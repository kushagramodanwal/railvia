"""API smoke tests.

Kept small and fast: these check the contract the front end depends on, not
schedule quality, which the optimiser tests cover.
"""

from __future__ import annotations

import pathlib

import pytest
from fastapi.testclient import TestClient

from src.api.app import app

client = TestClient(app)
SMALL = {"grounded": "false", "tasks": "8", "days": "3", "seed": "1"}


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_instance_reports_per_component_provenance():
    body = client.get("/api/instance", params=SMALL).json()
    assert set(body["sources"]) == {"sections", "tasks", "traffic", "crew_capacity"}
    assert body["is_synthetic"] is True
    assert body["sections"]
    assert len(body["sections"][0]["profile"]) == 24


def test_plan_returns_blocks_with_task_detail():
    body = client.get("/api/plan", params={**SMALL, "time_limit": "5"}).json()
    assert body["status"] in ("OPTIMAL", "FEASIBLE")
    for block in body["blocks"]:
        assert block["tasks"]
        assert block["end"] > block["start"]
        assert set(block["tasks"][0]) >= {"id", "activity", "department", "severity"}
        # The saving from merging is what a planner actually acts on.
        assert block["saving"] >= 0
        assert block["separate_cost"] >= block["train_hours"] - 1e-6


def test_every_unscheduled_job_carries_a_reason_and_a_fix():
    """A planner needs to know why a job missed the plan, not just that it did."""
    body = client.get("/api/plan", params={**SMALL, "time_limit": "5"}).json()
    assert len(body["exceptions"]) == len(body["unscheduled"])
    for exc in body["exceptions"]:
        assert exc["reason"] and exc["fix"]
        assert exc["id"] in body["unscheduled"]


def test_shared_blocks_report_a_real_saving():
    body = client.get(
        "/api/plan",
        params={**SMALL, "tasks": "40", "days": "7", "time_limit": "8"},
    ).json()
    for block in body["blocks"]:
        if len(block["tasks"]) > 1:
            assert block["separate_cost"] >= block["train_hours"]


def test_criticality_exposes_importances_and_ranking():
    body = client.get("/api/criticality", params=SMALL).json()
    assert body["importances"]
    assert 0.0 < body["auc"] < 1.0
    assert body["top_tasks"]
    scores = [t["score"] for t in body["top_tasks"]]
    assert scores == sorted(scores, reverse=True)


def test_single_task_explanation():
    ranked = client.get("/api/criticality", params=SMALL).json()["top_tasks"]
    task_id = ranked[0]["id"]
    body = client.get(f"/api/criticality/{task_id}", params=SMALL).json()
    assert body["task_id"] == task_id
    assert body["contributions"]


def test_unknown_task_is_404():
    assert client.get("/api/criticality/NOPE", params=SMALL).status_code == 404


def test_comparison_contract():
    body = client.get("/api/comparison", params={**SMALL, "time_limit": "5"}).json()
    metrics = {row["metric"] for row in body["rows"]}
    assert "Train-hours lost" in metrics
    assert "Blocks shared across departments" in metrics
    assert "horizon_start" in body  # the baseline Gantt needs it to render
    assert isinstance(body["headline_reduction_pct"], float)


def test_root_serves_the_ui_when_built_and_404s_otherwise():
    """This service serves the API always, and the UI once it is built.

    It used to be JSON-only, with the UI deployed separately. Serving both
    from one process is what makes the deployment a single Render service.
    """
    from src.api.app import UI_DIR

    assert client.get("/api/health").json() == {"status": "ok"}
    root = client.get("/")
    if UI_DIR.is_dir():
        assert root.status_code == 200
        assert "RailVia" in root.text
    else:
        assert root.status_code == 404


def test_cors_allows_the_next_dev_origin():
    """The browser calls this service directly — Next's dev proxy drops the
    socket on a 60-second solve."""
    res = client.get("/api/health", headers={"Origin": "http://localhost:3000"})
    assert res.headers.get("access-control-allow-origin") == "http://localhost:3000"


# --- decisions: approvals and completions ----------------------------------


def test_store_status_is_reported_honestly():
    """The UI must be able to say plainly whether decisions can be recorded."""
    body = client.get("/api/store").json()
    assert body["backend"] == "Supabase"
    assert isinstance(body["connected"], bool)
    assert body["detail"]


