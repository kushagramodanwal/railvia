"""Scenario re-planning: something overran, re-optimise what is left.

A block plan meets reality within hours. A tamping machine breaks down, a
possession is handed back late, a section is released early. The question a
controller actually asks is not "what was the plan" but "given where we are
now, what should the rest of the month look like".

How this works
--------------
Re-planning is not a special solver mode. We freeze the past, subtract the
work already done, and hand the remainder to the same CP-SAT model:

  * Work that finished before the disruption is removed from the backlog.
  * Work in progress at the disruption is kept, and the section it occupies
    is made unavailable for the length of the overrun.
  * Everything still pending is re-planned from the disruption onward.

Because the horizon shrinks, the re-plan can legitimately be worse than the
original — fewer quiet windows remain. Reporting that honestly is the point:
a re-planner that always claims improvement is not measuring anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from src.models import PlanningInstance
from src.optimiser.model import BlockPlanner, Solution


@dataclass
class Disruption:
    """One thing going wrong, at a point in the plan."""

    at_slot: int
    section_id: str
    overrun_slots: int
    description: str = ""


@dataclass
class ReplanResult:
    original: Solution
    replanned: Solution
    completed_task_ids: list[str]
    carried_task_ids: list[str]
    disruption: Disruption

    @property
    def train_hours_delta(self) -> float:
        """Positive means the disruption cost us train-hours."""
        return round(
            self.replanned.train_hours_lost - self._original_remaining_hours(), 3
        )

    def _original_remaining_hours(self) -> float:
        return round(
            sum(
                b.train_hours for b in self.original.blocks
                if b.start_slot >= self.disruption.at_slot
            ),
            3,
        )

    def summary(self) -> str:
        return (
            f"disruption at slot {self.disruption.at_slot} on "
            f"{self.disruption.section_id}: {self.disruption.description}\n"
            f"  {len(self.completed_task_ids)} tasks already done, "
            f"{len(self.carried_task_ids)} re-planned\n"
            f"  original remaining: {self._original_remaining_hours():.1f} train-hours\n"
            f"  after re-plan     : {self.replanned.train_hours_lost:.1f} train-hours "
            f"({self.train_hours_delta:+.1f})\n"
            f"  status {self.replanned.status}, {self.replanned.wall_time:.1f}s"
        )


def replan_after(
    instance: PlanningInstance,
    original: Solution,
    disruption: Disruption,
    time_limit: float = 30.0,
    percentile: float = 25.0,
    criticality: dict[str, float] | None = None,
    greedy_only: bool = False,
) -> ReplanResult:
    """Re-solve the remainder of the horizon after a disruption.

    `greedy_only` skips building the CP-SAT model and returns the constructive
    schedule instead. It exists for hosts too small to hold the model — the
    deployed image runs with runtime solving off — and the returned status
    says which route was taken, so a greedy re-plan is never mistaken for an
    optimised one.
    """
    completed: list[str] = []
    carried: list[str] = []

    for block in original.blocks:
        finished = block.end_slot <= disruption.at_slot
        for task_id in block.task_ids:
            (completed if finished else carried).append(task_id)

    # Anything the original plan never placed is still outstanding.
    carried.extend(original.unscheduled_task_ids)
    carried = sorted(set(carried) - set(completed))

    remaining = instance.model_copy(
        update={"tasks": [t for t in instance.tasks if t.id in set(carried)]}
    )

    # The disrupted section is unavailable until the overrun clears; express
    # it by removing those hours from the traffic windows the planner sees.
    blocked_until = disruption.at_slot + disruption.overrun_slots
    grid_day = 96  # 15-minute slots per day
    busy_hours = {
        (
            instance.horizon_start + timedelta(days=slot // grid_day),
            (slot % grid_day) // 4,
        )
        for slot in range(disruption.at_slot, blocked_until)
    }
    traffic = [
        w.model_copy(update={"trains_per_hour": 9_999.0})
        if (w.section_id == disruption.section_id and (w.day, w.hour_of_day) in busy_hours)
        else w
        for w in remaining.traffic
    ]
    remaining = remaining.model_copy(update={"traffic": traffic})

    weights = (
        {k: v for k, v in criticality.items() if k in set(carried)}
        if criticality else None
    )
    planner = BlockPlanner(
        remaining, time_limit=time_limit, percentile=percentile,
        criticality=weights, build_model=not greedy_only,
    )
    replanned = planner.greedy_only() if greedy_only else planner.solve()

    return ReplanResult(
        original=original,
        replanned=replanned,
        completed_task_ids=sorted(set(completed)),
        carried_task_ids=carried,
        disruption=disruption,
    )
