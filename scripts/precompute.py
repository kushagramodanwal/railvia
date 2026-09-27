"""Solve plans at image-build time, so the server never has to.

Why this exists
---------------
A month-long instance needs 700 MB to 1.9 GB of memory to solve — measured on
39 sections with 120 tasks. A small cloud instance has 512 MB, so a container
that tries is killed mid-request.

None of that is necessary. A plan is deterministic given its inputs, so it can
be solved once on a machine with room and shipped inside the image. The server
then answers from its cache in milliseconds, on any amount of memory.

    python scripts/precompute.py --months 4

The budget MUST match the API's own default, because the cache is keyed on it
— solving here at 30s while the server asks for 10s writes entries nobody ever
looks up. It therefore defaults to the API's value rather than a number of its
own.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import time
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


def months_from(first: date, count: int) -> list[date]:
    out, year, month = [], first.year, first.month
    for _ in range(count):
        out.append(date(year, month, 1))
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return out


def days_in(first: date) -> int:
    nxt = date(first.year + (first.month == 12), (first.month % 12) + 1, 1)
    return (nxt - first).days


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--months", type=int, default=12,
                    help="how many consecutive months to solve. The UI's "
                         "month picker offers 12 — two back and nine ahead — "
                         "and any month not solved here falls back to the "
                         "constructive schedule on a host with runtime "
                         "solving disabled")
    ap.add_argument("--from", dest="first", default=None, metavar="YYYY-MM",
                    help="first month to solve (default: two months back, "
                         "matching the earliest the picker offers)")
    ap.add_argument("--tasks", type=int, default=120)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--time-limit", type=float, default=None,
                    help="budget per solve; defaults to the API's own, which "
                         "is what the cache is keyed on")
    args = ap.parse_args()

    # Imported here so --help works without loading the solver.
    from src.api.app import DEFAULT_UI_BUDGET, plan

    budget = args.time_limit if args.time_limit is not None else DEFAULT_UI_BUDGET
    today = date.today()
    if args.first:
        year, month = (int(part) for part in args.first.split("-"))
        start = date(year, month, 1)
    else:
        # Two back, because that is the earliest the picker offers and an
        # unsolved month there is just as visible as an unsolved month ahead.
        month0 = today.month - 2
        year0 = today.year + (month0 - 1) // 12
        start = date(year0, (month0 - 1) % 12 + 1, 1)
    started = time.time()

    print(f"precomputing {args.months} month(s) from {start:%B %Y}, "
          f"{budget:.0f}s each, {args.tasks} tasks")

    for first in months_from(start, args.months):
        began = time.time()
        result = plan(
            grounded=True, tasks=args.tasks, days=days_in(first),
            seed=args.seed, time_limit=budget,
            horizon_start=first.isoformat(),
        )
        print(f"  {first:%B %Y}: {result['block_count']:4d} closures, "
              f"{result['scheduled']:3d}/{result['task_total']} jobs, "
              f"{result['status']:16} {time.time() - began:5.1f}s")

    cached = list(pathlib.Path("data/cache/plans").glob("*.json"))
    size = sum(f.stat().st_size for f in cached) / 1e6
    print(f"cached {len(cached)} plan(s), {size:.1f} MB, "
          f"in {time.time() - started:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