def test_decisions_require_a_signed_in_caller():
    """Every decision endpoint refuses an anonymous request.

    401 rather than 503: the store may be perfectly healthy — we simply do
    not know who is asking, and a decision has to be attributable.
    """
    payload = {"instance_id": "x", "section_id": "A-B", "start_iso": "2026-03-02T00:00:00"}
    assert client.post("/api/approvals", json=payload).status_code == 401
    assert client.post(
        "/api/completions", json={"instance_id": "x", "task_id": "T1"}
    ).status_code == 401
    assert client.get("/api/decisions", params={"instance_id": "x"}).status_code == 401
    assert client.get("/api/me").status_code == 401
    assert client.delete(
        "/api/approvals",
        params={"instance_id": "x", "section_id": "A", "start_iso": "t"},
    ).status_code == 401


def test_a_forged_token_is_rejected():
    """A token we cannot verify is no better than no token."""
    res = client.get("/api/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert res.status_code == 401


def test_planning_stays_open():
    """The plan is derived from a public timetable and simulated jobs, so it
    is not access-controlled here. Decisions are."""
    body = client.get("/api/plan", params={**SMALL, "time_limit": "5"})
    assert body.status_code == 200


def test_plan_exposes_instance_id_for_keying_decisions():
    body = client.get("/api/plan", params={**SMALL, "time_limit": "5"}).json()
    assert body["instance_id"]


def test_importing_the_api_loads_the_environment():
    """Token verification reads SUPABASE_URL to find the project's JWKS, and
    it runs before any store call.

    Regression: the environment was loaded lazily inside the store, so
    whether sign-in worked depended on the order the front end happened to
    make its requests — /api/store first and it worked, /api/me first and the
    role came back unknown.
    """
    import importlib
    import os

    saved = {k: os.environ.pop(k, None) for k in ("SUPABASE_URL", "SUPABASE_KEY")}
    try:
        import src.api.app as app_module

        importlib.reload(app_module)
        from src.store.auth import jwks_url

        # Present in .env, so importing the API must be enough to see it.
        if pathlib.Path(".env").exists():
            assert os.environ.get("SUPABASE_URL"), "import did not load .env"
            assert jwks_url()
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


# --- choosing the period ---------------------------------------------------


def test_horizon_start_is_honoured():
    """The month picker sends the first of a month; the plan must start there."""
    for start, days in [("2026-09-01", 30), ("2026-02-01", 28)]:
        body = client.get("/api/plan", params={
            **SMALL, "days": days, "time_limit": "4", "horizon_start": start,
        }).json()
        assert body["horizon_start"] == start
        assert body["horizon_days"] == days


def test_horizon_start_defaults_to_a_monday():
    body = client.get("/api/plan", params={**SMALL, "time_limit": "4"}).json()
    from datetime import date

    assert date.fromisoformat(body["horizon_start"]).weekday() == 0


def test_bad_horizon_start_is_a_400_not_a_500():
    res = client.get("/api/plan", params={**SMALL, "horizon_start": "not-a-date"})
    assert res.status_code == 400
    assert "ISO date" in res.json()["detail"]


def test_different_months_get_different_plans():
    """Regression: the disk cache key must include the horizon, or one month
    is served another month's plan with silently wrong dates."""
    a = client.get("/api/plan", params={
        **SMALL, "days": 28, "time_limit": "4", "horizon_start": "2026-09-01"}).json()
    b = client.get("/api/plan", params={
        **SMALL, "days": 28, "time_limit": "4", "horizon_start": "2026-10-01"}).json()
    assert a["horizon_start"] != b["horizon_start"]
    if a["blocks"] and b["blocks"]:
        assert a["blocks"][0]["start"][:7] != b["blocks"][0]["start"][:7]


# --- deployment ------------------------------------------------------------


def test_deployed_origins_come_from_the_environment(monkeypatch):
    """A deployment's own origin is configured, not hardcoded."""
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://railvia.onrender.com,https://x.dev/")
    from src.api.app import allowed_origins

    origins = allowed_origins()
    assert "https://railvia.onrender.com" in origins
    assert "https://x.dev" in origins          # trailing slash stripped
    assert "http://localhost:3000" in origins  # local dev still works


def test_cors_is_never_a_wildcard(monkeypatch):
    """The API accepts a bearer token. A wildcard origin would let any site
    make authenticated calls with a token it had somehow obtained."""
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    from src.api.app import allowed_origins

    assert "*" not in allowed_origins()


def test_ui_and_api_coexist_on_one_origin():
    """In production FastAPI serves the built UI as well as the API.

    The mount is at "/", so it must not shadow the API routes — Starlette
    matches in registration order, which is why the mount is added last.
    """
    from src.api.app import UI_DIR

    assert client.get("/api/health").json() == {"status": "ok"}
    if not UI_DIR.is_dir():
        pytest.skip("UI not built; run STATIC_EXPORT=1 npm --prefix web run build")
    for route in ("/", "/plan/", "/approved/", "/completed/"):
        page = client.get(route)
        assert page.status_code == 200, route
        assert "RailVia" in page.text


def test_server_falls_back_to_the_public_supabase_variables(monkeypatch):
    """Setting the same values twice is a trap, so the server accepts the
    NEXT_PUBLIC_ names too.

    Next only exposes NEXT_PUBLIC_-prefixed variables to browser code, so the
    front end must have its own copy. Setting only that pair made sign-in
    work while every approval failed — the confusing half-configured state.
    """
    from src.store.supabase_store import configured_key, configured_url

    for name in ("SUPABASE_URL", "SUPABASE_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "anon-key")

    assert configured_url() == "https://proj.supabase.co"
    assert configured_key() == "anon-key"


def test_explicit_server_key_wins_over_the_public_one(monkeypatch):
    """A deployment using a service key must not be overridden by the anon
    key the browser uses."""
    from src.store.supabase_store import configured_key

    monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.setenv("SUPABASE_KEY", "service-key")
    assert configured_key() == "service-key"


# --- the network map and closure impact -----------------------------------


def test_network_returns_geometry_with_real_coordinates():
    body = client.get("/api/network").json()
    assert body["stations"] and body["sections"]
    for code, station in body["stations"].items():
        assert station["name"]
        # Every station carries real coordinates from the timetable feed;
        # a missing one would silently collapse to the map's origin.
        assert station["lat"] is not None, f"{code} has no latitude"
        assert station["lng"] is not None, f"{code} has no longitude"
        assert 6 < station["lat"] < 38, f"{code} is outside India"
        assert 68 < station["lng"] < 98, f"{code} is outside India"


def test_network_sections_reference_known_stations():
    """A section pointing at a station the map has no position for draws a
    line to nowhere."""
    body = client.get("/api/network").json()
    known = set(body["stations"])
    for section in body["sections"]:
        assert section["a"] in known, section["id"]
        assert section["b"] in known, section["id"]


def test_impact_lists_the_trains_a_closure_stops():
    body = client.get("/api/impact", params={
        "section_id": "SBB-GZB",
        "start": "2026-08-31T03:45:00", "end": "2026-08-31T06:00:00",
    }).json()
    assert body["affected_count"] == len(body["trains"])
    assert body["trains"], "the busiest section should stop somebody"
    for train in body["trains"]:
        assert train["number"] and train["name"]
        # Every train must fall inside the window it is reported for.
        assert body["start"][:10] <= train["at"][:10]


def test_impact_window_actually_filters():
    """A wider closure must stop at least as many trains as a narrow one."""
    narrow = client.get("/api/impact", params={
        "section_id": "SBB-GZB",
        "start": "2026-08-31T03:00:00", "end": "2026-08-31T03:30:00"}).json()
    wide = client.get("/api/impact", params={
        "section_id": "SBB-GZB",
        "start": "2026-08-31T03:00:00", "end": "2026-08-31T07:00:00"}).json()
    assert wide["affected_count"] >= narrow["affected_count"]
    assert wide["affected_count"] > 0


def test_impact_rejects_an_unknown_section():
    res = client.get("/api/impact", params={
        "section_id": "NOWHERE", "start": "2026-08-31T00:00:00",
        "end": "2026-08-31T04:00:00"})
    assert res.status_code == 404


def test_impact_rejects_a_bad_timestamp():
    res = client.get("/api/impact", params={
        "section_id": "SBB-GZB", "start": "not-a-time",
        "end": "2026-08-31T04:00:00"})
    assert res.status_code == 400
