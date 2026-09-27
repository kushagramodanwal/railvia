"""Spend ONE request to learn the true shape of a RailRadar response.

The parsers in src/ingest/timetable.py were written against documentation,
not a live response. Run this first with a real key, read the shape it
prints, and correct the field-name lists if they differ.

    RAILRADAR_API_KEY=rr_live_... .venv/bin/python scripts/probe_api.py --station NDLS
    RAILRADAR_API_KEY=rr_live_... .venv/bin/python scripts/probe_api.py --train 12002
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.ingest.railradar import RailRadarClient, RailRadarError  # noqa: E402

MAX_ITEMS_SHOWN = 2


def describe(value, indent: int = 0, depth: int = 0, max_depth: int = 5) -> None:
    pad = "  " * indent
    if depth > max_depth:
        print(f"{pad}...")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            kind = type(item).__name__
            if isinstance(item, (dict, list)):
                size = f"[{len(item)}]" if isinstance(item, list) else ""
                print(f"{pad}{key}: {kind}{size}")
                describe(item, indent + 1, depth + 1, max_depth)
            else:
                shown = json.dumps(item)[:70]
                print(f"{pad}{key}: {kind} = {shown}")
    elif isinstance(value, list):
        for item in value[:MAX_ITEMS_SHOWN]:
            describe(item, indent, depth + 1, max_depth)
            if len(value) > 1:
                print(f"{pad}---")
        if len(value) > MAX_ITEMS_SHOWN:
            print(f"{pad}... {len(value) - MAX_ITEMS_SHOWN} more entries")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--station", help="station code, e.g. NDLS")
    group.add_argument("--train", help="train number, e.g. 12002")
    ap.add_argument("--raw", action="store_true", help="print the full JSON instead")
    args = ap.parse_args()

    client = RailRadarClient(run_budget=2)
    try:
        if args.station:
            payload = client.station_board(args.station)
            label = f"station board: {args.station.upper()}"
        else:
            payload = client.train_details(args.train, halts_only=False)
            label = f"train details: {args.train}"
    except RailRadarError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1

    print(f"=== {label} ===")
    print(f"(requests spent this month: {client.budget.spent_this_month}/"
          f"{client.budget.monthly_budget})\n")
    if args.raw:
        print(json.dumps(payload, indent=2)[:20000])
    else:
        describe(payload)

    print("\n--- parser check ---")
    try:
        if args.station:
            from src.ingest.timetable import parse_station_board

            stops = parse_station_board(payload)
            print(f"OK: parsed {len(stops)} stops")
            for stop in stops[:5]:
                print(f"  {stop.train_number:8} seq={stop.sequence:<4} "
                      f"arr={stop.arrival_min} dep={stop.departure_min} "
                      f"km={stop.distance_km} halt={stop.is_halt}")
        else:
            from src.ingest.timetable import parse_train_route

            route = parse_train_route(payload)
            print(f"OK: parsed {len(route)} route stops")
            for stop in route[:5]:
                print(f"  {stop.sequence:<4} {stop.station_code:8} "
                      f"arr={stop.arrival_min} dep={stop.departure_min} km={stop.distance_km}")
    except Exception as exc:
        print(f"PARSER MISMATCH: {exc}")
        print("Correct the field-name lists in src/ingest/timetable.py using the shape above.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
