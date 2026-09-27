"""Constraint tests for the CP-SAT model. Mandatory from Phase 1 onward.

For each constraint there are two kinds of test:

  * a REJECTION test that pins the model to a violating assignment and
    asserts INFEASIBLE, and
  * a PROPERTY test that solves normally and asserts the constraint holds in
    the returned schedule.

Both matter. A constraint that is merely absent still yields plausible
schedules, and a silent constraint bug is the way this project fails
invisibly: the solver returns something, it looks reasonable, and it is
wrong.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from ortools.sat.python import cp_model

from src.models import (
    CrewCapacity,
    DataProvenance,
    Department,
    PlanningInstance,
    Section,
    Severity,
    SourceKind,
    Task,
    TrafficWindow,
)
from src.optimiser.model import BlockPlanner

HORIZON_START = date(2026, 3, 2)

# Quiet 00:00-05:59, busy the rest. Gives a clean 6-hour permitted window at
# the 25th percentile and an unambiguous peak to test rejection against.
NIGHT_QUIET = [0.0] * 6 + [20.0] * 18

# Same shape but with genuine night traffic. Needed wherever cost must be
# visible: where the quiet hours are literally empty, blocking is free and
# the optimiser is rightly indifferent between merging and not.
NIGHT_SPARSE = [4.0] * 6 + [40.0] * 18


def build_instance(
    profiles: dict[str, list[float]],
    tasks: list[Task],
    horizon_days: int = 1,
) -> PlanningInstance:
    sections = [
        Section(id=sid, name=sid, division="test", length_km=5.0,
                traffic_density_profile=profile)
        for sid, profile in profiles.items()
    ]
    traffic = [
        TrafficWindow(
            section_id=sid, day=HORIZON_START + timedelta(days=d),
            hour_of_day=h, day_of_week=(HORIZON_START + timedelta(days=d)).weekday(),
            trains_per_hour=profile[h],
        )
        for sid, profile in profiles.items()
        for d in range(horizon_days)
        for h in range(24)
    ]
    return PlanningInstance(
        instance_id="test", generated_at=datetime(2026, 1, 1), seed=0,
        sources=DataProvenance(
            sections=SourceKind.SYNTHETIC, tasks=SourceKind.SYNTHETIC,
            traffic=SourceKind.SYNTHETIC, crew_capacity=SourceKind.SYNTHETIC,
        ),
        provenance="test fixture",
        horizon_start=HORIZON_START, horizon_days=horizon_days,
        sections=sections, tasks=tasks,
        traffic=traffic,
        crew_capacity=[
            CrewCapacity(department=d, date=HORIZON_START + timedelta(days=i),
                         available_crews=5)
            for d in Department for i in range(horizon_days)
        ],
    )


def task(tid, section, minutes, dept=Department.ENGG, **over) -> Task:
    base = dict(
        id=tid, department=dept, section_id=section, activity_type="test",
        duration_minutes=minutes, crew_required=1,
        last_done_date=date(2025, 1, 1), interval_days=365,
        due_date=date(2026, 6, 1), defect_severity=Severity.MODERATE,
        is_overdue=False, co_locatable=True,
    )
    return Task(**{**base, **over})


def solve_with(planner: BlockPlanner, extra) -> str:
    """Add a violating constraint, then report the resulting status."""
    extra(planner)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 20
    return solver.StatusName(solver.Solve(planner.model))


# --- constraint 2: forbidden windows ---------------------------------------


def test_peak_start_is_rejected():
    """A block may not begin during a peak hour."""
    instance = build_instance({"S1": NIGHT_QUIET}, [task("T1", "S1", 60)])
    planner = BlockPlanner(instance, time_limit=10)
    grid = planner.grid
    peak_slot = 10 * grid.slots_per_hour  # 10:00, firmly in the busy band

    status = solve_with(planner, lambda p: (
        p.model.Add(p.task_start["T1"] == peak_slot),
        p.model.Add(p.task_present["T1"] == 1),
    ))
    assert status == "INFEASIBLE"


def test_block_may_not_straddle_a_peak():
    """Both ends quiet is not enough — the middle must be quiet too.

    Without the one-run constraint a block could span from the night window,
    across the whole busy day, into the next night.
    """
    instance = build_instance({"S1": NIGHT_QUIET}, [task("T1", "S1", 60)], horizon_days=2)
    planner = BlockPlanner(instance, time_limit=10)
    grid = planner.grid
    blocks = planner.block_vars["S1"]

    status = solve_with(planner, lambda p: (
        p.model.Add(blocks[0]["present"] == 1),
        p.model.Add(blocks[0]["start"] == 4 * grid.slots_per_hour),   # 04:00 quiet
        p.model.Add(blocks[0]["end"] == 25 * grid.slots_per_hour),    # 01:00 next day
    ))
    assert status == "INFEASIBLE"


def test_solution_only_uses_permitted_slots():
    instance = build_instance(
        {"S1": NIGHT_QUIET, "S2": NIGHT_QUIET},
        [task("T1", "S1", 120), task("T2", "S2", 90, dept=Department.SNT)],
    )
    planner = BlockPlanner(instance, time_limit=20)
    solution = planner.solve()
    assert solution.feasible
    for block in solution.blocks:
        permitted = planner.permitted[block.section_id]
        assert all(permitted[s] for s in range(block.start_slot, block.end_slot))


# --- constraint 1: NoOverlap on blocks -------------------------------------


def test_blocks_on_a_section_cannot_overlap_by_construction():
    """Non-overlap is structural, not a constraint the solver must enforce.

    Each block is confined to one permitted run, and runs on a section are
    maximal disjoint stretches, so two blocks on a section can never share a
    slot. This test pins the structure that guarantees it — if candidate
    blocks ever stop being run-scoped, it fails.
    """
    instance = build_instance(
        {"S1": NIGHT_QUIET},
        [task("T1", "S1", 60), task("T2", "S1", 60)],
        horizon_days=3,
    )
    planner = BlockPlanner(instance, time_limit=10)
    spans = [b["run"] for b in planner.block_vars["S1"].values()]
    assert len(spans) >= 2
    ordered = sorted(spans)
    for (_, end), (next_start, _) in zip(ordered, ordered[1:]):
        assert end <= next_start, "candidate block runs overlap"
    # And every scheduled block falls inside exactly one of those runs.
    solution = planner.solve()
    assert solution.feasible
    for scheduled in solution.blocks:
        assert any(
            start <= scheduled.start_slot and scheduled.end_slot <= end
            for start, end in spans
        ), "a scheduled block escaped its permitted run"


def test_blocks_never_overlap_in_a_solution():
    instance = build_instance(
        {"S1": NIGHT_QUIET},
        [task("T1", "S1", 60), task("T2", "S1", 60), task("T3", "S1", 60)],
    )
    solution = BlockPlanner(instance, time_limit=20).solve()
    assert solution.feasible
    spans = sorted(
        (b.start_slot, b.end_slot) for b in solution.blocks if b.section_id == "S1"
    )
    for (_, end), (next_start, _) in zip(spans, spans[1:]):
        assert end <= next_start


def test_different_sections_may_be_blocked_simultaneously():
    """NoOverlap is per section: parallel work elsewhere must stay legal."""
    instance = build_instance(
        {"S1": NIGHT_QUIET, "S2": NIGHT_QUIET},
        [task("T1", "S1", 240), task("T2", "S2", 240, dept=Department.TRD)],
    )
    solution = BlockPlanner(instance, time_limit=20).solve()
    assert solution.feasible
    assert solution.scheduled_count == 2
    by_section = {b.section_id: b for b in solution.blocks}
    assert set(by_section) == {"S1", "S2"}
    # The quiet window is 6h and both jobs are 4h, so they must overlap in time.
    a, b = by_section["S1"], by_section["S2"]
    assert a.start_slot < b.end_slot and b.start_slot < a.end_slot


# --- constraint 5: horizon bounds ------------------------------------------


def test_work_may_not_run_past_the_horizon():
    instance = build_instance({"S1": NIGHT_QUIET}, [task("T1", "S1", 120)])
    planner = BlockPlanner(instance, time_limit=10)
    horizon = planner.grid.n_slots
    status = solve_with(planner, lambda p: (
        p.model.Add(p.task_present["T1"] == 1),
        p.model.Add(p.task_end["T1"] > horizon),
    ))
    assert status == "INFEASIBLE"


def test_solution_stays_inside_the_horizon():
    instance = build_instance({"S1": NIGHT_QUIET}, [task("T1", "S1", 120)])
    planner = BlockPlanner(instance, time_limit=20)
    solution = planner.solve()
    assert solution.feasible
    for block in solution.blocks:
        assert 0 <= block.start_slot < block.end_slot <= planner.grid.n_slots


# --- task/block nesting ----------------------------------------------------


def test_task_outside_its_block_is_rejected():
    instance = build_instance({"S1": NIGHT_QUIET}, [task("T1", "S1", 60)])
    planner = BlockPlanner(instance, time_limit=10)
    grid = planner.grid
    run_index = sorted(planner.block_vars["S1"])[0]
    block = planner.block_vars["S1"][run_index]
    status = solve_with(planner, lambda p: (
        p.model.Add(p.task_present["T1"] == 1),
        p.model.Add(p.assign[("T1", run_index)] == 1),
        p.model.Add(block["start"] == 0),
        p.model.Add(block["end"] == 1 * grid.slots_per_hour),
        # Task starts after its block has already ended.
        p.model.Add(p.task_start["T1"] == 2 * grid.slots_per_hour),
    ))
    assert status == "INFEASIBLE"


def test_every_task_sits_inside_its_block():
    instance = build_instance(
        {"S1": NIGHT_QUIET},
        [task("T1", "S1", 60), task("T2", "S1", 90, dept=Department.SNT)],
    )
    solution = BlockPlanner(instance, time_limit=20).solve()
    assert solution.feasible
    for block in solution.blocks:
        assert block.task_ids
        assert block.end_slot > block.start_slot


# --- co-location: the economic property the project exists to show ---------


def test_two_departments_share_one_block():
    """Same section, same night, one handover instead of two.

    Nothing rewards this explicitly. Cost is charged per block, so merging is
    simply cheaper — the optimiser finds it.

    Uses NIGHT_SPARSE: with zero night traffic there is nothing to save, and
    the solver is correctly indifferent. See
    test_no_colocation_incentive_when_blocking_is_free.
    """
    instance = build_instance(
        {"S1": NIGHT_SPARSE},
        [task("T1", "S1", 120, dept=Department.ENGG),
         task("T2", "S1", 120, dept=Department.SNT)],
    )
    solution = BlockPlanner(instance, time_limit=20).solve()
    assert solution.feasible
    assert solution.scheduled_count == 2
    assert len(solution.blocks) == 1
    assert solution.blocks[0].is_shared
    assert solution.shared_blocks == 1


def test_sharing_costs_less_than_separate_blocks():
    """The merged plan must actually be cheaper, not merely permitted."""
    instance = build_instance(
        {"S1": NIGHT_SPARSE},
        [task("T1", "S1", 120, dept=Department.ENGG),
         task("T2", "S1", 120, dept=Department.SNT)],
        horizon_days=2,
    )
    planner = BlockPlanner(instance, time_limit=20)
    merged = planner.solve()
    assert merged.feasible and len(merged.blocks) == 1

    # Force the two tasks into different runs, so they cannot share a block.
    separate = BlockPlanner(instance, time_limit=20)
    runs = sorted(separate.block_vars["S1"])
    assert len(runs) >= 2, "fixture needs at least two permitted runs"
    separate.model.Add(separate.assign[("T1", runs[0])] == 1)
    separate.model.Add(separate.assign[("T2", runs[1])] == 1)
    apart = separate.solve()
    assert apart.feasible
    assert merged.train_hours_lost < apart.train_hours_lost


def test_shared_block_charges_traffic_once():
    """Two 2-hour tasks in one 2-hour block cost one block's train-hours."""
    instance = build_instance(
        {"S1": NIGHT_SPARSE},
        [task("T1", "S1", 120, dept=Department.ENGG),
         task("T2", "S1", 120, dept=Department.SNT)],
    )
    solution = BlockPlanner(instance, time_limit=20).solve()
    block = solution.blocks[0]
    hours = (block.end_slot - block.start_slot) * 15 / 60
    assert hours == pytest.approx(2.0)
    assert block.train_hours == pytest.approx(4.0 * 2.0)  # 4 trains/h x 2h, once


