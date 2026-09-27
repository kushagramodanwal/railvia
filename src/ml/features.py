"""Feature extraction for the criticality model.

One job only (PROJECT_BRIEF.md section 6): score each pending task for
criticality and urgency, producing a weight in [0,1] for the optimiser's
objective. Nothing here schedules anything.
"""

from __future__ import annotations

from datetime import date

from src.models import Department, PlanningInstance, Section, Task

FEATURE_NAMES = [
    "defect_severity",
    "days_overdue",
    "days_to_due",
    "interval_days",
    "days_since_last_done",
    "interval_fraction_elapsed",
    "duration_minutes",
    "crew_required",
    "section_daily_trains",
    "section_peak_trains",
    "dept_engg",
    "dept_trd",
    "dept_snt",
]


def task_features(task: Task, section: Section, as_of: date) -> list[float]:
    """One row of model input. Order must match FEATURE_NAMES."""
    days_since = (as_of - task.last_done_date).days
    elapsed = days_since / task.interval_days if task.interval_days else 0.0
    return [
        float(task.defect_severity.value),
        float(task.days_overdue(as_of)),
        float(task.days_to_due(as_of)),
        float(task.interval_days),
        float(days_since),
        float(round(elapsed, 4)),
        float(task.duration_minutes),
        float(task.crew_required),
        float(section.daily_trains),
        float(section.peak_trains_per_hour),
        1.0 if task.department == Department.ENGG else 0.0,
        1.0 if task.department == Department.TRD else 0.0,
        1.0 if task.department == Department.SNT else 0.0,
    ]


def instance_features(instance: PlanningInstance) -> tuple[list[str], list[list[float]]]:
    sections = {s.id: s for s in instance.sections}
    ids, rows = [], []
    for task in instance.tasks:
        ids.append(task.id)
        rows.append(task_features(task, sections[task.section_id], instance.horizon_start))
    return ids, rows
