"""The greedy warm start.

It only ever feeds CP-SAT a hint, so a bug here cannot make the schedule
wrong — but it can make it much worse, which is exactly what happened when
the heuristic modelled crew as a daily quota instead of a concurrency limit.
These tests pin the semantics that matter.
"""

from __future__ import annotations

from src.models import Department
from src.optimiser.model import BlockPlanner
from src.optimiser.warmstart import build_greedy
from tests.test_optimiser_constraints import (
    NIGHT_QUIET,
    NIGHT_SPARSE,
    build_instance,
    task,
)


def test_greedy_places_work_in_permitted_windows_only():
    instance = build_instance(
        {"S1": NIGHT_SPARSE, "S2": NIGHT_SPARSE},
        [task(f"T{i}", "S1" if i % 2 else "S2", 60, dept=list(Department)[i % 3])
         for i in range(6)],
        horizon_days=4,
    )
    planner = BlockPlanner(instance, time_limit=5)
    greedy = build_greedy(planner)
    for task_id, placement in greedy.placements.items():
        section = next(t.section_id for t in instance.tasks if t.id == task_id)
        permitted = planner.permitted[section]
        for slot in range(placement.start_slot, placement.end_slot):
            assert permitted[slot], f"{task_id} placed outside a permitted window"


def test_greedy_respects_crew_as_a_concurrency_limit():
    """Regression: crew is a Cumulative capacity, not a daily quota.

    Treating it as a daily total let only 200 of 300 tasks be placed on the
    real instance, because the heuristic could not see that one day holds
    several sequential jobs. The hint then dragged the solver toward a worse
    schedule than it found unaided.
    """
    instance = build_instance(
        {"S1": NIGHT_SPARSE},
        [task(f"T{i}", "S1", 60, dept=Department.ENGG, crew_required=1)
         for i in range(4)],
        horizon_days=1,
    )
    planner = BlockPlanner(instance, time_limit=5)
    greedy = build_greedy(planner)
    # The quiet window is six hours and each job is one hour, so a department
    # with any crew at all should fit several sequentially in a single day.
    assert greedy.placed >= 3


