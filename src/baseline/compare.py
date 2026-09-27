"""Before/after comparison: manual process against coordinated planning.

The fairness problem
--------------------
Comparing raw train-hours is misleading, and in our own disfavour twice over.
The manual baseline is confined to a fixed 4-hour night window, so it simply
cannot fit as much work: on the 300-task instance it places 218 tasks for 762
train-hours, while the planner places 272 for 914. Read naively, the baseline
"wins" — because it does less.

So we report two comparisons, and lead with the second:

  1. **Full backlog.** What each approach achieves given the same 30 days.
     Our planner completes more work; that is a real result but not a clean
     train-hours comparison.

  2. **Like for like.** The planner is re-run restricted to exactly the task
     set the baseline managed to schedule. Identical work, identical crews,
     identical horizon — the only difference is coordination and traffic
     awareness. This is the honest headline.

Quoting (1) alone would overstate us. Quoting (2) alone hides that the
manual process leaves a quarter of the backlog undone. Both belong in the
deck.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.baseline.manual import BaselineResult, ManualBaseline
from src.models import PlanningInstance
from src.optimiser.model import BlockPlanner, Solution


@dataclass
class Comparison:
    instance: PlanningInstance
    baseline: BaselineResult
    planned_full: Solution
    planned_like_for_like: Solution | None
    like_for_like_task_ids: list[str]

    @staticmethod
    def _pct(before: float, after: float) -> float:
        if before <= 0:
            return 0.0
        return round((before - after) / before * 100, 1)

    @property
    def headline_reduction_pct(self) -> float:
        """The number for slide 2: same work, fewer train-hours lost."""
        if self.planned_like_for_like is None or not self.planned_like_for_like.feasible:
            return 0.0
        return self._pct(
            self.baseline.train_hours_lost,
            self.planned_like_for_like.train_hours_lost,
        )

    @property
    def block_reduction_pct(self) -> float:
        if self.planned_like_for_like is None:
            return 0.0
        return self._pct(
            len(self.baseline.blocks), len(self.planned_like_for_like.blocks)
        )

    def overdue_completed(self, scheduled_ids: set[str]) -> int:
        return sum(
            1 for t in self.instance.tasks if t.is_overdue and t.id in scheduled_ids
        )

    def _scheduled_ids(self, result) -> set[str]:
        return {tid for block in result.blocks for tid in block.task_ids}

    def rows(self) -> list[tuple[str, str, str, str]]:
        """(metric, manual, ours-like-for-like, ours-full-backlog)"""
        base_ids = self._scheduled_ids(self.baseline)
        lfl = self.planned_like_for_like
        full = self.planned_full
        lfl_ids = self._scheduled_ids(lfl) if lfl else set()
        full_ids = self._scheduled_ids(full)

        def fmt(value, suffix=""):
            return f"{value}{suffix}"

        return [
            ("Train-hours lost",
             fmt(f"{self.baseline.train_hours_lost:.1f}"),
             fmt(f"{lfl.train_hours_lost:.1f}") if lfl else "-",
             fmt(f"{full.train_hours_lost:.1f}")),
            ("Separate blocks",
             fmt(len(self.baseline.blocks)),
             fmt(len(lfl.blocks)) if lfl else "-",
             fmt(len(full.blocks))),
            ("Tasks scheduled",
             fmt(f"{self.baseline.scheduled_count}/{len(self.instance.tasks)}"),
             fmt(f"{lfl.scheduled_count}/{len(base_ids)}") if lfl else "-",
             fmt(f"{full.scheduled_count}/{len(self.instance.tasks)}")),
            ("Overdue tasks done",
             fmt(self.overdue_completed(base_ids)),
             fmt(self.overdue_completed(lfl_ids)) if lfl else "-",
             fmt(self.overdue_completed(full_ids))),
            ("Blocks shared across departments",
             fmt(self.baseline.shared_blocks),
             fmt(lfl.shared_blocks) if lfl else "-",
             fmt(full.shared_blocks)),
            ("Peak-hour blocks",
             fmt(self.baseline.peak_hour_blocks),
             fmt(lfl.peak_hour_blocks) if lfl else "-",
             fmt(full.peak_hour_blocks)),
            ("Tasks finishing late",
             fmt(self.baseline.late_task_count),
             fmt(lfl.late_task_count) if lfl else "-",
             fmt(full.late_task_count)),
        ]


def subset_instance(instance: PlanningInstance, task_ids: set[str]) -> PlanningInstance:
    """Same instance, restricted to a chosen set of tasks."""
    return instance.model_copy(
        update={"tasks": [t for t in instance.tasks if t.id in task_ids]}
    )


def run_comparison(
    instance: PlanningInstance,
    time_limit: float = 60.0,
    percentile: float = 25.0,
    criticality: dict[str, float] | None = None,
) -> Comparison:
    baseline = ManualBaseline(instance).run()

    planned_full = BlockPlanner(
        instance, time_limit=time_limit, percentile=percentile, criticality=criticality
    ).solve()

    # Like for like: exactly the work the manual process managed to place.
    base_ids = {tid for block in baseline.blocks for tid in block.task_ids}
    like_for_like = None
    if base_ids:
        sub = subset_instance(instance, base_ids)
        like_for_like = BlockPlanner(
            sub, time_limit=time_limit, percentile=percentile,
            criticality=criticality,
        ).solve()

    return Comparison(
        instance=instance,
        baseline=baseline,
        planned_full=planned_full,
        planned_like_for_like=like_for_like,
        like_for_like_task_ids=sorted(base_ids),
    )