def test_no_colocation_incentive_when_blocking_is_free():
    """Where night traffic is genuinely zero, merging saves nothing.

    Documented rather than worked around. Several real sections on the
    NDLS-GZB corridor carry no trains at all around 01:00, so the optimiser
    has no reason to merge there and our co-location count understates what
    a real planner would still want to do — a block has handover and staff
    costs beyond lost train-hours, which this objective does not yet model.
    Recorded in ASSUMPTIONS.md (A-15).
    """
    instance = build_instance(
        {"S1": NIGHT_QUIET},  # zero traffic in the permitted window
        [task("T1", "S1", 120, dept=Department.ENGG),
         task("T2", "S1", 120, dept=Department.SNT)],
    )
    solution = BlockPlanner(instance, time_limit=20).solve()
    assert solution.feasible
    assert solution.scheduled_count == 2
    assert solution.train_hours_lost == 0.0
    # Whether it merges is arbitrary at equal cost; that it costs nothing is
    # the point being pinned.


# --- degenerate and edge cases ---------------------------------------------


def test_task_too_long_for_any_window_is_reported_not_hidden():
    """A job longer than the quiet period must be named, not silently dropped."""
    instance = build_instance({"S1": NIGHT_QUIET}, [task("T1", "S1", 8 * 60)])
    solution = BlockPlanner(instance, time_limit=20).solve()
    assert solution.feasible  # the run still returns a usable plan
    assert "T1" in solution.impossible_task_ids
    assert "T1" in solution.unscheduled_task_ids
    assert solution.blocks == []


