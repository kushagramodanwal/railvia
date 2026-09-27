"""Derive per-section hourly traffic from RailRadar station boards.

The idea
--------
A "section" is the track between two adjacent stations, A and B. RailRadar
gives us, per station, every scheduled train calling there — including
pass-through trains when `includeIntermediate=true` — with each train's stop
`sequence` and `distance` from its origin.

A train traverses section A-B if it appears on both boards with **adjacent
stop sequences**. Direction follows from which sequence is lower. The train
occupies the section from its departure at the entry station to its arrival
at the exit station, and we credit it to every clock hour that interval
touches.

Aggregating over all trains gives a 24-bin histogram: real trains per hour,
per section. That is `Section.traffic_density_profile` — measured from a
published timetable rather than drawn by hand.

The same data yields `length_km` as the difference of the two `distance`
values, which grounds section geometry as well.

Response-shape caution
----------------------
These parsers were written against the RailRadar documentation, not against
a live response. They accept several plausible field spellings and, when
nothing matches, raise an error naming the keys actually present rather than
silently producing zeros. Silent zeros would be the worst failure mode here:
a section with no traffic looks free to block, and the optimiser would
happily schedule work through rush hour.

Run `scripts/probe_api.py` once with a real key to confirm the true shape.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable

HOURS = 24
DAYS = 7
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})")

# RailRadar reports weekdays as three-letter lowercase names. 0 = Monday, to
# match datetime.date.weekday().
DOW_NAMES: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DOW_INDEX: dict[str, int] = {name: i for i, name in enumerate(DOW_NAMES)}
ALL_DAYS: frozenset[int] = frozenset(range(DAYS))

# stopType values seen in live responses. Everything except "pass-through"
# means the train is scheduled to stand at the station; all of them mean it
# is present on the section either side.
HALT_STOP_TYPES: frozenset[str] = frozenset({"halt", "origin", "destination"})


def parse_run_days(value: Any) -> frozenset[int]:
    """['mon','tue',...] -> {0,1,...}. Unknown or absent means runs daily.

    Defaulting to daily is the conservative choice: it never removes traffic
    that might be there, so a parsing gap cannot make a section look quieter
    than it is.
    """
    if not isinstance(value, (list, tuple, set, frozenset)):
        return ALL_DAYS
    days = {DOW_INDEX[str(d).strip().lower()[:3]]
            for d in value if str(d).strip().lower()[:3] in DOW_INDEX}
    return frozenset(days) if days else ALL_DAYS


class ShapeError(ValueError):
    """The API response did not look like anything we know how to read."""


# --- generic helpers -------------------------------------------------------


def _first(mapping: dict, *names: str) -> Any:
    """Return the first present, non-null key among `names`."""
    for name in names:
        if isinstance(mapping, dict) and mapping.get(name) is not None:
            return mapping[name]
    return None


def parse_time_to_minutes(value: Any) -> int | None:
    """'23:55' -> 1435. Returns None for null/unparseable values.

    Originating trains have no arrival and terminating trains no departure,
    so None is expected and must not be treated as midnight.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value) % (24 * 60)
    match = _TIME_RE.match(str(value).strip())
    if not match:
        return None
    hours, minutes = int(match.group(1)), int(match.group(2))
    if hours > 23 or minutes > 59:
        return None
    return hours * 60 + minutes


def unwrap(payload: Any) -> Any:
    """Strip the {"success": ..., "data": ...} envelope if present."""
    if isinstance(payload, dict):
        if "data" in payload and isinstance(payload.get("data"), (list, dict)):
            return payload["data"]
    return payload


# --- station board ---------------------------------------------------------


@dataclass(frozen=True)
class StationStop:
    """One train's scheduled call at one station."""

    train_number: str
    train_name: str
    sequence: int
    arrival_min: int | None
    departure_min: int | None
    distance_km: float | None
    is_halt: bool
    run_days: frozenset[int] = ALL_DAYS
    train_type: str = ""

    @property
    def entry_time(self) -> int | None:
        """When the train leaves this station. Falls back to arrival."""
        return self.departure_min if self.departure_min is not None else self.arrival_min

    @property
    def exit_time(self) -> int | None:
        """When the train reaches this station. Falls back to departure."""
        return self.arrival_min if self.arrival_min is not None else self.departure_min


