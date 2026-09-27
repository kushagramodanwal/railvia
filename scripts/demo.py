"""End-to-end demo run, recorded to a transcript.

Runs every stage in order and writes the output to a file, so there is a
stage backup if the live demo will not cooperate:

    .venv/bin/python scripts/demo.py --out demo_run.txt

Everything is deterministic given the seed, so the transcript and a live run
produce the same numbers.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.adapters import GroundedTimetableSource  # noqa: E402
from src.baseline.compare import run_comparison  # noqa: E402
from src.ml.criticality import CriticalityModel  # noqa: E402
from src.optimiser.replan import Disruption, replan_after  # noqa: E402

RULE = "═" * 78


def banner(title: str) -> None:
    print(f"\n{RULE}\n  {title}\n{RULE}")


def run(seed: int, tasks: int, days: int, time_limit: float) -> None:
    started = time.time()

    banner("1. DATA — real timetable, synthetic maintenance backlog")
    source = GroundedTimetableSource(seed=seed, n_tasks=tasks, horizon_days=days)
    instance = source.load()
    print(f"  {source.describe()}")
    print(f"  {len(instance.sections)} sections · {len(instance.tasks)} tasks · "
          f"{instance.horizon_days}-day horizon")
    print("\n  provenance by component:")
    for name, kind in instance.sources.components.items():
        mark = "generated" if kind.value == "synthetic" else "REAL"
        print(f"    {name:15} {kind.value:18} {mark}")
    print(f"\n  {instance.provenance}")
    busiest = max(instance.sections, key=lambda s: s.daily_trains)
    print(f"\n  busiest section: {busiest.id} ({busiest.name})")
    print(f"    {busiest.daily_trains:.0f} trains/day, peak "
          f"{busiest.peak_trains_per_hour:.1f}/h, floor "
          f"{min(busiest.traffic_density_profile):.1f}/h")
    print("    a flat 'no blocks above 8 trains/hour' rule would leave this")
    print("    section unusable — hence the per-section threshold (A-14)")

    banner("2. CRITICALITY MODEL")
    model = CriticalityModel()
    report = model.train(instance.sections)
    for line in report.summary().splitlines():
        print(f"  {line}")
    scores = model.score_instance(instance)
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    by_id = {t.id: t for t in instance.tasks}
    print("\n  highest-criticality work:")
    for task_id, score in ranked[:5]:
        task = by_id[task_id]
        flag = " OVERDUE" if task.is_overdue else ""
        print(f"    {task_id:6} {score:.3f}  {task.department.value:5} "
              f"{task.activity_type:30}{flag}")
    print("\n  why the top task scored as it did:")
    for feature, value in model.explain(instance, ranked[0][0])[:5]:
        print(f"    {feature:28} {value:+.4f}")

    banner("3. BEFORE / AFTER")
    comparison = run_comparison(instance, time_limit=time_limit, criticality=scores)
    header = ("Metric", "Manual", "Ours (same work)", "Ours (full)")
    print(f"  {header[0]:34}{header[1]:>10}{header[2]:>20}{header[3]:>16}")
    print("  " + "─" * 78)
    for metric, manual, lfl, full in comparison.rows():
        print(f"  {metric:34}{manual:>10}{lfl:>20}{full:>16}")

    print(f"\n  HEADLINE: {comparison.headline_reduction_pct:.1f}% fewer train-hours "
          f"lost across a {instance.horizon_days}-day horizon")
    print(f"            on {len(instance.sections)} sections with 3 departments, "
          f"for identical work")
    print(f"            {comparison.block_reduction_pct:.1f}% fewer separate blocks")
    print(f"  SECOND  : {comparison.planned_full.scheduled_count - comparison.baseline.scheduled_count}"
          f" more tasks completed than the manual process manages")

    banner("4. SCENARIO RE-PLANNING")
    plan = comparison.planned_full
    section = max(instance.sections, key=lambda s: s.daily_trains)
    disruption = Disruption(
        at_slot=96 * (days // 3), section_id=section.id, overrun_slots=16,
        description="tamping machine failure, 4-hour overrun",
    )
    result = replan_after(
        instance, plan, disruption, time_limit=time_limit, criticality=scores
    )
    for line in result.summary().splitlines():
        print(f"  {line}")

    banner("5. WHAT IS AND IS NOT REAL")
    print("  REAL      section geometry, hourly traffic, day-of-week variation")
    print("            (published Indian Railways timetable via RailRadar)")
    print("  SYNTHETIC maintenance backlog, crew strength, failure history")
    print("            (TMS/SMMS/TDMS have no public equivalent)")
    print("  NOT DONE  freight paths are absent from public timetables, so")
    print("            night traffic is undercounted — the one place our")
    print("            figures could flatter us (A-04)")
    print("  CAVEAT    the failure hazard the model learns is one we wrote (A-08)")
    print(f"\n  total demo wall time: {time.time() - started:.1f}s")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--tasks", type=int, default=300)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--time-limit", type=float, default=30.0)
    ap.add_argument("--out", default=None, help="also write the transcript here")
    args = ap.parse_args()

    if args.out:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            run(args.seed, args.tasks, args.days, args.time_limit)
        text = buffer.getvalue()
        print(text)
        pathlib.Path(args.out).write_text(text)
        print(f"\ntranscript written to {args.out}")
    else:
        run(args.seed, args.tasks, args.days, args.time_limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