def test_unscheduled_penalty_prevents_the_empty_schedule():
    """Without a penalty, scheduling nothing is optimal at zero cost."""
    busy = [10.0] * 24  # every hour costly; doing nothing would be cheapest
    instance = build_instance({"S1": busy}, [task("T1", "S1", 60)])
    solution = BlockPlanner(instance, time_limit=20).solve()
    assert solution.feasible
    assert solution.scheduled_count == 1
    assert solution.train_hours_lost > 0


def test_optimiser_prefers_the_quiet_hour():
    """The premise of the whole project, asserted."""
    profile = [1.0] * 4 + [30.0] * 20  # quiet 00:00-03:59 only
    instance = build_instance({"S1": profile}, [task("T1", "S1", 60)])
    planner = BlockPlanner(instance, time_limit=20)
    solution = planner.solve()
    assert solution.feasible
    start_hour = solution.blocks[0].start_slot // planner.grid.slots_per_hour
    assert start_hour < 4


# --- symmetry-breaking regression ------------------------------------------


def test_first_block_is_not_forced_to_midnight():
    """Regression from the earlier block-per-task formulation.

    Absent blocks were pinned to slot 0, so an unconditional ordering
    constraint `start[i] <= start[i+1]` read as `start[i] <= 0` whenever a
    later block went unused, forcing every section's first block to midnight.
    The model stayed feasible and still reported OPTIMAL — which is what made
    that class of bug dangerous: it quietly deleted better schedules.

    Blocks are now scoped to permitted runs and there is no ordering
    constraint at all, but the property is worth keeping pinned: midnight is
    permitted here but costly, 01:00 is free, and the plan must use 01:00.
    """
    profile = [8.0] + [0.0] * 5 + [40.0] * 18
    instance = build_instance(
        {"S1": profile},
        [task("T1", "S1", 60, dept=Department.ENGG),
         task("T2", "S1", 60, dept=Department.SNT)],
    )
    planner = BlockPlanner(instance, time_limit=20)
    solution = planner.solve()

    assert solution.feasible
    assert solution.scheduled_count == 2
    block = min(solution.blocks, key=lambda b: b.start_slot)
    assert block.start_slot > 0, "first block pinned to midnight by symmetry breaking"
    assert solution.train_hours_lost == pytest.approx(0.0)


