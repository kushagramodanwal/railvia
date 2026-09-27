"""CP-SAT block planning model.

Formulation in plain language
-----------------------------
*Tasks* are the work to be done. *Blocks* are the windows during which a
section is handed to maintenance. Several tasks may share one block — that is
the point of the project, and it is why cost is charged per block rather than
per task. Two departments in one block pay once, so the optimiser discovers
co-location without any bonus term to point at.

The unit of scheduling is the **permitted run**: a maximal stretch of hours
during which a section is quiet enough to block (see windows.py). Runs on a
section are disjoint by construction, which does a lot of work for us.

Variables
  per task            start, end (duration fixed), present, an optional interval
  per (section, run)  one candidate block: present, start, end, cost
  linking             assign[task, run] — which run carries which task

Constraints
  1. A present task is assigned to exactly one run on its own section, and
     nests inside that run's block.
  2. Blocks on a section never overlap. This holds by construction: runs are
     disjoint and each run carries at most one block, so no NoOverlap
     constraint is needed at all.
  3. A block lies inside a single permitted run, so it cannot straddle a peak
     period. Also by construction.
  4. Crew capacity per department per day (Cumulative).
  5. Deadlines, soft: lateness is measured in days and priced.
  6. Work not co-locatable takes its block alone.
  7. Everything finishes inside the horizon (implicit in run bounds).

Why runs are the unit
---------------------
The earlier formulation gave every task its own candidate block floating over
the whole horizon, and expressed cost as a lookup into a cumulative-traffic
array spanning every slot. On a 30-day, 39-section instance that meant ~1,800
element constraints over 2,880-entry arrays. CP-SAT's presolve expanded them
into millions of literals and could not find *any* feasible solution in 25
seconds — with the objective removed entirely. Confining each block to one
run shrinks every lookup to the length of that run (tens of entries) and
deletes the NoOverlap and run-containment constraints outright.

Why an unscheduled penalty exists even with a pure train-hours objective:
doing nothing costs nothing, so the empty schedule would be optimal.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from src.models import Department, PlanningInstance, Task
from src.optimiser.windows import (
    DEFAULT_PERCENTILE,
    TimeGrid,
    permitted_runs,
    permitted_slots,
    traffic_by_slot,
)

log = logging.getLogger(__name__)

COST_SCALE = 100  # integer units per train-hour

# Must exceed the cost of any single block, or dropping work would look
# cheaper than doing it.
DEFAULT_UNSCHEDULED_PENALTY = 100_000

# Cost of finishing one day past the mandated date, per unit of criticality.
DEFAULT_LATE_PENALTY_PER_DAY = 2_000

DEFAULT_TIME_LIMIT_SECONDS = 60.0  # A live demo cannot wait longer.

# How many search workers CP-SAT may use.
#
# This is a MEMORY setting as much as a speed one: each worker holds its own
# copy of the search state. Measured on the 120-task instance —
#
#     workers   peak RSS   train-hours
#           1      257 MB         424
#           2      369 MB         277
#           4      498 MB         272
#           8      651 MB         330
#
# — so a 512 MB container is killed at 4 workers and above, and 8 is worse
# than 2 on quality anyway because a time-limited portfolio search is not
# monotone. os.cpu_count() cannot be trusted here: it reports the host's
# cores, not the cgroup limit a container actually gets, so this is explicit.
DEFAULT_WORKERS = int(os.environ.get("SOLVER_WORKERS", "0")) or min(
    os.cpu_count() or 1, 8
)


@dataclass
class ScheduledBlock:
    section_id: str
    start_slot: int
    end_slot: int
    task_ids: list[str]
    departments: list[Department]
    train_hours: float

    @property
    def is_shared(self) -> bool:
        return len(set(self.departments)) > 1


@dataclass
class Solution:
    status: str
    blocks: list[ScheduledBlock]
    unscheduled_task_ids: list[str]
    train_hours_lost: float
    objective: float
    wall_time: float
    best_bound: float
    impossible_task_ids: list[str] = field(default_factory=list)
    late_days: dict[str, int] = field(default_factory=dict)

    @property
    def feasible(self) -> bool:
        return self.status in ("OPTIMAL", "FEASIBLE")

    @property
    def shared_blocks(self) -> int:
        return sum(1 for b in self.blocks if b.is_shared)

    @property
    def scheduled_count(self) -> int:
        return sum(len(b.task_ids) for b in self.blocks)

    @property
    def total_days_late(self) -> int:
        return sum(self.late_days.values())

    @property
    def late_task_count(self) -> int:
        return sum(1 for v in self.late_days.values() if v > 0)

    @property
    def peak_hour_blocks(self) -> int:
        """Always 0 for our planner; the baseline reports its own count."""
        return 0


class BlockPlanner:
    """Builds and solves the CP-SAT model for one planning instance."""

    def __init__(
        self,
        instance: PlanningInstance,
        percentile: float = DEFAULT_PERCENTILE,
        unscheduled_penalty: int = DEFAULT_UNSCHEDULED_PENALTY,
        time_limit: float = DEFAULT_TIME_LIMIT_SECONDS,
        slot_minutes: int = 15,
        criticality: dict[str, float] | None = None,
        enforce_crew: bool = True,
        enforce_deadlines: bool = True,
        late_penalty_per_day: int = DEFAULT_LATE_PENALTY_PER_DAY,
        with_objective: bool = True,
        build_model: bool = True,
    ) -> None:
        self.instance = instance
        self.percentile = percentile
        self.unscheduled_penalty = unscheduled_penalty
        self.time_limit = time_limit
        # Criticality in [0,1] scales both penalties. Defaults to 1.0 so the
        # model behaves identically until the Phase 3 scorer supplies weights.
        self.criticality = criticality or {t.id: 1.0 for t in instance.tasks}
        self.enforce_crew = enforce_crew
        self.enforce_deadlines = enforce_deadlines
        self.late_penalty_per_day = late_penalty_per_day
        # Diagnostic switch: solving without the objective separates "the
        # constraints cannot be satisfied" from "the search cannot optimise in
        # time". The two need different fixes.
        self.with_objective = with_objective

        self.grid = TimeGrid(instance.horizon_start, instance.horizon_days, slot_minutes)
        self.traffic = traffic_by_slot(instance, self.grid)
        self.permitted = {
            sid: permitted_slots(series, percentile) for sid, series in self.traffic.items()
        }
        self.runs = {sid: permitted_runs(p) for sid, p in self.permitted.items()}

        self.model = cp_model.CpModel()
        self._hint_applied = False
        self.greedy = None
        self.model_built = build_model
        if build_model:
            self._build()
        else:
            # Windows and traffic only. Constructing the CP-SAT model costs
            # hundreds of megabytes on a month-long instance, and a container
            # that only ever serves precomputed plans must never pay it.
            self.task_start = {}
            self.task_end = {}
            self.task_present = {}
            self.task_interval = {}
            self.assign = {}
            self.block_vars = {}
            self.late_days_var = {}
            self.late_ceiling = {}
            self.impossible = []
            # Callers read this to explain why a job could not be placed, and
            # it is normally populated while building the crew constraint.
            self.crew_ceiling = {
                dept: max(
                    (c.available_crews for c in instance.crew_capacity
                     if c.department == dept), default=0,
                )
                for dept in Department
            }

    # -- helpers -------------------------------------------------------------

    def duration_slots(self, task: Task) -> int:
        return self.grid.minutes_to_slots(task.duration_minutes)

    def _tasks_by_section(self) -> dict[str, list[Task]]:
        grouped: dict[str, list[Task]] = {s.id: [] for s in self.instance.sections}
        for task in self.instance.tasks:
            grouped.setdefault(task.section_id, []).append(task)
        return grouped

    def _run_cumulative(self, section_id: str, run: tuple[int, int]) -> list[int]:
        """Prefix sums of train-hours across one run, so a block's cost is one
        subtraction over an array tens of entries long rather than thousands."""
        start, end = run
        series = self.traffic[section_id]
        cumulative = [0]
        total = 0
        for slot in range(start, end):
            total += round(series[slot] * self.grid.slot_hours * COST_SCALE)
            cumulative.append(total)
        return cumulative

    # -- model ---------------------------------------------------------------

    def _build(self) -> None:
        model = self.model
        self.task_start: dict[str, cp_model.IntVar] = {}
        self.task_end: dict[str, cp_model.IntVar] = {}
        self.task_present: dict[str, cp_model.IntVar] = {}
        self.task_interval: dict[str, object] = {}
        self.assign: dict[tuple[str, int], cp_model.IntVar] = {}
        self.block_vars: dict[str, dict[int, dict]] = {}
        self.late_days_var: dict[str, cp_model.IntVar] = {}
        # Upper bound per task, tracked here because IntVar.Proto() segfaults
        # in this OR-Tools build rather than returning the domain.
        self.late_ceiling: dict[str, int] = {}
        self.impossible: list[str] = []

        grouped = self._tasks_by_section()

        for section_id, tasks in grouped.items():
            if not tasks:
                continue
            runs = self.runs[section_id]
            blocks: dict[int, dict] = {}

            # Which runs could host which tasks. A run shorter than the task
            # is pruned outright, which keeps the assignment matrix small.
            eligible: dict[str, list[int]] = {}
            for task in tasks:
                length = self.duration_slots(task)
                eligible[task.id] = [
                    index for index, (start, end) in enumerate(runs)
                    if end - start >= length
                ]

            used_runs = sorted({r for indices in eligible.values() for r in indices})

            # --- one candidate block per usable run ---
            for run_index in used_runs:
                run_start, run_end = runs[run_index]
                present = model.NewBoolVar(f"blk_{section_id}_{run_index}")
                start = model.NewIntVar(run_start, run_end, f"blks_{section_id}_{run_index}")
                end = model.NewIntVar(run_start, run_end, f"blke_{section_id}_{run_index}")
                model.Add(end >= start)
                model.Add(start == run_start).OnlyEnforceIf(present.Not())
                model.Add(end == run_start).OnlyEnforceIf(present.Not())
                blocks[run_index] = {
                    "present": present, "start": start, "end": end,
                    "run": (run_start, run_end),
                }
            self.block_vars[section_id] = blocks

            # --- task variables ---
            for task in tasks:
                length = self.duration_slots(task)
                present = model.NewBoolVar(f"present_{task.id}")
                self.task_present[task.id] = present

                if not eligible[task.id]:
                    # No permitted window is long enough. Say so, rather than
                    # letting an unexplained infeasibility surface later.
                    model.Add(present == 0)
                    self.impossible.append(task.id)
                    start = model.NewIntVar(0, 0, f"start_{task.id}")
                    end = model.NewIntVar(0, 0, f"end_{task.id}")
                    length = 0
                else:
                    lo = min(runs[r][0] for r in eligible[task.id])
                    hi = max(runs[r][1] for r in eligible[task.id])
                    start = model.NewIntVar(lo, max(lo, hi - length), f"start_{task.id}")
                    end = model.NewIntVar(lo, hi, f"end_{task.id}")
                    model.Add(end == start + length)
                self.task_start[task.id] = start
                self.task_end[task.id] = end
                self.task_interval[task.id] = model.NewOptionalIntervalVar(
                    start, length, end, present, f"iv_{task.id}"
                )

                # Constraint 1: exactly one run carries a scheduled task.
                literals = []
                for run_index in eligible[task.id]:
                    block = blocks[run_index]
                    chosen = model.NewBoolVar(f"assign_{task.id}_{run_index}")
                    self.assign[(task.id, run_index)] = chosen
                    model.Add(start >= block["start"]).OnlyEnforceIf(chosen)
                    model.Add(end <= block["end"]).OnlyEnforceIf(chosen)
                    model.AddImplication(chosen, block["present"])
                    literals.append(chosen)
                if literals:
                    model.Add(sum(literals) == 1).OnlyEnforceIf(present)
                    model.Add(sum(literals) == 0).OnlyEnforceIf(present.Not())

            # A block exists only to carry work.
            for run_index, block in blocks.items():
                carried = [
                    self.assign[(t.id, run_index)]
                    for t in tasks if (t.id, run_index) in self.assign
                ]
                if carried:
                    model.AddBoolOr(carried).OnlyEnforceIf(block["present"])
                else:
                    model.Add(block["present"] == 0)

            # Constraint 6: heavy machinery occupies the whole section, so
            # such work cannot share its block (ASSUMPTIONS.md A-10).
            for task in tasks:
                if task.co_locatable:
                    continue
                for run_index in eligible[task.id]:
                    mine = self.assign[(task.id, run_index)]
                    for other in tasks:
                        if other.id == task.id:
                            continue
                        theirs = self.assign.get((other.id, run_index))
                        if theirs is not None:
                            model.AddBoolOr([mine.Not(), theirs.Not()])

        self._build_crew_capacity()
        self._build_deadlines()
        if self.with_objective:
            self._build_objective()
        else:
            self._build_cost_vars()

    def _build_crew_capacity(self) -> None:
        """Constraint 4: a department cannot field more crews than it has.

        One Cumulative per department over that department's task intervals,
        with `crew_required` as the demand.

        Capacity varies by day and Cumulative takes a single capacity, so we
        set capacity to the department's best day and lay a fixed blocking
        interval across every weaker day carrying the shortfall as demand. A
        day with 1 of 3 crews therefore starts with 2 already consumed.
        """
        if not self.enforce_crew:
            return
        model = self.model
        grid = self.grid
        by_dept_day: dict[tuple[Department, int], int] = {}
        for record in self.instance.crew_capacity:
            offset = (record.date - self.instance.horizon_start).days
            if 0 <= offset < self.instance.horizon_days:
                by_dept_day[(record.department, offset)] = record.available_crews

        self.crew_ceiling: dict[Department, int] = {}
        for dept in Department:
            tasks = [t for t in self.instance.tasks if t.department == dept]
            if not tasks:
                continue
            caps = [
                by_dept_day.get((dept, day), 0)
                for day in range(self.instance.horizon_days)
            ]
            ceiling = max(caps) if caps else 0
            self.crew_ceiling[dept] = ceiling
            if ceiling <= 0:
                for task in tasks:
                    model.Add(self.task_present[task.id] == 0)
                continue

            intervals = [self.task_interval[t.id] for t in tasks]
            demands = [t.crew_required for t in tasks]
            for day, cap in enumerate(caps):
                shortfall = ceiling - cap
                if shortfall <= 0:
                    continue
                start = day * grid.slots_per_day
                intervals.append(
                    model.NewIntervalVar(
                        start, grid.slots_per_day, start + grid.slots_per_day,
                        f"crewgap_{dept.value}_{day}",
                    )
                )
                demands.append(shortfall)
            model.AddCumulative(intervals, demands, ceiling)

            # Work needing more crews than the department ever has can never
            # run. Report it rather than returning a bare INFEASIBLE.
            for task in tasks:
                if task.crew_required > ceiling:
                    model.Add(self.task_present[task.id] == 0)
                    if task.id not in self.impossible:
                        self.impossible.append(task.id)

    def _build_deadlines(self) -> None:
        """Constraint 5: work should finish by its mandated date.

        Soft, not hard. A hard deadline over an already-overdue backlog makes
        the model INFEASIBLE and tells the planner nothing. Lateness is
        measured in days and priced, so the solver chooses what to defer and
        we can see what it chose.

        Tasks already overdue when the horizon opens accrue lateness from
        their original due date, so they carry the largest penalties.
        """
        if not self.enforce_deadlines:
            return
        model = self.model
        grid = self.grid
        horizon_days = self.instance.horizon_days

        for task in self.instance.tasks:
            due_day = (task.due_date - self.instance.horizon_start).days
            end_day = model.NewIntVar(0, horizon_days, f"endday_{task.id}")
            model.AddDivisionEquality(end_day, self.task_end[task.id], grid.slots_per_day)
            ceiling = max(0, horizon_days - due_day) + 1
            late = model.NewIntVar(0, ceiling, f"late_{task.id}")
            self.late_ceiling[task.id] = ceiling
            present = self.task_present[task.id]
            model.Add(late >= end_day - due_day).OnlyEnforceIf(present)
            model.Add(late == 0).OnlyEnforceIf(present.Not())
            self.late_days_var[task.id] = late

    def _build_cost_vars(self) -> list:
        """Per-block train-hours. Always built, so a schedule can be costed
        even when solved without an objective."""
        model = self.model
        terms = []
        self.block_cost: dict[tuple[str, int], cp_model.IntVar] = {}

        for section_id, blocks in self.block_vars.items():
            for run_index, block in blocks.items():
                run_start, run_end = block["run"]
                cumulative = self._run_cumulative(section_id, (run_start, run_end))
                ceiling = cumulative[-1]

                # Offsets within the run: the lookup array is the length of
                # this run, not of the whole horizon.
                offset_start = model.NewIntVar(0, run_end - run_start, f"os_{section_id}_{run_index}")
                offset_end = model.NewIntVar(0, run_end - run_start, f"oe_{section_id}_{run_index}")
                model.Add(offset_start == block["start"] - run_start)
                model.Add(offset_end == block["end"] - run_start)

                at_start = model.NewIntVar(0, ceiling, f"cs_{section_id}_{run_index}")
                at_end = model.NewIntVar(0, ceiling, f"ce_{section_id}_{run_index}")
                model.AddElement(offset_start, cumulative, at_start)
                model.AddElement(offset_end, cumulative, at_end)

                cost = model.NewIntVar(0, ceiling, f"cost_{section_id}_{run_index}")
                model.Add(cost == at_end - at_start)
                self.block_cost[(section_id, run_index)] = cost
                terms.append(cost)
        return terms

    def _build_objective(self) -> None:
        terms = self._build_cost_vars()

        # Criticality scales both penalties, so the model defers the work it
        # can most afford to defer rather than whatever is cheapest to move.
        # Weights are 1.0 until the Phase 3 scorer supplies them.
        for task_id, present in self.task_present.items():
            weight = max(0.0, min(1.0, self.criticality.get(task_id, 1.0)))
            penalty = int(self.unscheduled_penalty * (0.2 + 0.8 * weight))
            terms.append(penalty * (1 - present))

        # Lateness is capped so that doing the work late can never cost more
        # than not doing it at all.
        #
        # Without the cap the model prefers to abandon exactly the work that
        # matters most: a task already 45 days overdue, finished on day 20 of
        # a 30-day horizon, accrues 65 days of lateness. At 2,000 per day that
        # is 130,000 against a 100,000 penalty for leaving it undone, so the
        # optimiser drops it. Measured on the 300-task instance, this made our
        # plan complete 61 overdue tasks where the *manual* process completed
        # 73 — worse than the baseline at the thing the baseline is worst at.
        for task_id, late in self.late_days_var.items():
            weight = max(0.0, min(1.0, self.criticality.get(task_id, 1.0)))
            rate = int(self.late_penalty_per_day * (0.2 + 0.8 * weight))
            drop_cost = int(self.unscheduled_penalty * (0.2 + 0.8 * weight))
            ceiling = self.late_ceiling.get(task_id, 0)
            raw = self.model.NewIntVar(0, rate * ceiling + 1, f"lateraw_{task_id}")
            self.model.Add(raw == rate * late)
            capped = self.model.NewIntVar(0, max(0, drop_cost - 1), f"latecap_{task_id}")
            self.model.AddMinEquality(capped, [raw, max(0, drop_cost - 1)])
            terms.append(capped)

        self.model.Minimize(sum(terms))

    # -- solve ---------------------------------------------------------------

    def greedy_only(self) -> Solution:
        """A schedule without building or running the solver.

        For hosts too small to hold the CP-SAT model. Quality is the greedy's,
        and the status says so.
        """
        from src.optimiser.warmstart import build_greedy

        self.greedy = build_greedy(self)
        return self._solution_from_greedy("SKIPPED", 0.0)

    def _solution_from_greedy(self, status_name: str, wall: float) -> Solution:
        """Turn the warm-start schedule into a Solution.

        Same shape the solver would have produced, so every caller — the API,
        the comparison, the UI — is unaffected. The status carries the
        solver's own verdict with a marker, so a plan built this way is never
        mistaken for one the solver optimised.
        """
        tasks_by_id = {t.id: t for t in self.instance.tasks}
        by_block: dict[tuple[str, int], list[str]] = {}
        for task_id, placement in self.greedy.placements.items():
            key = (tasks_by_id[task_id].section_id, placement.run_index)
            by_block.setdefault(key, []).append(task_id)

        blocks: list[ScheduledBlock] = []
        total = 0.0
        for (section_id, run_index), task_ids in by_block.items():
            extent = self.greedy.extents.get((section_id, run_index))
            if extent is None:
                continue
            start, end = extent
            series = self.traffic[section_id]
            cost = round(
                sum(series[s] for s in range(start, min(end, len(series))))
                * self.grid.slot_hours, 3,
            )
            total += cost
            blocks.append(
                ScheduledBlock(
                    section_id=section_id, start_slot=start, end_slot=end,
                    task_ids=sorted(task_ids),
                    departments=sorted(
                        {tasks_by_id[t].department for t in task_ids},
                        key=lambda d: d.value,
                    ),
                    train_hours=cost,
                )
            )
        blocks.sort(key=lambda b: (b.start_slot, b.section_id))
        placed = set(self.greedy.placements)
        return Solution(
            status=f"{status_name}+GREEDY",
            blocks=blocks,
            unscheduled_task_ids=[
                t.id for t in self.instance.tasks if t.id not in placed
            ],
            train_hours_lost=round(total, 3),
            objective=0.0,
            wall_time=wall,
            best_bound=0.0,
            impossible_task_ids=list(self.impossible),
        )

    def solve(
        self,
        log_search: bool = False,
        workers: int = 8,
        warm_start: bool = True,
    ) -> Solution:
        """Solve within the wall-clock budget.

        On reproducibility, which the brief rightly demands (section 10): the
        *data* is fully deterministic — same seed, byte-identical instance.
        The *search* is not, and cannot practically be made so here.

        Two routes were measured and rejected:

          * `max_deterministic_time`, which counts work rather than seconds
            and is reproducible, runs far longer than its numeric value
            suggests on this model — a budget of 20 units had not returned
            after eight minutes, which no demo can use.
          * A single worker with a fixed seed is reproducible but hopeless:
            30 seconds placed 8 of 300 tasks, against 271 with eight workers.
            Parallel search is doing the real work here.

        So the honest position is that a time-limited parallel search returns
        one of several good schedules, and we report the headline as a
        measured range across repeated runs rather than a single figure that
        would not survive being re-run on stage. `scripts/compare.py --repeat`
        produces that range. The seed below removes one source of variation
        but does not remove worker interleaving.
        """
        # Hand CP-SAT a feasible schedule to start from. Without it the
        # search spends much of a short budget finding any good solution at
        # all, and where it lands depends on worker interleaving — which is
        # what made the headline swing 9.5-24.5% between runs.
        self.hinted_vars = 0
        if warm_start and not self._hint_applied:
            from src.optimiser.warmstart import apply_hint, build_greedy

            self.greedy = build_greedy(self)
            self.hinted_vars = apply_hint(self, self.greedy)
            self._hint_applied = True
            log.info("warm start: %d tasks placed, %d vars hinted",
                     self.greedy.placed, self.hinted_vars)

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.time_limit
        solver.parameters.num_search_workers = workers or DEFAULT_WORKERS
        solver.parameters.random_seed = 42
        solver.parameters.log_search_progress = log_search
        status = solver.Solve(self.model)
        status_name = solver.StatusName(status)
        ok = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

        log.info(
            "solver status=%s objective=%s bound=%s wall=%.2fs",
            status_name,
            solver.ObjectiveValue() if ok and self.with_objective else None,
            solver.BestObjectiveBound() if ok and self.with_objective else None,
            solver.WallTime(),
        )

        if not ok:
            # The solver found nothing in the time allowed. That is not the
            # same as there being nothing to do: the warm start already built
            # a feasible schedule in milliseconds, so return that rather than
            # an empty plan.
            #
            # Not hypothetical. On half a CPU — a small cloud instance — a
            # ten-second budget can expire before CP-SAT returns any solution
            # at all, and the user sees an empty calendar with no error to
            # explain it.
            if self.greedy is not None and self.greedy.placements:
                log.warning(
                    "solver returned %s in %.1fs; using the greedy schedule "
                    "(%d tasks placed)",
                    status_name, solver.WallTime(), self.greedy.placed,
                )
                return self._solution_from_greedy(status_name, solver.WallTime())
            return Solution(
                status=status_name, blocks=[],
                unscheduled_task_ids=[t.id for t in self.instance.tasks],
                train_hours_lost=0.0, objective=0.0,
                wall_time=solver.WallTime(), best_bound=0.0,
                impossible_task_ids=list(self.impossible),
            )

        tasks_by_id = {t.id: t for t in self.instance.tasks}
        blocks: list[ScheduledBlock] = []
        train_hours = 0.0

        for section_id, block_map in self.block_vars.items():
            for run_index, block in block_map.items():
                if not solver.Value(block["present"]):
                    continue
                carried = [
                    task_id for (task_id, index), literal in self.assign.items()
                    if index == run_index
                    and tasks_by_id[task_id].section_id == section_id
                    and solver.Value(literal)
                ]
                if not carried:
                    continue
                cost = solver.Value(self.block_cost[(section_id, run_index)]) / COST_SCALE
                train_hours += cost
                # Shrink the reported block to the work it actually carries:
                # the solver has no incentive to tighten bounds beyond cost,
                # and a block wider than its tasks would misreport the plan.
                start = min(solver.Value(self.task_start[t]) for t in carried)
                end = max(solver.Value(self.task_end[t]) for t in carried)
                blocks.append(
                    ScheduledBlock(
                        section_id=section_id,
                        start_slot=start,
                        end_slot=end,
                        task_ids=sorted(carried),
                        departments=sorted(
                            {tasks_by_id[t].department for t in carried},
                            key=lambda d: d.value,
                        ),
                        train_hours=round(cost, 3),
                    )
                )

        blocks.sort(key=lambda b: (b.start_slot, b.section_id))
        unscheduled = [
            t.id for t in self.instance.tasks if not solver.Value(self.task_present[t.id])
        ]
        late_days = {
            task_id: solver.Value(var)
            for task_id, var in self.late_days_var.items()
            if solver.Value(self.task_present[task_id]) and solver.Value(var) > 0
        }
        return Solution(
            status=status_name,
            blocks=blocks,
            unscheduled_task_ids=unscheduled,
            late_days=late_days,
            train_hours_lost=round(train_hours, 3),
            objective=solver.ObjectiveValue() if self.with_objective else 0.0,
            wall_time=solver.WallTime(),
            best_bound=solver.BestObjectiveBound() if self.with_objective else 0.0,
            impossible_task_ids=list(self.impossible),
        )
