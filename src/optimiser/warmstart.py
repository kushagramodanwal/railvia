"""Greedy constructive schedule, used as a CP-SAT solution hint.

Why this exists
---------------
A time-limited parallel search on the 300-task instance stops a long way
short of proving optimality, and *where* it stops depends on how the workers
interleave. Measured over four runs at a 60-second budget the headline
reduction ranged from 9.5% to 24.5%. A number that moves fifteen points
between runs cannot be quoted on a slide.

The usual fix is to stop making the solver find its first good solution from
nothing. This module builds a feasible schedule directly — cheap, ordered,
deterministic — and hands it to CP-SAT as a hint. The solver then spends its
whole budget improving a decent plan rather than hunting for one, which both
raises the floor and narrows the spread.

The heuristic is deliberately simple and mirrors the objective:

  * Tasks are ordered by criticality, then urgency. Whatever gets dropped
    should be what we could most afford to drop.
  * Each task prefers a run that ALREADY has work on it and can absorb the
    task inside the existing block extent. That is free — cost is charged per
    block, not per task — and it is exactly the co-location the project is
    about.
  * Failing that, it takes the cheapest run that still fits, measured in
    train-hours over the slots the block would actually occupy.
  * Crew capacity is respected per department per day, so the hint is
    feasible rather than merely plausible.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.models import Department, Task


@dataclass
class Placement:
    run_index: int
    start_slot: int
    end_slot: int


@dataclass
class GreedyResult:
    placements: dict[str, Placement] = field(default_factory=dict)
    # run_index -> (start, end) extent of the block on that run
    extents: dict[tuple[str, int], tuple[int, int]] = field(default_factory=dict)
    unplaced: list[str] = field(default_factory=list)

    @property
    def placed(self) -> int:
        return len(self.placements)


def build_greedy(planner) -> GreedyResult:
    """Construct a feasible schedule for `planner`'s instance."""
    instance = planner.instance
    grid = planner.grid
    result = GreedyResult()

    # Crew ledger, tracked PER SLOT rather than per day.
    #
    # The model limits crews with AddCumulative, which caps how many run
    # *concurrently*. Charging a daily quota instead — as this heuristic first
    # did — is far stricter: it saturated 89 of 90 crew-days and stalled at
    # 200 of 300 tasks, because it could not see that a day holds several
    # sequential jobs. A hint built on the wrong resource semantics drags the
    # solver toward a worse region than it would have found alone.
    capacity: dict[tuple[Department, int], int] = {}
    for record in instance.crew_capacity:
        offset = (record.date - instance.horizon_start).days
        if 0 <= offset < instance.horizon_days:
            capacity[(record.department, offset)] = record.available_crews
    n_slots = grid.n_slots
    used: dict[Department, list[int]] = {
        dept: [0] * n_slots for dept in Department
    }

    def cost(section_id: str, start: int, end: int) -> float:
        """Train-hours lost over [start, end). The planner keeps its prefix
        sums per run; for the heuristic a direct sum is simpler and plenty
        fast at this size."""
        series = planner.traffic[section_id]
        stop = min(end, len(series))
        return sum(series[s] for s in range(start, stop)) * grid.slot_hours

    def crew_ok(task: Task, start: int, end: int) -> bool:
        ledger = used[task.department]
        for slot in range(start, min(end, n_slots)):
            have = capacity.get((task.department, slot // grid.slots_per_day), 0)
            if ledger[slot] + task.crew_required > have:
                return False
        return True

    def commit_crew(task: Task, start: int, end: int) -> None:
        ledger = used[task.department]
        for slot in range(start, min(end, n_slots)):
            ledger[slot] += task.crew_required

    # Most critical and most urgent first: whatever falls off the end should
    # be the work we could most afford to defer.
    ordered = sorted(
        instance.tasks,
        key=lambda t: (
            -planner.criticality.get(t.id, 1.0),
            t.due_date,
            -t.defect_severity.value,
            t.id,
        ),
    )

    for task in ordered:
        runs = planner.runs.get(task.section_id, [])
        length = planner.duration_slots(task)
        if not runs or length <= 0:
            result.unplaced.append(task.id)
            continue

        best: tuple[float, int, int] | None = None  # (cost delta, run, start)

        for run_index, (run_start, run_end) in enumerate(runs):
            if run_end - run_start < length:
                continue
            key = (task.section_id, run_index)
            extent = result.extents.get(key)

            if extent is not None:
                open_start, open_end = extent
                # Co-location: does it fit inside what is already blocked?
                # A task that does costs nothing extra at all.
                if not task.co_locatable:
                    continue
                shares = any(
                    not other.co_locatable
                    for other in instance.tasks
                    if result.placements.get(other.id)
                    and other.section_id == task.section_id
                    and result.placements[other.id].run_index == run_index
                )
                if shares:
                    continue
                if open_end - open_start >= length and crew_ok(task, open_start, open_start + length):
                    candidate = (0.0, run_index, open_start)
                    if best is None or candidate[0] < best[0]:
                        best = candidate
                    continue
                # Otherwise extend the block to the right, paying only the
                # extra slots.
                new_end = min(run_end, open_start + length)
                if new_end - open_start >= length and crew_ok(task, open_start, new_end):
                    delta = cost(task.section_id, open_end, new_end)
                    candidate = (delta, run_index, open_start)
                    if best is None or delta < best[0]:
                        best = candidate
                continue

            # Fresh block on this run: try the cheapest position in it.
            positions = range(run_start, run_end - length + 1)
            step = max(1, grid.slots_per_hour // 2)
            for start in list(positions)[::step] or [run_start]:
                if not crew_ok(task, start, start + length):
                    continue
                delta = cost(task.section_id, start, start + length)
                if best is None or delta < best[0]:
                    best = (delta, run_index, start)

        if best is None:
            result.unplaced.append(task.id)
            continue

        _, run_index, start = best
        end = start + length
        commit_crew(task, start, end)
        result.placements[task.id] = Placement(run_index, start, end)
        key = (task.section_id, run_index)
        if key in result.extents:
            old_start, old_end = result.extents[key]
            result.extents[key] = (min(old_start, start), max(old_end, end))
        else:
            result.extents[key] = (start, end)

    return result


def apply_hint(planner, greedy: GreedyResult) -> int:
    """Feed the greedy schedule to CP-SAT as a solution hint.

    Returns the number of hinted variables. A hint is advisory: CP-SAT will
    repair or discard it if it conflicts, so a mistake here costs search time
    rather than correctness.
    """
    model = planner.model
    hinted = 0
    seen: set[int] = set()

    def hint(var, value):
        nonlocal hinted
        key = id(var)
        if key in seen:
            return
        seen.add(key)
        model.AddHint(var, value)
        hinted += 1

    for task in planner.instance.tasks:
        placement = greedy.placements.get(task.id)
        present = planner.task_present.get(task.id)
        if present is None:
            continue
        if placement is None:
            if task.id not in planner.impossible:
                hint(present, 0)
            continue
        hint(present, 1)
        start = planner.task_start.get(task.id)
        if start is not None:
            hint(start, placement.start_slot)
        for (task_id, run_index), literal in planner.assign.items():
            if task_id != task.id:
                continue
            hint(literal, 1 if run_index == placement.run_index else 0)

    for section_id, blocks in planner.block_vars.items():
        for run_index, block in blocks.items():
            extent = greedy.extents.get((section_id, run_index))
            if extent is None:
                hint(block["present"], 0)
                hint(block["start"], block["run"][0])
                hint(block["end"], block["run"][0])
            else:
                hint(block["present"], 1)
                hint(block["start"], extent[0])
                hint(block["end"], extent[1])

    return hinted