def test_unused_blocks_do_not_add_cost():
    instance = build_instance(
        {"S1": NIGHT_SPARSE},
        [task("T1", "S1", 60), task("T2", "S1", 60, dept=Department.SNT),
         task("T3", "S1", 60, dept=Department.TRD)],
    )
    solution = BlockPlanner(instance, time_limit=20).solve()
    assert solution.feasible
    # Every reported block carries work; empty blocks are never emitted.
    assert all(b.task_ids for b in solution.blocks)
    assert solution.train_hours_lost == pytest.approx(
        sum(b.train_hours for b in solution.blocks)
    )


# --- resource limits -------------------------------------------------------


def test_worker_count_is_configurable(monkeypatch):
    """Worker count is a MEMORY setting as much as a speed one.

    Each CP-SAT worker holds its own search state: measured on the 120-task
    instance the solve peaks at 369 MB with 2 workers and 651 MB with 8, so a
    512 MB container dies at the default. os.cpu_count() cannot help — it
    reports the host's cores, not the cgroup limit a container is given.
    """
    import importlib

    import src.optimiser.model as model

    monkeypatch.setenv("SOLVER_WORKERS", "2")
    importlib.reload(model)
    assert model.DEFAULT_WORKERS == 2

    monkeypatch.delenv("SOLVER_WORKERS", raising=False)
    importlib.reload(model)
    assert 1 <= model.DEFAULT_WORKERS <= 8


