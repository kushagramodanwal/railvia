"""Human-readable dump of a planning instance. This is the Phase 0 gate.

    python scripts/inspect_data.py [--seed 42] [--from-file data/instance.json]

Read the output and decide whether the data is structurally sane before any
optimiser work begins.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from collections import Counter
from datetime import timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.adapters import (  # noqa: E402
    GroundedTimetableSource,
    JSONFileDataSource,
    SyntheticDataSource,
)
from src.models import Department, PlanningInstance  # noqa: E402

BARS = " ▁▂▃▄▅▆▇█"
RULE = "─" * 78


def sparkline(values: list[float], vmax: float | None = None) -> str:
    top = vmax if vmax is not None else (max(values) or 1)
    return "".join(BARS[min(len(BARS) - 1, int(v / top * (len(BARS) - 1)))] for v in values)


def header(title: str) -> None:
    print(f"\n{title}\n{RULE}")


def show_sections(inst: PlanningInstance) -> None:
    header("SECTIONS — 24h traffic profile (00h ....... 23h)")
    vmax = max(s.peak_trains_per_hour for s in inst.sections)
    for s in inst.sections:
        print(
            f"  {s.id:10} {s.name:24} {s.length_km:5.1f} km  "
            f"peak {s.peak_trains_per_hour:5.1f}/h  {s.daily_trains:6.1f} trains/day"
        )
        print(f"  {'':10} |{sparkline(s.traffic_density_profile, vmax)}|")


def show_tasks(inst: PlanningInstance) -> None:
    header(f"TASKS ({len(inst.tasks)})")
    print(
        f"  {'id':5} {'dept':5} {'section':10} {'activity':30} "
        f"{'dur':>6} {'crew':>4} {'sev':>3} {'due':>11} {'status':>9}"
    )
    for t in sorted(inst.tasks, key=lambda t: (t.due_date, t.id)):
        d = t.days_to_due(inst.horizon_start)
        if t.is_overdue:
            status = f"OVERDUE{-d:+d}"
        elif d <= inst.horizon_days:
            status = f"due D+{d}"
        else:
            status = "ahead"
        print(
            f"  {t.id:5} {t.department.value:5} {t.section_id:10} {t.activity_type:30} "
            f"{t.duration_minutes:4d}m {t.crew_required:4d} {t.defect_severity.value:3d} "
            f"{t.due_date.isoformat():>11} {status:>9}"
        )


def show_mix(inst: PlanningInstance) -> None:
    header("BACKLOG MIX")
    n = len(inst.tasks)
    by_dept = Counter(t.department.value for t in inst.tasks)
    by_section = Counter(t.section_id for t in inst.tasks)
    overdue = sum(t.is_overdue for t in inst.tasks)
    in_horizon = sum(
        1 for t in inst.tasks
        if not t.is_overdue and t.days_to_due(inst.horizon_start) <= inst.horizon_days
    )
    print("  by department : " + "  ".join(f"{k} {v}" for k, v in sorted(by_dept.items())))
    print("  by section    : " + "  ".join(f"{k} {v}" for k, v in sorted(by_section.items())))
    print(f"  overdue       : {overdue}/{n} ({overdue / n:.0%})")
    print(f"  due in horizon: {in_horizon}/{n} ({in_horizon / n:.0%})")
    print(f"  not co-locatable: {sum(not t.co_locatable for t in inst.tasks)}/{n}")
    total_h = sum(t.duration_hours for t in inst.tasks)
    print(f"  total work    : {total_h:.1f} crew-block-hours across {inst.horizon_days} days")


def show_colocation_potential(inst: PlanningInstance) -> None:
    header("CO-LOCATION POTENTIAL (the coordination win to be demonstrated)")
    found = False
    for s in inst.sections:
        depts = {t.department for t in inst.tasks_for(s.id) if t.co_locatable}
        if len(depts) > 1:
            found = True
            names = ", ".join(sorted(d.value for d in depts))
            print(f"  {s.id:10} {len(depts)} departments could share a block: {names}")
    if not found:
        print("  none — no section has co-locatable work from >1 department")


def show_traffic_checks(inst: PlanningInstance) -> None:
    header("TRAFFIC WINDOWS — sanity checks")
    expected = len(inst.sections) * inst.horizon_days * 24
    print(f"  rows            : {len(inst.traffic)} (expected {expected}) "
          f"{'OK' if len(inst.traffic) == expected else 'MISMATCH'}")
    quiet = [w for w in inst.traffic if w.trains_per_hour <= 2]
    busy = [w for w in inst.traffic if w.trains_per_hour > 8]
    print(f"  quiet (<=2/h)   : {len(quiet)} windows ({len(quiet) / len(inst.traffic):.0%})")
    print(f"  peak  (> 8/h)   : {len(busy)} windows ({len(busy) / len(inst.traffic):.0%}) "
          f"— blocked by the Phase 1 forbidden-window constraint")
    cheapest = min(inst.traffic, key=lambda w: w.trains_per_hour)
    dearest = max(inst.traffic, key=lambda w: w.trains_per_hour)
    print(f"  cheapest hour   : {cheapest.section_id} {cheapest.day} "
          f"{cheapest.hour_of_day:02d}:00 @ {cheapest.trains_per_hour}/h")
    print(f"  dearest hour    : {dearest.section_id} {dearest.day} "
          f"{dearest.hour_of_day:02d}:00 @ {dearest.trains_per_hour}/h")
    print(f"  goods-flagged   : {sum(w.is_goods_forecast for w in inst.traffic)} windows")


def show_crew(inst: PlanningInstance) -> None:
    header("CREW CAPACITY")
    days = sorted({c.date for c in inst.crew_capacity})
    print(f"  {'dept':6} " + " ".join(d.strftime('%a') for d in days))
    for dept in Department:
        row = {c.date: c.available_crews for c in inst.crew_capacity if c.department == dept}
        print(f"  {dept.value:6} " + " ".join(f"{row[d]:3d}" for d in days))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--tasks", type=int, default=20)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--sections", type=int, default=5)
    ap.add_argument("--from-file", default=None)
    ap.add_argument("--grounded", action="store_true",
                    help="use real timetable-derived sections (data/grounded_sections.json)")
    args = ap.parse_args()

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
    inst = source.load()

    print(RULE)
    print(f"  {inst.instance_id}")
    print(f"  {source.describe()}")
    print(f"  horizon: {inst.horizon_start} .. {inst.horizon_end - timedelta(days=1)} "
          f"({inst.horizon_days} days)")
    print(RULE)
    print("\n  PROVENANCE BY COMPONENT")
    for name, kind in inst.sources.components.items():
        mark = "generated" if kind.value == "synthetic" else "REAL"
        print(f"    {name:15} {kind.value:18} {mark}")
    print(f"\n  !! {inst.provenance}")

    show_sections(inst)
    show_tasks(inst)
    show_mix(inst)
    show_colocation_potential(inst)
    show_traffic_checks(inst)
    show_crew(inst)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
