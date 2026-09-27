"""Model-level invariants. Constraint tests arrive in Phase 1."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from src.models import Block, Department, Section, Severity, Task


def _section(profile=None) -> dict:
    return dict(
        id="X-Y", name="X - Y", division="D", length_km=10.0,
        traffic_density_profile=profile if profile is not None else [1.0] * 24,
    )


def test_traffic_profile_must_be_24_hours():
    with pytest.raises(ValidationError):
        Section(**_section([1.0] * 23))
    with pytest.raises(ValidationError):
        Section(**_section([1.0] * 25))


def test_traffic_profile_rejects_negative():
    with pytest.raises(ValidationError):
        Section(**_section([1.0] * 23 + [-1.0]))


def test_section_length_must_be_positive():
    with pytest.raises(ValidationError):
        Section(**{**_section(), "length_km": 0})


def test_section_derived_traffic_stats():
    s = Section(**_section([2.0] * 12 + [4.0] * 12))
    assert s.peak_trains_per_hour == 4.0
    assert s.daily_trains == 72.0


def _task(**over) -> Task:
    base = dict(
        id="T001", department=Department.ENGG, section_id="X-Y",
        activity_type="through_packing", duration_minutes=120, crew_required=2,
        last_done_date=date(2025, 3, 1), interval_days=365,
        due_date=date(2026, 3, 1), defect_severity=Severity.MODERATE,
        is_overdue=False,
    )
    return Task(**{**base, **over})


def test_task_duration_must_be_positive():
    with pytest.raises(ValidationError):
        _task(duration_minutes=0)


def test_task_overdue_arithmetic():
    t = _task(due_date=date(2026, 3, 1))
    assert t.days_overdue(date(2026, 3, 11)) == 10
    assert t.days_overdue(date(2026, 2, 20)) == 0  # never negative
    assert t.days_to_due(date(2026, 2, 20)) == 9
    assert t.days_to_due(date(2026, 3, 11)) == -10


def test_task_duration_hours():
    assert _task(duration_minutes=90).duration_hours == 1.5


def _block(**over) -> Block:
    base = dict(
        id="B001", section_id="X-Y",
        start=datetime(2026, 3, 2, 1, 0), end=datetime(2026, 3, 2, 4, 0),
        task_ids=["T001"], departments=[Department.ENGG],
    )
    return Block(**{**base, **over})


def test_block_end_must_follow_start():
    with pytest.raises(ValidationError):
        _block(end=datetime(2026, 3, 2, 1, 0))
    with pytest.raises(ValidationError):
        _block(end=datetime(2026, 3, 2, 0, 0))


def test_block_must_carry_at_least_one_task():
    with pytest.raises(ValidationError):
        _block(task_ids=[])


def test_block_duration_and_sharing():
    b = _block()
    assert b.duration_hours == 3.0
    assert b.is_shared is False
    shared = _block(
        task_ids=["T001", "T002"],
        departments=[Department.ENGG, Department.SNT],
    )
    assert shared.is_shared is True