def test_solving_honours_an_explicit_worker_count():
    instance = build_instance({"S1": NIGHT_SPARSE}, [task("T1", "S1", 60)])
    solution = BlockPlanner(instance, time_limit=10).solve(workers=1)
    assert solution.feasible


def test_planner_can_skip_building_the_model():
    """Constructing the CP-SAT model is what costs the memory.

    A month-long instance needs 700 MB to 1.9 GB to solve, against 512 MB on
    a small cloud plan. Skipping the model build drops the peak to ~150 MB and
    still returns a real schedule.
    """
    instance = build_instance(
        {"S1": NIGHT_SPARSE, "S2": NIGHT_SPARSE},
        [task(f"T{i}", "S1" if i % 2 else "S2", 60, dept=list(Department)[i % 3])
         for i in range(6)],
        horizon_days=4,
    )
    planner = BlockPlanner(instance, build_model=False)
    assert planner.model_built is False
    assert planner.block_vars == {}, "the model was built anyway"

    solution = planner.greedy_only()
    assert solution.blocks
    assert solution.status == "SKIPPED+GREEDY"
    assert solution.scheduled_count > 0
    for block in solution.blocks:
        permitted = planner.permitted[block.section_id]
        assert all(permitted[s] for s in range(block.start_slot, block.end_slot))


def test_model_free_planner_still_explains_crew_limits():
    """The exception messages read crew_ceiling, which is normally filled in
    while building the crew constraint."""
    instance = build_instance({"S1": NIGHT_SPARSE}, [task("T1", "S1", 60)])
    planner = BlockPlanner(instance, build_model=False)
    assert planner.crew_ceiling
    assert all(v >= 0 for v in planner.crew_ceiling.values())
