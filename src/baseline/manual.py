"""Simulator for the current manual process.

This produces the comparison number the project is judged on, so the
simulation has to be *fair*. A strawman baseline that schedules maintenance
through rush hour would hand us a huge improvement and would be torn apart
by the first judge who asks how blocks are requested today.

What we model
-------------
The problem statement names two failures, and we model exactly those:

  1. **No coordination between departments.** ENGG, TRD and S&T each raise
     their own block demands through BDMS, against their own defect lists in
     TMS / SMMS / TDMS. Nobody merges two departments' work on one section
     into a single handover, so each task gets its own block.

  2. **Not optimised against the timetable.** Blocks are requested in the
     conventional night maintenance window, applied uniformly. That is a
     sensible rule of thumb, not an absurd one — but it is the *same* window
     for every section, so it cannot exploit the fact that one section is
     quiet at 02:00 and another at 14:00.

What we deliberately DO give the baseline
-----------------------------------------
  * The night window, so it is not caricatured as blocking at 09:00.
  * Physical safety: two blocks never overlap on one section, whichever
    department asked. A real controller would refuse the second request.
  * Its own crew limits, respected per department.
  * Urgency ordering: the most overdue work is requested first.

The gap that remains is therefore attributable to coordination and
traffic-awareness alone, which is the claim we want to make.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.models import Department, PlanningInstance, Task
from src.optimiser.model import ScheduledBlock
from src.optimiser.windows import TimeGrid, traffic_by_slot

# The conventional night maintenance window, applied to every section alike.
# Indian Railways commonly grants engineering blocks in the small hours; the
# point of the baseline is that this is a fixed habit rather than a
# per-section calculation. See ASSUMPTIONS.md (A-17).
CONVENTIONAL_WINDOW_START_HOUR = 1
CONVENTIONAL_WINDOW_END_HOUR = 5


@dataclass
class BaselineResult:
    """Deliberately shaped like Solution, so both feed one comparison table."""

    blocks: list[ScheduledBlock]
    unscheduled_task_ids: list[str]
    train_hours_lost: float
    late_days: dict[str, int] = field(default_factory=dict)
    peak_hour_block_count: int = 0

    @property
    def feasible(self) -> bool:
        return True

    @property
    def status(self) -> str:
        return "MANUAL"

    @property
    def shared_blocks(self) -> int:
        return sum(1 for b in self.blocks if b.is_shared)

    @property
    def scheduled_count(self) -> int:
        return sum(len(b.task_ids) for b in self.blocks)

    @property
    def total_days_late(self) -> int:
        return sum(self.late_days.values())

    @property
    def late_task_count(self) -> int:
        return sum(1 for v in self.late_days.values() if v > 0)

    @property
    def peak_hour_blocks(self) -> int:
        return self.peak_hour_block_count


class ManualBaseline:
    """Replays the current process: three departments, no coordination."""

    def __init__(
        self,
        instance: PlanningInstance,
        slot_minutes: int = 15,
        window_start_hour: int = CONVENTIONAL_WINDOW_START_HOUR,
        window_end_hour: int = CONVENTIONAL_WINDOW_END_HOUR,
        peak_threshold: float = 8.0,
    ) -> None:
        self.instance = instance
        self.grid = TimeGrid(instance.horizon_start, instance.horizon_days, slot_minutes)
        self.traffic = traffic_by_slot(instance, self.grid)
        self.window_start_hour = window_start_hour
        self.window_end_hour = window_end_hour
        self.peak_threshold = peak_threshold

    def _window_slots(self, day: int) -> tuple[int, int]:
        base = day * self.grid.slots_per_day
        return (
            base + self.window_start_hour * self.grid.slots_per_hour,
            base + self.window_end_hour * self.grid.slots_per_hour,
        )

    def _cost(self, section_id: str, start: int, end: int) -> float:
        series = self.traffic[section_id]
        return round(
            sum(series[s] for s in range(start, min(end, len(series))))
            * self.grid.slot_hours,
            3,
        )

    def _crew_capacity(self) -> dict[tuple[Department, int], int]:
        caps: dict[tuple[Department, int], int] = {}
        for record in self.instance.crew_capacity:
            offset = (record.date - self.instance.horizon_start).days
            if 0 <= offset < self.instance.horizon_days:
                caps[(record.department, offset)] = record.available_crews
        return caps

    def run(self) -> BaselineResult:
        grid = self.grid
        capacity = self._crew_capacity()
        crew_used: dict[tuple[Department, int], int] = {}
        # Occupied stretches per section, across ALL departments: a controller
        # will not grant two overlapping blocks on one section.
        occupied: dict[str, list[tuple[int, int]]] = {}

        blocks: list[ScheduledBlock] = []
        unscheduled: list[str] = []
        late_days: dict[str, int] = {}
        peak_blocks = 0

        # Each department works its own list, most overdue first. Departments
        # are processed in turn — there is no shared queue and no merging,
        # which is precisely the coordination failure being modelled.
        for dept in Department:
            tasks = sorted(
                (t for t in self.instance.tasks if t.department == dept),
                key=lambda t: (t.due_date, -t.defect_severity.value, t.id),
            )
            for task in tasks:
                placement = self._place(task, occupied, capacity, crew_used)
                if placement is None:
                    unscheduled.append(task.id)
                    continue
                start, end, day = placement
                occupied.setdefault(task.section_id, []).append((start, end))
                crew_used[(dept, day)] = (
                    crew_used.get((dept, day), 0) + task.crew_required
                )
                cost = self._cost(task.section_id, start, end)
                if self._touches_peak(task.section_id, start, end):
                    peak_blocks += 1
                blocks.append(
                    ScheduledBlock(
                        section_id=task.section_id,
                        start_slot=start, end_slot=end,
                        task_ids=[task.id], departments=[dept],
                        train_hours=cost,
                    )
                )
                due_day = (task.due_date - self.instance.horizon_start).days
                lateness = max(0, (end // grid.slots_per_day) - due_day)
                if lateness:
                    late_days[task.id] = lateness

        blocks.sort(key=lambda b: (b.start_slot, b.section_id))
        return BaselineResult(
            blocks=blocks,
            unscheduled_task_ids=unscheduled,
            train_hours_lost=round(sum(b.train_hours for b in blocks), 3),
            late_days=late_days,
            peak_hour_block_count=peak_blocks,
        )

    def _touches_peak(self, section_id: str, start: int, end: int) -> bool:
        series = self.traffic[section_id]
        return any(
            series[s] > self.peak_threshold for s in range(start, min(end, len(series)))
        )

    def _place(
        self,
        task: Task,
        occupied: dict[str, list[tuple[int, int]]],
        capacity: dict[tuple[Department, int], int],
        crew_used: dict[tuple[Department, int], int],
    ) -> tuple[int, int, int] | None:
        """Earliest night window that fits, scanning forward day by day."""
        length = self.grid.minutes_to_slots(task.duration_minutes)
        taken = occupied.get(task.section_id, [])

        for day in range(self.instance.horizon_days):
            available = capacity.get((task.department, day), 0)
            if crew_used.get((task.department, day), 0) + task.crew_required > available:
                continue
            window_start, window_end = self._window_slots(day)
            if window_end - window_start < length:
                continue
            # First free position inside the window, after anything already
            # granted on this section.
            cursor = window_start
            while cursor + length <= window_end:
                clash = next(
                    ((s, e) for s, e in taken if s < cursor + length and cursor < e),
                    None,
                )
                if clash is None:
                    return cursor, cursor + length, day
                cursor = clash[1]
            continue
        return None
