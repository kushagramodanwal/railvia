"""Manual baseline vs coordinated planning. Produces the headline number.

    .venv/bin/python scripts/compare.py --grounded --tasks 300 --days 30
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.adapters import GroundedTimetableSource, SyntheticDataSource  # noqa: E402
from src.baseline.compare import run_comparison  # noqa: E402

RULE = "─" * 92


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--tasks", type=int, default=300)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--sections", type=int, default=5)
    ap.add_argument("--grounded", action="store_true")
    ap.add_argument("--time-limit", type=float, default=60.0)
    ap.add_argument("--percentile", type=float, default=25.0)
    ap.add_argument("--no-ml", action="store_true",
                    help="use flat criticality weights instead of the trained model")
    ap.add_argument("--repeat", type=int, default=1,
                    help="repeat the comparison N times and report the range; "
                         "parallel time-limited search is not bit-reproducible")
    args = ap.parse_args()

    source = (
        GroundedTimetableSource(seed=args.seed, n_tasks=args.tasks, horizon_days=args.days)
        if args.grounded
        else SyntheticDataSource(seed=args.seed, n_tasks=args.tasks,
                                 horizon_days=args.days, n_sections=args.sections)
    )
    instance = source.load()

    print(RULE)
    print(f"  {instance.instance_id}")
    print(f"  {source.describe()}")
    print(f"  provenance: {instance.sources.summary_line()}")
    print(f"  {len(instance.sections)} sections, {len(instance.tasks)} tasks, "
          f"{instance.horizon_days}-day horizon")
    print(RULE)
    criticality = None
    if not args.no_ml:
        from src.ml.criticality import CriticalityModel

        model = CriticalityModel()
        report = model.train(instance.sections)
        criticality = model.score_instance(instance)
        print(f"\nCRITICALITY MODEL ({model.backend})")
        for line in report.summary().splitlines():
            print(f"  {line}")

    print("\nsolving (baseline, full plan, like-for-like plan)...")

    runs = []
    for attempt in range(max(1, args.repeat)):
        comparison = run_comparison(
            instance, time_limit=args.time_limit, percentile=args.percentile,
            criticality=criticality,
        )
        runs.append(comparison)
        if args.repeat > 1:
            print(f"  run {attempt + 1}/{args.repeat}: "
                  f"{comparison.headline_reduction_pct:.1f}% "
                  f"({comparison.planned_like_for_like.train_hours_lost:.1f} vs "
                  f"{comparison.baseline.train_hours_lost:.1f} train-hours)")
    comparison = runs[0]

    header = ("Metric", "Manual", "Ours (same work)", "Ours (full backlog)")
    print(f"\n{RULE}")
    print(f"  {header[0]:34}{header[1]:>12}{header[2]:>20}{header[3]:>22}")
    print(RULE)
    for metric, manual, lfl, full in comparison.rows():
        print(f"  {metric:34}{manual:>12}{lfl:>20}{full:>22}")
    print(RULE)

    reduction = comparison.headline_reduction_pct
    blocks = comparison.block_reduction_pct
    print("\nHEADLINE (like for like — identical task set, crews and horizon)")
    print(f"  {reduction:.1f}% fewer train-hours lost across a "
          f"{instance.horizon_days}-day horizon")
    print(f"  on {len(instance.sections)} sections with 3 departments")
    print(f"  {blocks:.1f}% fewer separate blocks")
    if comparison.planned_like_for_like:
        print(f"  {comparison.planned_like_for_like.shared_blocks} blocks shared "
              f"across departments, against 0 today")
    if len(runs) > 1:
        values = sorted(r.headline_reduction_pct for r in runs)
        mean = sum(values) / len(values)
        print(f"\n  measured over {len(values)} runs: "
              f"{values[0]:.1f}% to {values[-1]:.1f}%, mean {mean:.1f}%")
        print("  (parallel time-limited search returns one of several good "
              "schedules;\n   the data is deterministic, the search is not)")

    print("\nSECOND RESULT (full backlog, same 30 days)")
    extra = comparison.planned_full.scheduled_count - comparison.baseline.scheduled_count
    print(f"  {extra} more tasks completed than the manual process manages")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
