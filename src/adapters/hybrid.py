"""Real timetable + synthetic maintenance backlog.

This is the most honest instance we can currently build, and the reason the
distinction matters:

  * `sections` and `traffic` come from the **published Indian Railways
    timetable**, via the RailRadar aggregator. Real section geometry, real
    trains, real hourly distribution.
  * `tasks` and `crew_capacity` remain **synthetic**. Maintenance backlogs
    live in TMS/SMMS/TDMS, which are internal systems with no public
    equivalent. Nothing we can do closes that gap.

Which means the cost side of the objective — train-hours lost, the number in
the headline claim — is computed against real traffic. Only the work being
scheduled is invented. That is a materially stronger position than a fully
synthetic instance, and it is worth stating precisely rather than rounding
off in either direction.

This class occupies the COA slot: COA holds the timetable internally, and the
public timetable is the same information.
"""

from __future__ import annotations

import json
import pathlib
import random
from datetime import date

from src.adapters.base import DataSource
from src.models import (
    DataProvenance,
    next_monday,
    PlanningInstance,
    Section,
    SourceKind,
    TrafficWindow,
)

DEFAULT_GROUNDED_PATH = pathlib.Path("data/grounded_sections.json")

PROVENANCE = (
    "HYBRID. Sections and traffic derived from the published Indian Railways "
    "timetable via the RailRadar API (a third-party aggregator of public NTES "
    "data, not an official Railways endpoint). Maintenance tasks and crew "
    "capacity are SYNTHETIC — TMS/SMMS/TDMS have no public equivalent. "
    "See ASSUMPTIONS.md."
)


class GroundedTimetableSource(DataSource):
    """Builds a planning instance on real timetable-derived sections.

    Reads the file written by scripts/fetch_timetable.py. The API is never
    called at load time: the fetch is a separate, cached, offline step, so a
    demo cannot fail because of someone's network.
    """

    is_synthetic = False  # of the timetable half; the instance reports per component
    is_connected = True

    def __init__(
        self,
        path: pathlib.Path | str = DEFAULT_GROUNDED_PATH,
        seed: int = 42,
        n_tasks: int = 20,
        horizon_days: int = 7,
        horizon_start: date | None = None,
        division: str = "Delhi (Northern Railway)",
    ) -> None:
        self.path = pathlib.Path(path)
        self.seed = seed
        self.n_tasks = n_tasks
        self.horizon_days = horizon_days
        # None means "the upcoming Monday" — what a planner wants when they
        # open the app. Callers that need a fixed, reproducible instance pass
        # a date explicitly.
        self.horizon_start = horizon_start or next_monday()
        self.division = division
        self._weekly: dict[str, list[list[float]]] = {}

    @property
    def provenance(self) -> str:  # type: ignore[override]
        return (
            f"timetable-derived sections from {self.path}; "
            f"{self.n_tasks} synthetic tasks, seed={self.seed}"
        )

    def describe(self) -> str:
        return f"[HYBRID] {type(self).__name__}: {self.provenance}"

    def available(self) -> bool:
        return self.path.exists()

    def load_sections(self) -> list[Section]:
        if not self.path.exists():
            raise FileNotFoundError(
                f"{self.path} not found. Build it first:\n"
                f"  RAILRADAR_API_KEY=... .venv/bin/python scripts/fetch_timetable.py "
                f"--from-train <number> --start <code> --end <code>"
            )
        payload = json.loads(self.path.read_text())
        self._weekly: dict[str, list[list[float]]] = {}
        sections: list[Section] = []
        for record in payload["sections"]:
            profile = [float(x) for x in record["traffic_density_profile"]]
            if len(profile) != 24 or sum(profile) == 0:
                # A zero profile means no traversals were found: the pair is
                # probably not adjacent. Dropping it is right — a section that
                # looks empty would be scheduled through rush hour for free.
                continue
            grid = record.get("profile_by_dow")
            if isinstance(grid, list) and len(grid) == 7:
                self._weekly[record["id"]] = [[float(x) for x in row] for row in grid]
            length = record.get("length_km")
            sections.append(
                Section(
                    id=record["id"],
                    name=record.get("name")
                    or f"{record['station_a']} - {record['station_b']}",
                    division=self.division,
                    # Fall back only when the timetable carried no distance.
                    length_km=float(length) if length else 1.0,
                    traffic_density_profile=profile,
                )
            )
        if not sections:
            raise ValueError(
                f"{self.path} yielded no usable sections (all profiles empty)."
            )
        return sections

    def build_traffic_windows(self, sections: list[Section]) -> list[TrafficWindow]:
        """Expand the real 7x24 grid into per-day traffic windows.

        Where a weekly grid is available we use the measured day-of-week
        traffic directly, instead of scaling one weekday shape by invented
        multipliers. Sections lacking a grid fall back to the flat profile.

        No goods windows are flagged: freight paths do not appear in public
        timetables, and inventing them would be fabricating traffic.
        """
        from datetime import timedelta

        windows: list[TrafficWindow] = []
        for section in sections:
            grid = self._weekly.get(section.id)
            for offset in range(self.horizon_days):
                day = self.horizon_start + timedelta(days=offset)
                dow = day.weekday()
                profile = grid[dow] if grid else section.traffic_density_profile
                for hour in range(24):
                    windows.append(
                        TrafficWindow(
                            section_id=section.id,
                            day=day,
                            hour_of_day=hour,
                            day_of_week=dow,
                            trains_per_hour=round(float(profile[hour]), 2),
                            is_goods_forecast=False,
                        )
                    )
        return windows

    def load(self) -> PlanningInstance:
        # The adapter layer is the one place permitted to know the generator
        # exists; downstream packages must go through DataSource.
        from src.generator.synthetic import build_crew_capacity, generate_tasks

        sections = self.load_sections()
        rng = random.Random(self.seed)
        tasks = generate_tasks(
            rng, sections, self.n_tasks, self.horizon_start, self.horizon_days
        )

        instance = PlanningInstance(
            instance_id=(
                f"hybrid-s{self.seed}-{len(sections)}sec-"
                f"{self.n_tasks}task-{self.horizon_days}d"
            ),
            generated_at=__import__("datetime").datetime(2026, 1, 1),
            seed=self.seed,
            sources=DataProvenance(
                sections=SourceKind.PUBLIC_TIMETABLE,
                tasks=SourceKind.SYNTHETIC,
                traffic=SourceKind.PUBLIC_TIMETABLE,
                crew_capacity=SourceKind.SYNTHETIC,
                notes=(
                    "Section geometry, hourly traffic and day-of-week variation "
                    "from the published timetable (train runDays); maintenance "
                    "backlog and crew strength generated. No freight: goods "
                    "paths are absent from public timetables."
                ),
            ),
            provenance=PROVENANCE,
            horizon_start=self.horizon_start,
            horizon_days=self.horizon_days,
            sections=sections,
            tasks=tasks,
            traffic=self.build_traffic_windows(sections),
            crew_capacity=build_crew_capacity(
                rng, self.horizon_start, self.horizon_days, self.n_tasks
            ),
        )
        instance.validate_referential_integrity()
        return instance
