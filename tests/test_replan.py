"""Scenario re-planning."""

from __future__ import annotations

from src.models import Department
from src.optimiser.model import BlockPlanner
from src.optimiser.replan import Disruption, replan_after
from tests.test_optimiser_constraints import NIGHT_SPARSE, build_instance, task


def _instance():
    return build_instance(
        {"S1": NIGHT_SPARSE, "S2": NIGHT_SPARSE},
        [task(f"T{i}", "S1" if i % 2 else "S2", 60, dept=list(Department)[i % 3])
         for i in range(8)],
        horizon_days=6,
    )


def test_completed_work_is_not_replanned():
    instance = _instance()
    original = BlockPlanner(instance, time_limit=15).solve()
    grid = BlockPlanner(instance, time_limit=1).grid
    at = 3 * grid.slots_per_day
    result = replan_after(instance, original, Disruption(at, "S1", 8), time_limit=15)

    assert set(result.completed_task_ids).isdisjoint(result.carried_task_ids)
    replanned_ids = {t for b in result.replanned.blocks for t in b.task_ids}
    assert replanned_ids.isdisjoint(result.completed_task_ids)


def test_unscheduled_work_is_carried_forward():
    """Work the first plan could not place must not be quietly forgotten."""
    instance = _instance()
    original = BlockPlanner(instance, time_limit=15).solve()
    result = replan_after(instance, original, Disruption(0, "S1", 4), time_limit=15)
    for task_id in original.unscheduled_task_ids:
        assert task_id in result.carried_task_ids


def test_disrupted_section_is_avoided_during_the_overrun():
    instance = _instance()
    original = BlockPlanner(instance, time_limit=15).solve()
    grid = BlockPlanner(instance, time_limit=1).grid
    at = 2 * grid.slots_per_day
    overrun = 12
    result = replan_after(instance, original, Disruption(at, "S1", overrun), time_limit=15)
    for block in result.replanned.blocks:
        if block.section_id != "S1":
            continue
        assert not (block.start_slot < at + overrun and at < block.end_slot)


def test_replan_reports_its_own_delta():
    instance = _instance()
    original = BlockPlanner(instance, time_limit=15).solve()
    result = replan_after(instance, original, Disruption(96, "S1", 8), time_limit=15)
    assert isinstance(result.train_hours_delta, float)
    assert "train-hours" in result.summary()


# ── the API surface ─────────────────────────────────────────────────────

from fastapi.testclient import TestClient  # noqa: E402

from src.api.app import app  # noqa: E402

_client = TestClient(app)
_SMALL = {"grounded": "false", "tasks": "20", "days": "5", "seed": "3",
          "time_limit": "4"}


def _a_block() -> dict:
    blocks = _client.get("/api/plan", params=_SMALL).json()["blocks"]
    return sorted(blocks, key=lambda b: b["start"])[len(blocks) // 2]


def test_replanning_keeps_finished_work_and_carries_the_rest():
    block = _a_block()
    body = _client.post("/api/replan", params=_SMALL, json={
        "section_id": block["section_id"], "at": block["start"],
        "overrun_minutes": 120,
    }).json()
    assert body["completed"] > 0, "a mid-horizon disruption leaves work behind it"
    assert body["carried"] > 0
    assert body["blocks_after"] >= 0


def test_the_disruption_is_measured_against_a_like_for_like_control():
    """The delta must be against the same work re-solved with nothing wrong.

    Comparing against the original month-long plan credits the disruption
    with the benefit of a second, smaller solve — measured at -32.5
    train-hours on a real instance for a disruption that cannot have helped.
    """
    block = _a_block()
    body = _client.post("/api/replan", params=_SMALL, json={
        "section_id": block["section_id"], "at": block["start"],
        "overrun_minutes": 120,
    }).json()
    expected = round(body["train_hours_after"] - body["train_hours_control"], 2)
    assert abs(body["delta"] - expected) < 0.05
    # The naive figure is still reported, so the difference can be shown
    # rather than quietly corrected.
    naive = round(body["train_hours_after"] - body["train_hours_before"], 2)
    assert abs(body["delta_vs_original"] - naive) < 0.05


def test_removing_hours_from_a_section_never_helps_it():
    """Sanity on the direction: taking a section out for longer cannot make
    the remaining month cheaper than the same month with it available."""
    block = _a_block()
    body = _client.post("/api/replan", params=_SMALL, json={
        "section_id": block["section_id"], "at": block["start"],
        "overrun_minutes": 240,
    }).json()
    assert body["train_hours_after"] >= body["train_hours_control"] - 0.5


def test_a_disruption_outside_the_horizon_is_rejected():
    block = _a_block()
    assert _client.post("/api/replan", params=_SMALL, json={
        "section_id": block["section_id"], "at": "2099-01-01T00:00:00",
    }).status_code == 400


def test_replan_rejects_an_unknown_section_and_a_zero_overrun():
    block = _a_block()
    assert _client.post("/api/replan", params=_SMALL, json={
        "section_id": "NOWHERE-AT-ALL", "at": block["start"],
    }).status_code == 404
    assert _client.post("/api/replan", params=_SMALL, json={
        "section_id": block["section_id"], "at": block["start"],
        "overrun_minutes": 0,
    }).status_code == 400
