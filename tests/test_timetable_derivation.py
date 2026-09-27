"""Tests for timetable -> traffic-profile derivation.

No network. Fixtures are hand-built to the documented RailRadar shape.
This logic is subtle — direction, sequence adjacency, midnight wrap — and a
quiet bug here would silently understate traffic and flatter every number we
report.
"""

from __future__ import annotations

import pytest

from src.ingest.timetable import (
    ShapeError,
    StationStop,
    derive_section,
    find_traversals,
    hourly_profile,
    parse_station_board,
    parse_time_to_minutes,
    section_length_km,
    unwrap,
)


def board(*entries: dict) -> dict:
    """Wrap entries in the documented {"success","data"} envelope."""
    return {"success": True, "data": {"trains": list(entries)}}


def entry(number, seq, arr, dep, dist, name="Test Exp", halt=True) -> dict:
    return {
        "train": {"number": number, "name": name},
        "stop": {
            "sequence": seq, "arrival": arr, "departure": dep,
            "distance": dist, "isHalt": halt,
        },
    }


# --- time parsing ----------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [("00:00", 0), ("23:55", 1435), ("9:05", 545), (None, None), ("", None),
     ("--", None), ("25:00", None), ("12:75", None)],
)
def test_parse_time(value, expected):
    assert parse_time_to_minutes(value) == expected


# --- board parsing ---------------------------------------------------------


def test_parse_documented_shape():
    stops = parse_station_board(board(entry("12919", 2, "00:55", "01:00", 55)))
    assert len(stops) == 1
    stop = stops[0]
    assert stop.train_number == "12919"
    assert stop.sequence == 2
    assert stop.arrival_min == 55
    assert stop.departure_min == 60
    assert stop.distance_km == 55.0


def test_parse_flat_shape():
    """Field names differ across API versions; the parser accepts flat records."""
    payload = {"data": [{"trainNumber": "12002", "seq": 3, "sta": "10:10",
                         "std": "10:12", "distance": 120}]}
    stops = parse_station_board(payload)
    assert stops[0].train_number == "12002"
    assert stops[0].departure_min == 612


def test_parse_rejects_unknown_shape_loudly():
    """Silent zeros are the dangerous failure: a section with no traffic
    looks free to block."""
    with pytest.raises(ShapeError):
        parse_station_board({"success": True, "data": {"unexpected": 1}})
    with pytest.raises(ShapeError):
        parse_station_board(board({"nothing": "useful"}))


def test_unwrap_envelope():
    assert unwrap({"success": True, "data": [1, 2]}) == [1, 2]
    assert unwrap([1, 2]) == [1, 2]


def test_originating_train_has_no_arrival():
    stops = parse_station_board(board(entry("12919", 1, None, "23:55", 0)))
    assert stops[0].arrival_min is None
    assert stops[0].entry_time == 1435  # falls back to departure


# --- traversal detection ---------------------------------------------------


def _stop(number, seq, arr, dep, dist=None) -> StationStop:
    return StationStop(number, "T", seq, arr, dep, dist, True)


def test_adjacent_sequences_traverse():
    a = [_stop("111", 5, 600, 605)]
    b = [_stop("111", 6, 640, 645)]
    traversals = find_traversals(a, b)
    assert len(traversals) == 1
    assert traversals[0].forward is True
    assert traversals[0].entry_min == 605  # departure from A
    assert traversals[0].exit_min == 640   # arrival at B


def test_non_adjacent_sequences_do_not_traverse():
    """Both stations on the route, but not consecutive: some other path."""
    assert find_traversals([_stop("111", 5, 600, 605)], [_stop("111", 9, 900, 905)]) == []


def test_reverse_direction_detected():
    a = [_stop("222", 8, 700, 705)]
    b = [_stop("222", 7, 640, 645)]
    traversals = find_traversals(a, b)
    assert len(traversals) == 1
    assert traversals[0].forward is False
    assert traversals[0].entry_min == 645  # departs B, arrives A
    assert traversals[0].exit_min == 700


def test_both_directions_counted():
    """Up and down trains both block the section."""
    a = [_stop("111", 5, 600, 605), _stop("222", 8, 700, 705)]
    b = [_stop("111", 6, 640, 645), _stop("222", 7, 640, 645)]
    assert len(find_traversals(a, b)) == 2


