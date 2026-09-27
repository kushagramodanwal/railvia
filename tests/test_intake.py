"""Field intake: the shared front door for defects.

Three departments raising work through three systems is the reason the same
section gets closed three times. These tests cover the parts of the single
intake that can be checked without a database: the vocabulary it offers, the
arithmetic behind its cost estimate, and the fact that filing anything at all
requires a signed-in caller.

Storage itself is Supabase, so it is exercised by the row-level-security
policies in schema.sql rather than here — an in-memory fake would prove only
that the fake works.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.app import app
from src.models import CATALOGUE
from src.optimiser.windows import DEFAULT_PERCENTILE, TimeGrid, permitted_slots, traffic_by_slot
from src.store import Report, ReportStatus

client = TestClient(app)
SMALL = {"grounded": "false", "tasks": "8", "days": "3", "seed": "1"}


def test_form_offers_exactly_what_the_planner_can_schedule():
    """A form with its own activity list would drift from the optimiser's.

    A report naming work the planner has never heard of cannot be placed, so
    the two lists are the same list.
    """
    body = client.get("/api/activities").json()
    assert {a["activity_type"] for a in body["activities"]} == {
        spec.activity_type for spec in CATALOGUE
    }
    assert body["departments"] == ["ENGG", "TRD", "S&T"]


def test_provisional_periodicities_are_not_hidden_from_the_form():
    """Every interval in the catalogue is still provisional (A-01).

    The form must be able to say so; silently presenting them as mandated
    would be the one dishonest thing this page could do.
    """
    for entry in client.get("/api/activities").json()["activities"]:
        assert entry["source"]


def test_quiet_windows_are_ordered_by_what_they_cost():
    body = client.get(
        "/api/window",
        params={**SMALL, "section_id": _a_section(), "minutes": "60"},
    ).json()
    costs = [c["train_hours"] for c in body["candidates"]]
    assert costs == sorted(costs)
    assert all(c["end"] > c["start"] for c in body["candidates"])


def test_the_quoted_cost_is_the_traffic_actually_in_that_window():
    """The number shown to an engineer has to be the real integral, not a
    proxy. Recomputed here straight from the traffic profile."""
    section = _a_section()
    body = client.get(
        "/api/window",
        params={**SMALL, "section_id": section, "minutes": "60"},
    ).json()
    best = body["candidates"][0]

    from datetime import datetime

    from src.api.app import _load, _parse_start

    start = _parse_start(None)
    instance = _load(False, 8, 3, 1, start)
    grid = TimeGrid(horizon_start=start, horizon_days=3)
    series = traffic_by_slot(instance, grid)[section]

    slot = round(
        (datetime.fromisoformat(best["start"]) - grid.to_datetime(0)).total_seconds()
        / 60 / grid.slot_minutes
    )
    length = grid.minutes_to_slots(60)
    expected = sum(series[slot:slot + length]) * grid.slot_hours
    assert abs(best["train_hours"] - expected) < 0.01


def test_a_job_longer_than_any_quiet_stretch_is_told_so_plainly():
    """Not an error — a real answer. It means the job needs a traffic block,
    which is a different authority's decision."""
    section = _a_section()
    body = client.get(
        "/api/window",
        params={**SMALL, "section_id": section, "minutes": "4320"},  # 3 days
    ).json()
    assert body["candidates"] == []
    assert body["earliest"] is None


def test_unknown_section_is_a_404_not_a_crash():
    assert client.get(
        "/api/window", params={**SMALL, "section_id": "NOWHERE-AT-ALL"}
    ).status_code == 404


def test_window_share_matches_the_percentile_rule():
    """The form tells an engineer how little of the month is blockable at
    all. That figure must be the same rule the optimiser uses."""
    section = _a_section()
    body = client.get(
        "/api/window", params={**SMALL, "section_id": section, "minutes": "60"}
    ).json()

    from src.api.app import _load, _parse_start

    start = _parse_start(None)
    grid = TimeGrid(horizon_start=start, horizon_days=3)
    series = traffic_by_slot(_load(False, 8, 3, 1, start), grid)[section]
    permitted = permitted_slots(series, DEFAULT_PERCENTILE)
    assert abs(body["permitted_share"] - sum(permitted) / len(permitted)) < 0.002


def test_filing_a_report_requires_a_signed_in_caller():
    """Anonymous intake would let anyone put work in front of the head."""
    assert client.get("/api/reports").status_code == 401
    assert client.post("/api/reports", json={
        "section_id": "X", "activity_type": "y", "summary": "z",
        "department": "ENGG",
    }).status_code == 401
    assert client.patch(
        "/api/reports/whatever", json={"status": "accepted"}
    ).status_code == 401