def _extract_entries(payload: Any) -> list[dict]:
    body = unwrap(payload)
    if isinstance(body, list):
        return [e for e in body if isinstance(e, dict)]
    if isinstance(body, dict):
        for key in ("trains", "stops", "board", "results", "items", "schedule"):
            value = body.get(key)
            if isinstance(value, list):
                return [e for e in value if isinstance(e, dict)]
    raise ShapeError(
        "could not locate the train list in the station board response. "
        f"Top-level keys: {sorted(body.keys()) if isinstance(body, dict) else type(body).__name__}"
    )


def parse_station_board(payload: Any) -> list[StationStop]:
    """Parse a /stations/{code}/trains response into StationStop records."""
    stops: list[StationStop] = []
    unreadable = 0
    seen_keys: Counter[str] = Counter()

    for entry in _extract_entries(payload):
        seen_keys.update(entry.keys())
        # Documented shape nests the train and its stop; flat shapes also occur.
        train = entry.get("train") if isinstance(entry.get("train"), dict) else entry
        stop = entry.get("stop") if isinstance(entry.get("stop"), dict) else entry

        number = _first(train, "number", "trainNumber", "train_number", "trainNo")
        if number is None:
            unreadable += 1
            continue
        sequence = _first(stop, "sequence", "stopNumber", "seq", "sequenceNumber")
        if sequence is None:
            unreadable += 1
            continue

        stops.append(
            StationStop(
                train_number=str(number).strip(),
                train_name=str(_first(train, "name", "trainName") or "").strip(),
                sequence=int(sequence),
                arrival_min=parse_time_to_minutes(
                    _first(stop, "arrival", "arrivalTime", "sta", "scheduledArrival")
                ),
                departure_min=parse_time_to_minutes(
                    _first(stop, "departure", "departureTime", "std", "scheduledDeparture")
                ),
                distance_km=(
                    float(d)
                    if (d := _first(stop, "distance", "distanceFromOrigin", "km")) is not None
                    else None
                ),
                # Live responses use stopType (origin/halt/destination/
                # pass-through) rather than a boolean.
                is_halt=(
                    str(stop_type).strip().lower() in HALT_STOP_TYPES
                    if (stop_type := _first(stop, "stopType", "stop_type")) is not None
                    else bool(_first(stop, "isHalt", "halt", "isStopping") or False)
                ),
                run_days=parse_run_days(_first(train, "runDays", "run_days", "days")),
                train_type=str(_first(train, "type", "trainType") or "").strip(),
            )
        )

    if not stops:
        raise ShapeError(
            "station board parsed to zero usable stops. Keys seen on entries: "
            f"{sorted(seen_keys)}. Update the field-name lists in parse_station_board."
        )
    if unreadable > len(stops):
        raise ShapeError(
            f"{unreadable} entries unreadable vs {len(stops)} readable — the "
            f"response shape has probably changed. Keys seen: {sorted(seen_keys)}"
        )
    return stops


# --- section traversal -----------------------------------------------------


