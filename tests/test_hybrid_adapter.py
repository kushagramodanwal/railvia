"""The hybrid instance: real timetable sections, synthetic backlog.

Uses a stand-in grounded file so the path is exercised without network.
"""

from __future__ import annotations

import json

import pytest

from src.adapters import GroundedTimetableSource
from src.models import SourceKind


def write_grounded(tmp_path, sections):
    path = tmp_path / "grounded_sections.json"
    path.write_text(json.dumps({
        "source": "RailRadar API (public timetable)",
        "corridor": ["A", "B", "C"],
        "sections": sections,
    }))
    return path


def section_record(sid, a, b, profile, km=7.0):
    return {
        "id": sid, "station_a": a, "station_b": b,
        "length_km": km, "traffic_density_profile": profile,
        "daily_trains": int(sum(profile)),
    }


REAL_SHAPE = [2, 1, 1, 1, 2, 4, 8, 12, 14, 13, 11, 9,
              8, 7, 7, 8, 9, 12, 14, 13, 10, 7, 5, 3]


def test_hybrid_reports_per_component_provenance(tmp_path):
    path = write_grounded(tmp_path, [
        section_record("A-B", "A", "B", REAL_SHAPE),
        section_record("B-C", "B", "C", REAL_SHAPE),
    ])
    instance = GroundedTimetableSource(path=path, n_tasks=10).load()

    assert instance.sources.traffic == SourceKind.PUBLIC_TIMETABLE
    assert instance.sources.sections == SourceKind.PUBLIC_TIMETABLE
    assert instance.sources.tasks == SourceKind.SYNTHETIC
    assert instance.sources.crew_capacity == SourceKind.SYNTHETIC


def test_hybrid_still_declares_itself_synthetic_overall(tmp_path):
    """One synthetic component makes the whole instance synthetic.

    Partly-real data must never be presentable as wholly real.
    """
    path = write_grounded(tmp_path, [section_record("A-B", "A", "B", REAL_SHAPE)])
    instance = GroundedTimetableSource(path=path, n_tasks=5).load()
    assert instance.is_synthetic is True
    assert instance.is_fully_synthetic is False


def test_hybrid_uses_real_profile_and_length(tmp_path):
    path = write_grounded(tmp_path, [section_record("A-B", "A", "B", REAL_SHAPE, km=6.5)])
    instance = GroundedTimetableSource(path=path, n_tasks=5).load()
    section = instance.section("A-B")
    assert section.traffic_density_profile == [float(x) for x in REAL_SHAPE]
    assert section.length_km == 6.5
    assert section.peak_trains_per_hour == 14.0


def test_empty_profile_sections_are_dropped(tmp_path):
    """A zero profile means no traversals found — probably non-adjacent stations.

    Keeping it would present a section as free to block at any hour.
    """
    path = write_grounded(tmp_path, [
        section_record("A-B", "A", "B", REAL_SHAPE),
        section_record("B-C", "B", "C", [0] * 24),
    ])
    instance = GroundedTimetableSource(path=path, n_tasks=5).load()
    assert [s.id for s in instance.sections] == ["A-B"]


def test_all_empty_raises_rather_than_returning_nothing(tmp_path):
    path = write_grounded(tmp_path, [section_record("A-B", "A", "B", [0] * 24)])
    with pytest.raises(ValueError, match="no usable sections"):
        GroundedTimetableSource(path=path).load()


def test_missing_file_explains_how_to_build_it(tmp_path):
    with pytest.raises(FileNotFoundError, match="fetch_timetable"):
        GroundedTimetableSource(path=tmp_path / "absent.json").load()


def test_hybrid_is_deterministic(tmp_path):
    path = write_grounded(tmp_path, [section_record("A-B", "A", "B", REAL_SHAPE)])
    a = GroundedTimetableSource(path=path, seed=3).load()
    b = GroundedTimetableSource(path=path, seed=3).load()
    assert a.model_dump_json() == b.model_dump_json()


def test_hybrid_traffic_covers_horizon(tmp_path):
    path = write_grounded(tmp_path, [
        section_record("A-B", "A", "B", REAL_SHAPE),
        section_record("B-C", "B", "C", REAL_SHAPE),
    ])
    instance = GroundedTimetableSource(path=path, horizon_days=7).load()
    assert len(instance.traffic) == 2 * 7 * 24
    instance.validate_referential_integrity()


def test_no_goods_flag_invented_for_real_sections(tmp_path):
    """We have no freight data for real sections; none may be fabricated."""
    path = write_grounded(tmp_path, [section_record("A-B", "A", "B", REAL_SHAPE)])
    instance = GroundedTimetableSource(path=path).load()
    assert not any(w.is_goods_forecast for w in instance.traffic)


def test_describe_says_hybrid_not_live(tmp_path):
    path = write_grounded(tmp_path, [section_record("A-B", "A", "B", REAL_SHAPE)])
    description = GroundedTimetableSource(path=path).describe()
    assert "[HYBRID]" in description
    assert "[LIVE]" not in description
