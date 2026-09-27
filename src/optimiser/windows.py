"""Time discretisation and permitted-window computation.

Everything the CP-SAT model needs to know about *when* work may happen is
worked out here, in plain Python, so it can be tested directly rather than
inferred from solver behaviour.

Two jobs:
  1. Cut the planning horizon into fixed slots and map each slot to the
     traffic on a section at that moment.
  2. Decide which slots are blockable, and from that which start times let a
     task of a given length fit entirely inside a permitted run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from src.models import PlanningInstance

SLOT_MINUTES = 15  # Matches the 15-minute granularity of task durations.

# Blocks are permitted only in each section's own quietest hours. A fixed
# absolute threshold does not survive contact with real data: on the
# Sahibabad-Ghaziabad trunk, traffic never falls below 2.9 trains/hour and
# only 2 hours a day sit under 8/h, so a flat "> 8 forbidden" rule leaves no
# window long enough for a 4-hour job. Measuring each section against itself
# keeps every section workable and adapts to any corridor we ingest later.
# See ASSUMPTIONS.md (A-14).
DEFAULT_PERCENTILE = 25.0


@dataclass(frozen=True)
class TimeGrid:
    """The planning horizon, cut into slots."""

    horizon_start: date
    horizon_days: int
    slot_minutes: int = SLOT_MINUTES

    @property
    def slots_per_hour(self) -> int:
        return 60 // self.slot_minutes

    @property
    def slots_per_day(self) -> int:
        return 24 * self.slots_per_hour

    @property
    def n_slots(self) -> int:
        return self.horizon_days * self.slots_per_day

    @property
    def slot_hours(self) -> float:
        return self.slot_minutes / 60

    def minutes_to_slots(self, minutes: int) -> int:
        """Round up: a task may not be squeezed into fewer slots than it needs."""
        return -(-minutes // self.slot_minutes)

    def day_hour(self, slot: int) -> tuple[date, int]:
        day_index, within = divmod(slot, self.slots_per_day)
        return (
            self.horizon_start + timedelta(days=day_index),
            within // self.slots_per_hour,
        )

    def to_datetime(self, slot: int) -> datetime:
        return datetime.combine(self.horizon_start, datetime.min.time()) + timedelta(
            minutes=slot * self.slot_minutes
        )


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile. No numpy dependency for one number."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if pct <= 0:
        return ordered[0]
    rank = max(1, min(len(ordered), int(-(-pct / 100 * len(ordered) // 1))))
    return ordered[rank - 1]


def traffic_by_slot(instance: PlanningInstance, grid: TimeGrid) -> dict[str, list[float]]:
    """Trains per hour on each section, indexed by slot.

    Missing windows default to 0. That is the optimistic direction, so the
    builder below asserts full coverage rather than trusting it.
    """
    lookup: dict[tuple[str, date, int], float] = {
        (w.section_id, w.day, w.hour_of_day): w.trains_per_hour for w in instance.traffic
    }
    by_section: dict[str, list[float]] = {}
    for section in instance.sections:
        series = []
        for slot in range(grid.n_slots):
            day, hour = grid.day_hour(slot)
            series.append(float(lookup.get((section.id, day, hour), 0.0)))
        by_section[section.id] = series
    return by_section


def permitted_slots(series: list[float], pct: float = DEFAULT_PERCENTILE) -> list[bool]:
    """Which slots may carry a block, per the section's own traffic profile."""
    threshold = percentile(series, pct)
    return [value <= threshold for value in series]


def feasible_starts(permitted: list[bool], duration_slots: int) -> list[int]:
    """Start slots where the whole duration fits inside permitted time.

    Windows do not wrap past the end of the horizon: a block must finish
    inside the planning window (constraint 5).
    """
    if duration_slots <= 0:
        return []
    n = len(permitted)
    # Sliding count of permitted slots, so this stays linear rather than
    # re-scanning the duration for every candidate start.
    starts: list[int] = []
    run = 0
    for index in range(n):
        run = run + 1 if permitted[index] else 0
        start = index - duration_slots + 1
        if run >= duration_slots and start >= 0:
            starts.append(start)
    return starts


def permitted_runs(permitted: list[bool]) -> list[tuple[int, int]]:
    """Maximal contiguous permitted stretches, as [start, end) slot pairs.

    Used for reporting and diagnostics, not by the model itself.
    """
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, ok in enumerate(permitted):
        if ok and start is None:
            start = index
        elif not ok and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(permitted)))
    return runs


def cumulative_train_hours(series: list[float], grid: TimeGrid, scale: int = 100) -> list[int]:
    """Prefix sums of train-hours, so a block's cost is one subtraction.

    cost(start, end) = cum[end] - cum[start]

    Scaled to integers because CP-SAT is an integer solver; `scale` = 100
    keeps two decimal places of a train-hour, which is far finer than the
    input data justifies.
    """
    cumulative = [0]
    total = 0
    for value in series:
        total += round(value * grid.slot_hours * scale)
        cumulative.append(total)
    return cumulative


def run_end_index(permitted: list[bool]) -> list[int]:
    """For each slot, the exclusive end of the permitted run containing it.

    Lets the model express "this block lies inside one contiguous permitted
    window" as a single element lookup plus an inequality:

        run_end = RUN_END[block_start]
        block_end <= run_end

    The alternative — one boolean per candidate run per block — produced
    roughly 19,000 booleans on a 30-day, 39-section instance and the solver
    could not find any feasible schedule inside 60 seconds.

    Forbidden slots map to themselves, so a block can never start on one.
    """
    n = len(permitted)
    ends = [0] * n
    end_of_run = n
    for index in range(n - 1, -1, -1):
        if not permitted[index]:
            end_of_run = index
            ends[index] = index
        else:
            ends[index] = end_of_run
    return ends