def test_a_report_lists_everyone_who_must_attend_owner_first():
    """The co-location signal. Order matters — the owner does the work — and
    a department named twice must not be counted twice."""
    report = Report(
        section_id="NDLS-CSB", activity_type="through_packing",
        summary="Cracked fishplate", department="ENGG",
        concerns=["TRD", "ENGG", "S&T"],
    )
    assert report.departments == ["ENGG", "TRD", "S&T"]


def test_a_new_report_is_nobody_decision_yet():
    report = Report(
        section_id="NDLS-CSB", activity_type="through_packing",
        summary="Cracked fishplate", department="ENGG",
    )
    assert report.status is ReportStatus.OPEN
    assert report.decided_by == ""
    assert report.id  # filing twice must not collide


def _a_section() -> str:
    return client.get("/api/plan", params={**SMALL, "time_limit": "3"}).json()[
        "sections"
    ].popitem()[0]


def test_a_window_that_has_already_passed_is_never_offered():
    """People file reports in the middle of the month they are planning.

    Without this the honest-looking answer to "when is the soonest?" was a
    date last week.
    """
    section = _a_section()
    common = {**SMALL, "section_id": section, "minutes": "60"}
    full = client.get("/api/window", params=common).json()
    assert full["earliest"] is not None

    cut = full["candidates"][-1]["start"]
    later = client.get("/api/window", params={**common, "not_before": cut}).json()
    assert all(c["start"] >= cut for c in later["candidates"])
    assert later["earliest"]["start"] >= cut


def test_a_finished_month_says_so_rather_than_claiming_the_job_will_not_fit():
    """Two different facts, and an engineer needs different words for each."""
    section = _a_section()
    over = client.get("/api/window", params={
        **SMALL, "section_id": section, "minutes": "60",
        "not_before": "2099-01-01T00:00:00",
    }).json()
    assert over["candidates"] == []
    assert over["earliest"] is None
    assert over["horizon_over"] is True

    too_long = client.get("/api/window", params={
        **SMALL, "section_id": section, "minutes": "4320",
    }).json()
    assert too_long["candidates"] == []
    assert too_long["horizon_over"] is False


# ── the traffic case behind a closure ───────────────────────────────────
#
# "Why 01:15?" is the question a divisional officer actually asks, and
# "the optimiser said so" is not an answer. These check the figures the
# explanation panel puts on screen are the same ones the optimiser used.


def test_the_threshold_shown_is_the_one_the_optimiser_applied():
    """If the panel quoted a different rule from the model, the explanation
    would be a story rather than a reason."""
    section = _a_section()
    body = client.get(
        "/api/traffic", params={**SMALL, "section_id": section}
    ).json()

    from src.api.app import _load, _parse_start
    from src.optimiser.windows import percentile

    start = _parse_start(None)
    grid = TimeGrid(horizon_start=start, horizon_days=3)
    series = traffic_by_slot(_load(False, 8, 3, 1, start), grid)[section]
    assert abs(body["threshold"] - percentile(series, DEFAULT_PERCENTILE)) < 0.01
    assert body["percentile"] == DEFAULT_PERCENTILE


def test_every_blockable_hour_is_at_or_under_the_threshold():
    section = _a_section()
    body = client.get(
        "/api/traffic", params={**SMALL, "section_id": section}
    ).json()
    for hour in body["blockable_hours"]:
        assert body["profile"][hour] <= body["threshold"] + 1e-9
    for hour, value in enumerate(body["profile"]):
        if value > body["threshold"]:
            assert hour not in body["blockable_hours"]


def test_the_counterfactual_is_never_cheaper_than_the_chosen_window():
    """The panel claims the same closure in the busiest hour would cost more.

    If that were ever false the claim would be backwards, so it is asserted
    rather than assumed.
    """
    plan = client.get("/api/plan", params={**SMALL, "time_limit": "3"}).json()
    for block in plan["blocks"][:8]:
        body = client.get("/api/traffic", params={
            **SMALL, "section_id": block["section_id"],
            "start": block["start"], "end": block["end"],
        }).json()
        window = body["window"]
        assert window["at_peak_train_hours"] >= window["train_hours"] - 1e-6


def test_a_closure_with_no_window_asked_for_returns_no_window():
    section = _a_section()
    body = client.get("/api/traffic", params={**SMALL, "section_id": section}).json()
    assert body["window"] == {}


def test_traffic_for_an_unknown_section_is_a_404():
    assert client.get(
        "/api/traffic", params={**SMALL, "section_id": "NOWHERE-AT-ALL"}
    ).status_code == 404