def test_greedy_never_exceeds_concurrent_crew_capacity():
    instance = build_instance(
        {"S1": NIGHT_SPARSE, "S2": NIGHT_SPARSE},
        [task(f"T{i}", "S1" if i % 2 else "S2", 120, dept=Department.ENGG,
              crew_required=2) for i in range(6)],
        horizon_days=3,
    )
    planner = BlockPlanner(instance, time_limit=5)
    greedy = build_greedy(planner)
    grid = planner.grid
    caps = {
        (c.date - instance.horizon_start).days: c.available_crews
        for c in instance.crew_capacity if c.department == Department.ENGG
    }
    by_id = {t.id: t for t in instance.tasks}
    load: dict[int, int] = {}
    for task_id, placement in greedy.placements.items():
        for slot in range(placement.start_slot, placement.end_slot):
            load[slot] = load.get(slot, 0) + by_id[task_id].crew_required
    for slot, used in load.items():
        assert used <= caps[slot // grid.slots_per_day]


def test_greedy_prefers_sharing_a_block():
    """Two departments, one section, one quiet window: the cheap answer is
    one block carrying both."""
    instance = build_instance(
        {"S1": NIGHT_SPARSE},
        [task("T1", "S1", 120, dept=Department.ENGG),
         task("T2", "S1", 120, dept=Department.SNT)],
        horizon_days=1,
    )
    planner = BlockPlanner(instance, time_limit=5)
    greedy = build_greedy(planner)
    assert greedy.placed == 2
    assert len(greedy.extents) == 1, "greedy opened two blocks where one would do"


def test_greedy_keeps_exclusive_work_alone():
    instance = build_instance(
        {"S1": NIGHT_SPARSE},
        [task("SOLO", "S1", 120, dept=Department.ENGG, co_locatable=False),
         task("OTHER", "S1", 60, dept=Department.SNT)],
        horizon_days=2,
    )
    planner = BlockPlanner(instance, time_limit=5)
    greedy = build_greedy(planner)
    solo = greedy.placements.get("SOLO")
    other = greedy.placements.get("OTHER")
    if solo and other:
        assert solo.run_index != other.run_index


def test_hint_is_applied_and_solver_still_correct():
    instance = build_instance(
        {"S1": NIGHT_SPARSE, "S2": NIGHT_SPARSE},
        [task(f"T{i}", "S1" if i % 2 else "S2", 60, dept=list(Department)[i % 3])
         for i in range(6)],
        horizon_days=3,
    )
    planner = BlockPlanner(instance, time_limit=10)
    solution = planner.solve(warm_start=True)
    assert solution.feasible
    assert planner.hinted_vars > 0
    # A hint must never let a block escape its permitted window.
    for block in solution.blocks:
        permitted = planner.permitted[block.section_id]
        assert all(permitted[s] for s in range(block.start_slot, block.end_slot))


def test_solving_without_a_hint_still_works():
    instance = build_instance(
        {"S1": NIGHT_SPARSE}, [task("T1", "S1", 60)], horizon_days=2
    )
    planner = BlockPlanner(instance, time_limit=10)
    solution = planner.solve(warm_start=False)
    assert solution.feasible
    assert planner.hinted_vars == 0


def test_impossible_tasks_are_left_unplaced():
    instance = build_instance({"S1": NIGHT_QUIET}, [task("T1", "S1", 8 * 60)])
    planner = BlockPlanner(instance, time_limit=5)
    greedy = build_greedy(planner)
    assert "T1" in greedy.unplaced


def test_greedy_fallback_produces_a_usable_schedule():
    """A solver that returns nothing must not produce an empty calendar.

    On a constrained instance — half a CPU on a small cloud plan — a short
    budget can expire before CP-SAT returns any solution at all. The warm
    start has already built a feasible schedule in milliseconds, so that is
    what the user should get; the symptom otherwise is a month of empty days
    with no error to explain it.

    The fallback is exercised directly rather than by starving the solver: a
    small instance solves instantly however little time it is given, so a
    timing-based test would pass for the wrong reason.
    """
    instance = build_instance(
        {"S1": NIGHT_SPARSE, "S2": NIGHT_SPARSE},
        [task(f"T{i}", "S1" if i % 2 else "S2", 60, dept=list(Department)[i % 3])
         for i in range(8)],
        horizon_days=5,
    )
    planner = BlockPlanner(instance, time_limit=10)
    planner.greedy = build_greedy(planner)
    solution = planner._solution_from_greedy("UNKNOWN", 0.4)

    assert solution.blocks, "fallback produced nothing"
    assert solution.scheduled_count > 0
    assert solution.train_hours_lost >= 0
    # Every block carries work and has positive duration.
    for block in solution.blocks:
        assert block.task_ids
        assert block.end_slot > block.start_slot


def test_greedy_fallback_is_labelled_not_disguised():
    """A plan the solver did not optimise must say so."""
    instance = build_instance(
        {"S1": NIGHT_SPARSE},
        [task("T1", "S1", 60), task("T2", "S1", 60, dept=Department.SNT)],
        horizon_days=3,
    )
    planner = BlockPlanner(instance, time_limit=10)
    planner.greedy = build_greedy(planner)
    solution = planner._solution_from_greedy("UNKNOWN", 0.2)
    assert solution.status == "UNKNOWN+GREEDY"


def test_greedy_fallback_respects_permitted_windows():
    instance = build_instance(
        {"S1": NIGHT_SPARSE}, [task("T1", "S1", 60)], horizon_days=3
    )
    planner = BlockPlanner(instance, time_limit=10)
    planner.greedy = build_greedy(planner)
    solution = planner._solution_from_greedy("UNKNOWN", 0.1)
    for block in solution.blocks:
        permitted = planner.permitted[block.section_id]
        assert all(permitted[s] for s in range(block.start_slot, block.end_slot))


def test_fallback_accounts_for_every_task():
    """Whatever the greedy could not place must appear as unscheduled, not
    vanish."""
    instance = build_instance(
        {"S1": NIGHT_SPARSE},
        [task(f"T{i}", "S1", 60) for i in range(4)],
        horizon_days=2,
    )
    planner = BlockPlanner(instance, time_limit=10)
    planner.greedy = build_greedy(planner)
    solution = planner._solution_from_greedy("UNKNOWN", 0.1)
    accounted = solution.scheduled_count + len(solution.unscheduled_task_ids)
    assert accounted == len(instance.tasks)