def test_train_only_on_one_board_ignored():
    assert find_traversals([_stop("111", 5, 600, 605)], [_stop("999", 6, 640, 645)]) == []


# --- profile ---------------------------------------------------------------


def test_profile_buckets_by_hour():
    a = [_stop("1", 1, None, 9 * 60 + 10), _stop("2", 1, None, 9 * 60 + 50),
         _stop("3", 1, None, 3 * 60)]
    b = [_stop("1", 2, 9 * 60 + 30, None), _stop("2", 2, 9 * 60 + 58, None),
         _stop("3", 2, 3 * 60 + 20, None)]
    profile = hourly_profile(find_traversals(a, b))
    assert profile[9] == 2
    assert profile[3] == 1
    assert sum(profile) == 3


def test_traversal_spanning_two_hours_counts_in_both():
    a = [_stop("1", 1, None, 9 * 60 + 50)]
    b = [_stop("1", 2, 10 * 60 + 20, None)]
    profile = hourly_profile(find_traversals(a, b))
    assert profile[9] == 1 and profile[10] == 1


def test_midnight_wrap():
    a = [_stop("1", 1, None, 23 * 60 + 40)]
    b = [_stop("1", 2, 0 * 60 + 15, None)]
    profile = hourly_profile(find_traversals(a, b))
    assert profile[23] == 1 and profile[0] == 1


def test_missing_arrival_does_not_inflate_a_whole_day():
    """Guard against one bad record swamping the histogram."""
    a = [_stop("1", 1, None, 5 * 60)]
    b = [_stop("1", 2, None, None)]
    profile = hourly_profile(find_traversals(a, b))
    assert sum(profile) == 1


# --- geometry --------------------------------------------------------------


def test_section_length_is_distance_delta():
    a = [_stop("1", 5, 600, 605, 100.0), _stop("2", 3, 400, 405, 60.0)]
    b = [_stop("1", 6, 640, 645, 107.0), _stop("2", 4, 440, 445, 67.0)]
    assert section_length_km(a, b) == 7.0


def test_section_length_ignores_absurd_deltas():
    a = [_stop("1", 5, 600, 605, 100.0)]
    b = [_stop("1", 6, 640, 645, 900.0)]  # 800 km between adjacent stations
    assert section_length_km(a, b) is None


def test_section_length_none_without_distances():
    assert section_length_km([_stop("1", 5, 600, 605)], [_stop("1", 6, 640, 645)]) is None


# --- end to end ------------------------------------------------------------


def test_derive_section_end_to_end():
    a = board(entry("111", 5, "10:00", "10:05", 100),
              entry("222", 8, "11:40", "11:45", 140))
    b = board(entry("111", 6, "10:30", "10:32", 107),
              entry("222", 7, "11:10", "11:15", 147))
    section = derive_section("NDLS", "DSA", a, b)
    assert section.section_id == "NDLS-DSA"
    assert section.daily_trains == pytest.approx(2)
    assert section.length_km == 7.0
    assert sum(section.profile) >= 2
    assert "NDLS-DSA" in section.summary()


# --- train route -----------------------------------------------------------


def route_payload(*stops: dict) -> dict:
    return {"success": True, "data": {"train": {"number": "12002"}, "route": list(stops)}}


def rstop(seq, code, name="S", arr="10:00", dep="10:02", dist=0, halt=True) -> dict:
    return {
        "sequence": seq, "station": {"code": code, "name": name},
        "arrival": arr, "departure": dep, "distance": dist, "isHalt": halt,
    }


def test_parse_train_route_orders_by_sequence():
    from src.ingest.timetable import parse_train_route

    route = parse_train_route(route_payload(rstop(3, "C"), rstop(1, "A"), rstop(2, "B")))
    assert [s.station_code for s in route] == ["A", "B", "C"]


def test_parse_train_route_rejects_unknown_shape():
    from src.ingest.timetable import parse_train_route

    with pytest.raises(ShapeError):
        parse_train_route({"success": True, "data": {"nope": 1}})


