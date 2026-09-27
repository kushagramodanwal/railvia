"""Solve the block plan and print it as a text table.

    .venv/bin/python scripts/optimise.py --grounded
    .venv/bin/python scripts/optimise.py --seed 42 --tasks 20

No UI until Phase 4 — an ugly table showing a good schedule beats a pretty
Gantt showing a bad one.
"""

from __future__ import annotations

import argparse
import logging
import pathlib
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.adapters import (  # noqa: E402
    GroundedTimetableSource,
    JSONFileDataSource,
    SyntheticDataSource,
)
from src.optimiser.model import BlockPlanner  # noqa: E402
from src.optimiser.windows import permitted_runs  # noqa: E402

RULE = "─" * 100


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--tasks", type=int, default=20)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--sections", type=int, default=5)
    ap.add_argument("--grounded", action="store_true",
                    help="use real timetable-derived sections")
    ap.add_argument("--from-file", default=None)
    ap.add_argument("--percentile", type=float, default=25.0,
                    help="blocks permitted in each section's quietest N%% of hours")
    ap.add_argument("--time-limit", type=float, default=60.0)
    ap.add_argument("--verbose", action="store_true", help="log solver progress")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="  %(message)s")

    if args.from_file:
        source = JSONFileDataSource(args.from_file)
    elif args.grounded:
        source = GroundedTimetableSource(
            seed=args.seed, n_tasks=args.tasks, horizon_days=args.days
        )
    else:
        source = SyntheticDataSource(
            seed=args.seed, n_tasks=args.tasks,
            horizon_days=args.days, n_sections=args.sections,
        )
    instance = source.load()

    print(RULE)
    print(f"  {instance.instance_id}")
    print(f"  {source.describe()}")
    print(f"  provenance: {instance.sources.summary_line()}")
    print(RULE)

    planner = BlockPlanner(
        instance, percentile=args.percentile, time_limit=args.time_limit
    )

    print("\nPERMITTED WINDOWS (each section's quietest "
          f"{args.percentile:.0f}% of hours)")
    print(f"  {'section':12} {'threshold':>10} {'slots':>12} {'longest run':>12}")
    for section in instance.sections:
        permitted = planner.permitted[section.id]
        runs = permitted_runs(permitted)
        longest = max((e - b for b, e in runs), default=0)
        threshold = max(
            (v for v, ok in zip(planner.traffic[section.id], permitted) if ok),
            default=0.0,
        )
        print(f"  {section.id:12} {threshold:>8.1f}/h {sum(permitted):>6}/{len(permitted):<5} "
              f"{longest * planner.grid.slot_minutes / 60:>10.1f}h")

    solution = planner.solve(log_search=args.verbose)

    print(f"\nSOLVER: {solution.status}  objective={solution.objective:,.0f}  "
          f"bound={solution.best_bound:,.0f}  wall={solution.wall_time:.2f}s")
    if not solution.feasible:
        print("\nNo feasible schedule found.")
        if solution.impossible_task_ids:
            print("  tasks with no window long enough: "
                  f"{', '.join(solution.impossible_task_ids)}")
        return 1

    tasks_by_id = {t.id: t for t in instance.tasks}
    print(f"\nBLOCK PLAN ({len(solution.blocks)} blocks)")
    print(RULE)
    print(f"  {'section':12} {'start':>17} {'end':>10} {'hrs':>5} {'train-h':>8}  "
          f"{'depts':10} tasks")
    for block in solution.blocks:
        start = planner.grid.to_datetime(block.start_slot)
        end = planner.grid.to_datetime(block.end_slot)
        depts = "+".join(d.value for d in block.departments)
        mark = " <- SHARED" if block.is_shared else ""
        hours = (block.end_slot - block.start_slot) * planner.grid.slot_minutes / 60
        # Blocks legitimately run past midnight; show the day when it changes,
        # or the end reads as earlier than the start.
        end_text = (
            end.strftime("%H:%M") if end.date() == start.date()
            else end.strftime("+%a %H:%M")
        )
        print(f"  {block.section_id:12} {start.strftime('%a %d %H:%M'):>17} "
              f"{end_text:>10} {hours:>5.2f} {block.train_hours:>8.2f}  "
              f"{depts:10} {', '.join(block.task_ids)}{mark}")

    print(f"\n{RULE}\nRESULT")
    print(f"  train-hours lost      : {solution.train_hours_lost:.2f}")
    print(f"  blocks                : {len(solution.blocks)}")
    print(f"  tasks scheduled       : {solution.scheduled_count}/{len(instance.tasks)}")
    merged = solution.scheduled_count - len(solution.blocks)
    print(f"  tasks sharing a block : {merged}")
    print(f"  cross-department blocks: {solution.shared_blocks}")
    by_dept = Counter(
        tasks_by_id[t].department.value for b in solution.blocks for t in b.task_ids
    )
    print("  by department         : " + "  ".join(f"{k} {v}" for k, v in sorted(by_dept.items())))
    if solution.late_days:
        print(f"  tasks finishing late  : {solution.late_task_count} "
              f"({solution.total_days_late} task-days)")
    if solution.unscheduled_task_ids:
        ids = solution.unscheduled_task_ids
        shown = ", ".join(ids[:12]) + ("..." if len(ids) > 12 else "")
        print(f"  UNSCHEDULED           : {len(ids)} ({shown})")
    if solution.impossible_task_ids:
        print(f"  no window long enough : {', '.join(solution.impossible_task_ids)}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
