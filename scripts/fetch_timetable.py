"""Build real section traffic profiles from the published timetable.

Two modes:

  Derive the corridor from a real train's route (recommended — consecutive
  stops are physically adjacent, so every pair is a genuine section):

    .venv/bin/python scripts/fetch_timetable.py --from-train 12002 --start NDLS --end GZB

  Or name the stations yourself, in running order:

    .venv/bin/python scripts/fetch_timetable.py --stations NDLS,DSA,SBB,GZB

Cost: 1 request for the route (if used) plus 1 per station. Everything is
cached to disk and never re-fetched, so re-runs are free and the job is
resumable if the budget runs out mid-way.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.ingest.railradar import RailRadarClient, RailRadarError  # noqa: E402
from src.ingest.timetable import (  # noqa: E402
    corridor_from_route,
    derive_section,
    parse_train_route,
)

BARS = " ▁▂▃▄▅▆▇█"


def sparkline(values: list[float]) -> str:
    top = max(values) or 1
    return "".join(BARS[min(8, int(v / top * 8))] for v in values)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from-train",
                    help="derive corridors from these train routes (comma-separated)")
    ap.add_argument("--start", help="trim corridor to start at this station code")
    ap.add_argument("--end", help="trim corridor to end at this station code")
    ap.add_argument("--stations", help="comma-separated station codes in running order")
    ap.add_argument("--budget", type=int, default=60, help="max requests this run")
    ap.add_argument("--offline", action="store_true", help="use cache only")
    ap.add_argument("-o", "--out", default="data/grounded_sections.json")
    args = ap.parse_args()

    if not args.from_train and not args.stations:
        ap.error("give either --from-train or --stations")

    client = RailRadarClient(run_budget=args.budget, offline=args.offline)

    corridors: list[list[str]] = []
    try:
        if args.from_train:
            for number in [n.strip() for n in args.from_train.split(",") if n.strip()]:
                route = parse_train_route(client.train_details(number, halts_only=False))
                codes = corridor_from_route(route, args.start, args.end)
                print(f"corridor from train {number}: {len(codes)} stations")
                print("  " + " -> ".join(codes))
                corridors.append(codes)
        else:
            corridors.append(
                [c.strip().upper() for c in args.stations.split(",") if c.strip()]
            )

        if any(len(c) < 2 for c in corridors):
            print("need at least 2 stations to form a section", file=sys.stderr)
            return 1

        # One board per station, however many corridors touch it.
        needed = list(dict.fromkeys(code for c in corridors for code in c))
        print(f"\n{len(needed)} distinct stations to fetch")
        boards = {}
        names: dict[str, str] = {}
        coords: dict[str, tuple[float, float]] = {}
        for code in needed:
            payload = client.station_board(code, include_intermediate=True)
            boards[code] = payload
            body = payload.get("data") if isinstance(payload, dict) else None
            station = body.get("station") if isinstance(body, dict) else None
            if isinstance(station, dict):
                if station.get("name"):
                    names[code] = str(station["name"])
                lat, lng = station.get("lat"), station.get("lng")
                if lat is not None and lng is not None:
                    # Real positions, so a map shows the corridor as it runs
                    # on the ground rather than as an invented schematic.
                    coords[code] = (float(lat), float(lng))
    except RailRadarError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        if "API key" in str(exc):
            print("Get a free sandbox key at https://railradar.in/developers", file=sys.stderr)
        return 1

    sections = []
    empty = []
    seen: set[str] = set()
    for codes in corridors:
        for a, b in zip(codes, codes[1:]):
            # Corridors overlap around Delhi; a shared section is one section.
            key = "-".join(sorted((a, b)))
            if key in seen:
                continue
            seen.add(key)
            section = derive_section(a, b, boards[a], boards[b])
            if section.daily_trains == 0:
                empty.append(section.section_id)
                continue
            sections.append(section)

    print(f"\n{'section':14} {'trains/day':>10} {'peak/h':>7} {'quiet':>6} {'km':>7}  profile")
    print("-" * 92)
    for s in sections:
        print(
            f"{s.section_id:14} {s.daily_trains:>10.0f} {s.peak_trains_per_hour:>7.1f} "
            f"{s.quietest_hour:>5}h {str(s.length_km if s.length_km is not None else '?'):>7}  "
            f"|{sparkline(s.profile)}|"
        )

    if empty:
        print(
            f"\nDROPPED {len(empty)} pair(s) with no traversals: "
            f"{', '.join(empty[:8])}{'...' if len(empty) > 8 else ''}\n"
            "  Those station pairs are probably not physically adjacent, so no train\n"
            "  shows them with consecutive stop sequences. Use --from-train to derive\n"
            "  an adjacency-correct corridor instead of naming stations by hand."
        )

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {
            "source": "RailRadar API (aggregates public Indian Railways NTES timetable)",
            "source_url": "https://railradar.in/docs",
            "corridors": corridors,
            "stations": {
                code: {
                    "name": names.get(code, code),
                    "lat": coords.get(code, (None, None))[0],
                    "lng": coords.get(code, (None, None))[1],
                }
                for code in needed
            },
            "derived_from_train": args.from_train,
            "sections": [
                {
                    "id": s.section_id,
                    "station_a": s.station_a,
                    "station_b": s.station_b,
                    "name": (
                        f"{names.get(s.station_a, s.station_a)} - "
                        f"{names.get(s.station_b, s.station_b)}"
                    ),
                    "length_km": s.length_km,
                    "traffic_density_profile": s.profile,
                    # Real 7x24 grid from each train's runDays: weekday and
                    # weekend traffic measured separately, not scaled.
                    "profile_by_dow": s.profile_by_dow,
                    "daily_trains": s.daily_trains,
                    "distinct_trains": s.distinct_trains,
                    # The named trains crossing this section, with the minute
                    # past midnight each enters. This is what makes a closure
                    # concrete: not "26 train-hours" but the Shram Shakti
                    # Express and thirty-nine others.
                    "trains": sorted(
                        (
                            {
                                "number": t.train_number,
                                "name": t.train_name,
                                "entry": t.entry_min,
                                "exit": t.exit_min,
                                "days": sorted(t.run_days),
                                "type": t.train_type,
                            }
                            for t in s.traversals
                        ),
                        key=lambda t: t["entry"],
                    ),
                    "train_types": sorted({t.train_type for t in s.traversals if t.train_type}),
                }
                for s in sections
            ],
        },
        indent=2,
    ))
    print(f"\nwrote {out} ({len(sections)} sections)")
    print(f"requests spent this month: {client.budget.spent_this_month}/"
          f"{client.budget.monthly_budget}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