@dataclass(frozen=True)
class Traversal:
    """One train crossing one section, in one direction."""

    train_number: str
    train_name: str
    forward: bool  # True if travelling A -> B
    entry_min: int
    exit_min: int | None
    run_days: frozenset[int] = ALL_DAYS
    train_type: str = ""

    def runs_on(self, day_of_week: int) -> bool:
        return day_of_week in self.run_days

    @property
    def entry_hour(self) -> int:
        return (self.entry_min // 60) % HOURS

    def occupied_hours(self, max_span_hours: int = 6) -> list[int]:
        """Every clock hour this traversal touches, handling midnight wrap.

        `max_span_hours` guards against bad data (a missing arrival, or a
        mis-paired train) inflating one traversal into a whole day of traffic.
        """
        start_hour = self.entry_hour
        if self.exit_min is None:
            return [start_hour]
        span = (self.exit_min - self.entry_min) % (24 * 60)
        end_hour = ((self.entry_min + span) // 60) % HOURS
        hours = [start_hour]
        cursor = start_hour
        guard = 0
        while cursor != end_hour and guard < max_span_hours:
            cursor = (cursor + 1) % HOURS
            hours.append(cursor)
            guard += 1
        return hours


def find_traversals(
    board_a: Iterable[StationStop], board_b: Iterable[StationStop]
) -> list[Traversal]:
    """Trains appearing on both boards with adjacent stop sequences.

    Adjacency (|seq_a - seq_b| == 1) is what proves the two stations are
    consecutive on that train's route, i.e. that the train really runs over
    this section rather than reaching the other station by some other path.
    """
    by_number_b: dict[str, list[StationStop]] = {}
    for stop in board_b:
        by_number_b.setdefault(stop.train_number, []).append(stop)

    traversals: list[Traversal] = []
    for stop_a in board_a:
        for stop_b in by_number_b.get(stop_a.train_number, []):
            if abs(stop_a.sequence - stop_b.sequence) != 1:
                continue
            forward = stop_a.sequence < stop_b.sequence
            entry_stop, exit_stop = (stop_a, stop_b) if forward else (stop_b, stop_a)
            entry = entry_stop.entry_time
            if entry is None:
                continue
            traversals.append(
                Traversal(
                    train_number=stop_a.train_number,
                    train_name=stop_a.train_name,
                    forward=forward,
                    entry_min=entry,
                    exit_min=exit_stop.exit_time,
                    run_days=stop_a.run_days & stop_b.run_days or stop_a.run_days,
                    train_type=stop_a.train_type,
                )
            )
    return traversals


def hourly_profile(
    traversals: Iterable[Traversal], day_of_week: int | None = None
) -> list[float]:
    """24-bin histogram of trains occupying the section, by hour of day.

    With `day_of_week` set, counts only trains that actually run that day.
    """
    profile = [0.0] * HOURS
    for traversal in traversals:
        if day_of_week is not None and not traversal.runs_on(day_of_week):
            continue
        for hour in traversal.occupied_hours():
            profile[hour] += 1.0
    return profile


def mean_profile(grid: list[list[float]]) -> list[float]:
    """Average across the week: the traffic an arbitrary day actually sees.

    The unfiltered histogram counts every train that traverses the section on
    *any* day, which overstates any single day — on SBB-GZB, 482 distinct
    trains against roughly 365 on a given day. Averaging the weekly grid
    keeps the summary figure honest.
    """
    if not grid:
        return [0.0] * HOURS
    return [round(sum(day[h] for day in grid) / len(grid), 2) for h in range(HOURS)]


def weekly_profile(traversals: Iterable[Traversal]) -> list[list[float]]:
    """A real 7x24 traffic grid, indexed [day_of_week][hour].

    This replaces hand-chosen day-of-week multipliers: RailRadar reports each
    train's runDays, so weekend and weekday traffic are measured separately
    rather than scaled from one another.
    """
    traversals = list(traversals)
    return [hourly_profile(traversals, dow) for dow in range(DAYS)]


def section_length_km(
    board_a: Iterable[StationStop], board_b: Iterable[StationStop]
) -> float | None:
    """Distance between the two stations, from trains calling at both.

    Uses the median over all such trains: individual records can be wrong,
    and different trains reach the pair by routes of differing length.
    """
    by_number_b = {s.train_number: s for s in board_b if s.distance_km is not None}
    deltas: list[float] = []
    for stop_a in board_a:
        if stop_a.distance_km is None:
            continue
        stop_b = by_number_b.get(stop_a.train_number)
        if stop_b is None or abs(stop_a.sequence - stop_b.sequence) != 1:
            continue
        delta = abs(stop_b.distance_km - stop_a.distance_km)
        if 0 < delta < 200:  # sanity bound: adjacent stations, not a whole route
            deltas.append(delta)
    if not deltas:
        return None
    deltas.sort()
    mid = len(deltas) // 2
    if len(deltas) % 2:
        return round(deltas[mid], 2)
    return round((deltas[mid - 1] + deltas[mid]) / 2, 2)


@dataclass
class DerivedSection:
    """Everything we can learn about one section from the timetable."""

    section_id: str
    station_a: str
    station_b: str
    profile: list[float]
    length_km: float | None
    traversals: list[Traversal]
    profile_by_dow: list[list[float]] = field(default_factory=list)

    @property
    def distinct_trains(self) -> int:
        """Trains traversing on any day of the week."""
        return len(self.traversals)

    @property
    def daily_trains(self) -> float:
        """Trains on an average day. Lower than distinct_trains, since not
        every train runs daily."""
        return round(sum(self.profile), 1)

    @property
    def peak_trains_per_hour(self) -> float:
        return max(self.profile) if self.profile else 0.0

    @property
    def quietest_hour(self) -> int:
        return min(range(HOURS), key=lambda h: self.profile[h])

    def summary(self) -> str:
        return (
            f"{self.section_id}: {self.daily_trains} traversals/day, "
            f"peak {self.peak_trains_per_hour:.0f}/h, "
            f"quietest {self.quietest_hour:02d}:00, "
            f"length {self.length_km if self.length_km is not None else '?'} km"
        )


def derive_section(
    station_a: str, station_b: str, payload_a: Any, payload_b: Any
) -> DerivedSection:
    board_a = parse_station_board(payload_a)
    board_b = parse_station_board(payload_b)
    traversals = find_traversals(board_a, board_b)
    grid = weekly_profile(traversals)
    return DerivedSection(
        section_id=f"{station_a.upper()}-{station_b.upper()}",
        station_a=station_a.upper(),
        station_b=station_b.upper(),
        profile=mean_profile(grid),
        length_km=section_length_km(board_a, board_b),
        traversals=traversals,
        profile_by_dow=grid,
    )


# --- train route -----------------------------------------------------------


@dataclass(frozen=True)
class RouteStop:
    """One station on a train's route, in running order."""

    sequence: int
    station_code: str
    station_name: str
    arrival_min: int | None
    departure_min: int | None
    distance_km: float | None
    is_halt: bool


def parse_train_route(payload: Any) -> list[RouteStop]:
    """Parse /trains/{number} into an ordered route.

    Fetch with haltsOnly=false so pass-through stations are included:
    consecutive entries are then genuinely adjacent stations, which is what
    makes the derived section list physically correct.
    """
    body = unwrap(payload)
    route = None
    if isinstance(body, dict):
        for key in ("route", "schedule", "stations", "stops"):
            if isinstance(body.get(key), list):
                route = body[key]
                break
    elif isinstance(body, list):
        route = body
    if route is None:
        raise ShapeError(
            "could not locate the route array in the train response. "
            f"Top-level keys: {sorted(body.keys()) if isinstance(body, dict) else type(body).__name__}"
        )

    stops: list[RouteStop] = []
    for item in route:
        if not isinstance(item, dict):
            continue
        station = item.get("station") if isinstance(item.get("station"), dict) else item
        code = _first(station, "code", "stationCode", "station_code")
        sequence = _first(item, "sequence", "seq", "stopNumber")
        if code is None or sequence is None:
            continue
        stops.append(
            RouteStop(
                sequence=int(sequence),
                station_code=str(code).strip().upper(),
                station_name=str(_first(station, "name", "stationName") or "").strip(),
                arrival_min=parse_time_to_minutes(_first(item, "arrival", "arrivalTime", "sta")),
                departure_min=parse_time_to_minutes(
                    _first(item, "departure", "departureTime", "std")
                ),
                distance_km=(
                    float(d) if (d := _first(item, "distance", "km")) is not None else None
                ),
                is_halt=bool(_first(item, "isHalt", "halt") or False),
            )
        )
    if not stops:
        raise ShapeError("train route parsed to zero stops; check the response shape")
    stops.sort(key=lambda s: s.sequence)
    return stops


def corridor_from_route(
    route: list[RouteStop], start: str | None = None, end: str | None = None
) -> list[str]:
    """Ordered station codes for a corridor, optionally trimmed to a span.

    Consecutive entries are adjacent stations, so every consecutive pair is a
    real section.
    """
    codes = [stop.station_code for stop in route]
    if start:
        start = start.upper()
        if start not in codes:
            raise ValueError(f"{start} is not on this route")
        codes = codes[codes.index(start):]
    if end:
        end = end.upper()
        if end not in codes:
            raise ValueError(f"{end} is not on this route after {start or 'origin'}")
        codes = codes[: codes.index(end) + 1]
    # Collapse any repeated code (a few trains reverse and revisit a station).
    seen: set[str] = set()
    ordered: list[str] = []
    for code in codes:
        if code not in seen:
            ordered.append(code)
            seen.add(code)
    return ordered