def test_corridor_from_route_and_trimming():
    from src.ingest.timetable import corridor_from_route, parse_train_route

    route = parse_train_route(
        route_payload(rstop(1, "A"), rstop(2, "B"), rstop(3, "C"), rstop(4, "D"))
    )
    assert corridor_from_route(route) == ["A", "B", "C", "D"]
    assert corridor_from_route(route, start="B") == ["B", "C", "D"]
    assert corridor_from_route(route, start="B", end="C") == ["B", "C"]
    with pytest.raises(ValueError):
        corridor_from_route(route, start="Z")


def test_corridor_collapses_revisited_stations():
    from src.ingest.timetable import corridor_from_route, parse_train_route

    route = parse_train_route(
        route_payload(rstop(1, "A"), rstop(2, "B"), rstop(3, "A"), rstop(4, "C"))
    )
    assert corridor_from_route(route) == ["A", "B", "C"]


# --- live-schema details ---------------------------------------------------


def test_stop_type_maps_to_is_halt():
    """Live responses use stopType, not an isHalt boolean."""
    from src.ingest.timetable import parse_station_board

    def with_type(stop_type):
        e = entry("111", 2, "10:00", "10:02", 50)
        e["stop"].pop("isHalt")
        e["stop"]["stopType"] = stop_type
        return parse_station_board(board(e))[0]

    assert with_type("halt").is_halt is True
    assert with_type("origin").is_halt is True
    assert with_type("destination").is_halt is True
    assert with_type("pass-through").is_halt is False


def test_pass_through_trains_still_count_as_traffic():
    """A train that does not stop still occupies the section."""
    from src.ingest.timetable import find_traversals, parse_station_board

    def side(seq, stop_type):
        e = entry("111", seq, "10:00", "10:05", 50)
        e["stop"].pop("isHalt")
        e["stop"]["stopType"] = stop_type
        return parse_station_board(board(e))

    assert len(find_traversals(side(5, "pass-through"), side(6, "pass-through"))) == 1


def test_parse_run_days():
    from src.ingest.timetable import ALL_DAYS, parse_run_days

    assert parse_run_days(["mon", "tue", "wed", "thu", "fri", "sat", "sun"]) == ALL_DAYS
    assert parse_run_days(["sun"]) == frozenset({6})
    assert parse_run_days(["Mon", "FRI"]) == frozenset({0, 4})


def test_missing_run_days_defaults_to_daily():
    """Conservative: a parsing gap must never make a section look quieter."""
    from src.ingest.timetable import ALL_DAYS, parse_run_days

    assert parse_run_days(None) == ALL_DAYS
    assert parse_run_days([]) == ALL_DAYS
    assert parse_run_days(["nonsense"]) == ALL_DAYS


def test_run_days_reach_the_traversal():
    from src.ingest.timetable import find_traversals, parse_station_board

    def side(seq, days):
        e = entry("111", seq, "10:00", "10:05", 50)
        e["train"]["runDays"] = days
        return parse_station_board(board(e))

    traversal = find_traversals(side(5, ["sat", "sun"]), side(6, ["sat", "sun"]))[0]
    assert traversal.run_days == frozenset({5, 6})
    assert traversal.runs_on(5) is True
    assert traversal.runs_on(0) is False


def test_weekly_profile_reflects_run_days():
    """Sunday-only trains must not appear in Monday's profile."""
    from src.ingest.timetable import Traversal, weekly_profile

    daily = Traversal("1", "A", True, 9 * 60, 9 * 60 + 20)
    sunday = Traversal("2", "B", True, 9 * 60, 9 * 60 + 20, run_days=frozenset({6}))
    grid = weekly_profile([daily, sunday])
    assert len(grid) == 7 and all(len(row) == 24 for row in grid)
    assert grid[0][9] == 1  # Monday: daily train only
    assert grid[6][9] == 2  # Sunday: both


def test_derive_section_populates_weekly_grid():
    a = board(entry("111", 5, "10:00", "10:05", 100))
    b = board(entry("111", 6, "10:30", "10:32", 107))
    section = derive_section("NDLS", "DSA", a, b)
    assert len(section.profile_by_dow) == 7
    assert all(len(row) == 24 for row in section.profile_by_dow)
