"""FastAPI backend — a pure JSON API.

The front end is a separate Next.js app in `web/`, which calls this service
directly (see the CORS note below). There is no server-rendered UI here.

Solving is expensive (up to 60 seconds), so results are computed once per
distinct request and cached in-process. A demo must not re-solve on every
click, and the front end polls nothing.
"""

from __future__ import annotations

import contextlib
import functools
import logging
import os
import pathlib
import threading

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.api import cache
from src.adapters import GroundedTimetableSource, SyntheticDataSource
from src.ingest.railradar import load_dotenv
from src.baseline.compare import run_comparison
from src.ml.criticality import CriticalityModel
from datetime import date, datetime

from src.models import CATALOGUE, PlanningInstance, next_monday
from src.optimiser.model import BlockPlanner
from src.optimiser.replan import Disruption, replan_after
from src.optimiser.windows import (
    DEFAULT_PERCENTILE, TimeGrid, feasible_starts, percentile, permitted_slots,
    traffic_by_slot,
)
from src.store import (
    Approval, AuthError, Caller, Completion, Report, ReportStatus, bearer,
    store_for, store_status, verify,
)

log = logging.getLogger(__name__)

# Load .env once, at import, rather than lazily inside whichever call happens
# to run first. Token verification reads SUPABASE_URL to find the project's
# JWKS endpoint, and it runs BEFORE any store call — so relying on the store
# to load the environment made sign-in work or fail depending on the order
# the front end happened to make its requests.
load_dotenv()


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    """Solve the default view in the background at boot.

    Without this the first person to open the app waits for a cold solve.
    Daemon thread, so it never holds up shutdown.
    """

    def warm() -> None:
        try:
            today = date.today()
            plan(grounded=True, tasks=120,
                 days=(date(today.year + (today.month == 12),
                            (today.month % 12) + 1, 1) - date(today.year, today.month, 1)).days,
                 seed=42, time_limit=DEFAULT_UI_BUDGET,
                 horizon_start=date(today.year, today.month, 1).isoformat())
            log.info("warm cache ready for the default view")
        except Exception as exc:  # noqa: BLE001
            log.warning("cache warming failed: %s", exc)

    threading.Thread(target=warm, daemon=True, name="warm-cache").start()
    yield


app = FastAPI(
    title="Automatic Block Planning (SIH26027)",
    description=(
        "Coordinated maintenance block scheduling. Traffic data is real "
        "(published Indian Railways timetable); maintenance tasks are synthetic."
    ),
    version="0.6.0",
    lifespan=lifespan,
)


# The Next.js front end calls this service directly rather than through the
# dev-server proxy: a solve can take 60 seconds and Next's rewrite proxy hangs
# the socket up long before that (ECONNRESET). Two origins plus CORS is the
# ordinary shape for a SPA over a separate API, and it removes the proxy as a
# failure point during a demo.
# 10 seconds, not 30. Measured on the 120-task instance: 10s gives 237
# train-hours against 280 at 30s — the extra 20 seconds wanders and finds
# nothing better, because the search is not monotone under a time limit. The
# warm start does most of the work in milliseconds; the solver refines it.
DEFAULT_UI_BUDGET = float(os.environ.get("SOLVER_TIME_LIMIT", "10"))

# Whether this process may build and run the CP-SAT model at all.
#
# A month-long instance needs 700 MB to 1.9 GB to solve — measured — against
# 512 MB on a small cloud plan, so a container is killed mid-request. Plans
# are therefore solved once at image-build time (scripts/precompute.py) and
# served from the cache; when something is missed, the greedy schedule is
# built instead, which costs 147 MB and still returns a real plan.
ALLOW_RUNTIME_SOLVE = os.environ.get("ALLOW_RUNTIME_SOLVE", "1") != "0"

LOCAL_ORIGINS = [
    "http://localhost:3000", "http://127.0.0.1:3000",
    "http://localhost:3001", "http://127.0.0.1:3001",
]


def allowed_origins() -> list[str]:
    """Origins permitted to call this API.

    Local development origins are always allowed; a deployment adds its own
    through ALLOWED_ORIGINS (comma-separated). Deliberately not "*": the API
    accepts a bearer token, and a wildcard would let any site on the internet
    make authenticated calls with a token it had somehow obtained.
    """
    extra = [
        o.strip().rstrip("/")
        for o in os.environ.get("ALLOWED_ORIGINS", "").split(",")
        if o.strip()
    ]
    return LOCAL_ORIGINS + extra


app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


def _parse_start(value: str | None) -> date:
    """The first day of the planning horizon.

    Defaults to the Monday of the coming week. A caller may name any date —
    the month picker sends the first of a month.
    """
    if not value:
        return next_monday()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"horizon_start must be an ISO date (YYYY-MM-DD), got {value!r}",
        ) from exc


@functools.lru_cache(maxsize=16)
def _load(
    grounded: bool, tasks: int, days: int, seed: int, start: date
) -> PlanningInstance:
    source = (
        GroundedTimetableSource(seed=seed, n_tasks=tasks, horizon_days=days,
                                horizon_start=start)
        if grounded
        else SyntheticDataSource(seed=seed, n_tasks=tasks, horizon_days=days,
                                 horizon_start=start)
    )
    return source.load()


@functools.lru_cache(maxsize=8)
def _criticality(grounded: bool, tasks: int, days: int, seed: int, start: date):
    instance = _load(grounded, tasks, days, seed, start)
    model = CriticalityModel()
    report = model.train(instance.sections)
    return model, report, model.score_instance(instance)


@functools.lru_cache(maxsize=4)
def _comparison(grounded: bool, tasks: int, days: int, seed: int,
                time_limit: float, start: date):
    instance = _load(grounded, tasks, days, seed, start)
    _, _, scores = _criticality(grounded, tasks, days, seed, start)
    return run_comparison(instance, time_limit=time_limit, criticality=scores)


def _separate_cost(block, planner, tasks_by_id) -> float:
    """What this block's work would cost as separate single-job closures.

    The saving from merging is the number a planner actually cares about, and
    it is not visible anywhere in the raw plan. Each job is priced on its own
    at the same start time, which is what the manual process would produce.
    """
    series = planner.traffic.get(block.section_id)
    if not series:
        return 0.0
    total = 0.0
    for task_id in block.task_ids:
        task = tasks_by_id[task_id]
        length = planner.grid.minutes_to_slots(task.duration_minutes)
        stop = min(block.start_slot + length, len(series))
        total += sum(series[s] for s in range(block.start_slot, stop)) * planner.grid.slot_hours
    return round(total, 2)


def _block_payload(block, grid: TimeGrid, tasks_by_id: dict) -> dict:
    return {
        "section_id": block.section_id,
        "start": grid.to_datetime(block.start_slot).isoformat(),
        "end": grid.to_datetime(block.end_slot).isoformat(),
        "hours": round((block.end_slot - block.start_slot) * grid.slot_minutes / 60, 2),
        "train_hours": block.train_hours,
        "departments": [d.value for d in block.departments],
        "shared": block.is_shared,
        "tasks": [
            {
                "id": tid,
                "activity": tasks_by_id[tid].activity_type,
                "department": tasks_by_id[tid].department.value,
                "severity": tasks_by_id[tid].defect_severity.value,
                "overdue": tasks_by_id[tid].is_overdue,
            }
            for tid in block.task_ids
        ],
    }


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:
    """Return the reason, not a bare 500.

    An unhandled error reached the browser as an opaque failure, leaving the
    only diagnosis in server logs. The message goes in the response so it is
    visible where the problem is noticed.
    """
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": f"{type(exc).__name__}: {exc}",
            "path": request.url.path,
        },
    )


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/instance")
def instance_summary(
    grounded: bool = True, tasks: int = 120, days: int = 7, seed: int = 42,
    horizon_start: str | None = None,
) -> dict:
    instance = _load(grounded, tasks, days, seed, _parse_start(horizon_start))
    return {
        "instance_id": instance.instance_id,
        "horizon_start": instance.horizon_start.isoformat(),
        "horizon_days": instance.horizon_days,
        "is_synthetic": instance.is_synthetic,
        "provenance": instance.provenance,
        "sources": {k: v.value for k, v in instance.sources.components.items()},
        "sections": [
            {
                "id": s.id, "name": s.name, "length_km": s.length_km,
                "daily_trains": s.daily_trains,
                "peak_trains_per_hour": s.peak_trains_per_hour,
                "profile": s.traffic_density_profile,
            }
            for s in instance.sections
        ],
        "task_count": len(instance.tasks),
        "overdue_count": sum(1 for t in instance.tasks if t.is_overdue),
    }


@functools.lru_cache(maxsize=4)
def _cheap_plan(grounded: bool, tasks: int, days: int, seed: int,
                percentile: float, start: date):
    """A planner that never builds the CP-SAT model.

    Same windows and traffic, no solver — for hosts that cannot hold the
    model in memory.
    """
    instance = _load(grounded, tasks, days, seed, start)
    _, _, scores = _criticality(grounded, tasks, days, seed, start)
    planner = BlockPlanner(
        instance, percentile=percentile, criticality=scores, build_model=False
    )
    return instance, planner, scores


@functools.lru_cache(maxsize=8)
def _plan(grounded: bool, tasks: int, days: int, seed: int, time_limit: float,
          percentile: float, start: date):
    instance = _load(grounded, tasks, days, seed, start)
    _, _, scores = _criticality(grounded, tasks, days, seed, start)
    planner = BlockPlanner(
        instance, time_limit=time_limit, percentile=percentile, criticality=scores
    )
    return instance, planner, planner.solve(), scores


@app.get("/api/plan")
def plan(
    grounded: bool = True, tasks: int = 120, days: int = 7,
    seed: int = 42, time_limit: float = DEFAULT_UI_BUDGET,
    percentile: float = 25.0, horizon_start: str | None = None,
) -> dict:
    # The horizon is chosen by the caller and defaults to the coming Monday,
    # so it MUST be part of the key. Without it a different month would be
    # served this one's plan from disk — silently wrong dates, which is worse
    # than a slow solve.
    start = _parse_start(horizon_start)
    cache_key = cache.key(
        grounded=grounded, tasks=tasks, days=days, seed=seed,
        time_limit=time_limit, percentile=percentile,
        horizon_start=start.isoformat(),
    )
    cached = cache.load(cache_key)
    if cached is not None:
        return cached

    if ALLOW_RUNTIME_SOLVE:
        instance, planner, solution, scores = _plan(
            grounded, tasks, days, seed, time_limit, percentile, start
        )
    else:
        # Not enough memory here to hold the model. Build the greedy schedule
        # instead of being OOM-killed, and label it so nobody mistakes it for
        # an optimised plan.
        instance, planner, scores = _cheap_plan(
            grounded, tasks, days, seed, percentile, start
        )
        solution = planner.greedy_only()
        log.info("runtime solving disabled; served a greedy plan for %s", start)
    tasks_by_id = {t.id: t for t in instance.tasks}

    blocks = []
    for block in solution.blocks:
        payload = _block_payload(block, planner.grid, tasks_by_id)
        alone = _separate_cost(block, planner, tasks_by_id)
        payload["separate_cost"] = alone
        payload["saving"] = round(max(0.0, alone - block.train_hours), 2)
        payload["overdue_count"] = sum(
            1 for t in block.task_ids if tasks_by_id[t].is_overdue
        )
        blocks.append(payload)

    # Why each job missed the plan. A planner needs the reason, not the fact.
    exceptions = []
    for task_id in solution.unscheduled_task_ids:
        task = tasks_by_id[task_id]
        if task_id in solution.impossible_task_ids:
            reason = "no quiet window long enough on this section"
            fix = "shorten the job, split it, or widen the permitted hours"
        elif task.crew_required > planner.crew_ceiling.get(task.department, 99):
            reason = f"needs {task.crew_required} crews; department never has that many"
            fix = "borrow crew or split the job"
        else:
            reason = "deferred — crew and quiet windows went to more critical work"
            fix = "extend the horizon, or raise this job's priority"
        exceptions.append({
            "id": task_id, "section": task.section_id,
            "activity": task.activity_type, "department": task.department.value,
            "severity": task.defect_severity.value, "overdue": task.is_overdue,
            "due": task.due_date.isoformat(),
            "criticality": round(scores.get(task_id, 0.0), 3),
            "reason": reason, "fix": fix,
        })
    exceptions.sort(key=lambda e: (-e["criticality"], e["due"]))

    payload = {
        "instance_id": instance.instance_id,
        "status": solution.status,
        "wall_time": round(solution.wall_time, 2),
        "train_hours_lost": solution.train_hours_lost,
        "blocks": blocks,
        "block_count": len(solution.blocks),
        "scheduled": solution.scheduled_count,
        "task_total": len(instance.tasks),
        "shared_blocks": solution.shared_blocks,
        "unscheduled": solution.unscheduled_task_ids,
        "exceptions": exceptions,
        "late_tasks": solution.late_task_count,
        "total_saving": round(sum(b["saving"] for b in blocks), 1),
        "horizon_start": instance.horizon_start.isoformat(),
        "horizon_days": instance.horizon_days,
        "sections": {s.id: s.name for s in instance.sections},
    }
    # Only a solved plan is worth keeping.
    #
    # The fallback path produces a constructive schedule and labels it
    # "+GREEDY". Storing that wrote an inferior plan to disk permanently: the
    # deployed image has runtime solving off, so any month nobody precomputed
    # got a greedy plan cached forever, and the month picker lets a visitor
    # reach any month. Recomputing the greedy costs milliseconds; serving a
    # greedy plan for the rest of the deployment's life does not.
    if "GREEDY" not in solution.status:
        cache.store(cache_key, payload)
    return payload


@app.get("/api/comparison")
def comparison(
    grounded: bool = True, tasks: int = 120, days: int = 7,
    seed: int = 42, time_limit: float = DEFAULT_UI_BUDGET,
    horizon_start: str | None = None,
) -> dict:
    result = _comparison(grounded, tasks, days, seed, time_limit,
                         _parse_start(horizon_start))
    grid = TimeGrid(result.instance.horizon_start, result.instance.horizon_days, 15)
    tasks_by_id = {t.id: t for t in result.instance.tasks}
    return {
        "rows": [
            {"metric": m, "manual": a, "ours_same_work": b, "ours_full": c}
            for m, a, b, c in result.rows()
        ],
        "headline_reduction_pct": result.headline_reduction_pct,
        "block_reduction_pct": result.block_reduction_pct,
        "sections": len(result.instance.sections),
        "horizon_days": result.instance.horizon_days,
        "horizon_start": result.instance.horizon_start.isoformat(),
        "baseline_blocks": [
            _block_payload(b, grid, tasks_by_id) for b in result.baseline.blocks
        ],
        "extra_tasks_completed": (
            result.planned_full.scheduled_count - result.baseline.scheduled_count
        ),
    }


# ── the network, and what a closure actually costs ──────────────────────
#
# Station positions and the trains crossing each section come from the same
# cached timetable the traffic profiles do. The full set is 7,000+ traversals,
# far too much to send to a browser, so it is sliced per closure.


@functools.lru_cache(maxsize=1)
def _network() -> dict:
    import json

    path = pathlib.Path("data/grounded_sections.json")
    if not path.exists():
        raise HTTPException(
            status_code=503,
            detail="No timetable data. Run scripts/fetch_timetable.py first.",
        )
    return json.loads(path.read_text())


@app.get("/api/network")
def network() -> dict:
    """Geometry only — positions and section endpoints, no train lists."""
    data = _network()
    return {
        "stations": data["stations"],
        "sections": [
            {
                "id": s["id"], "a": s["station_a"], "b": s["station_b"],
                "name": s.get("name", s["id"]),
                "length_km": s.get("length_km"),
                "daily_trains": s.get("daily_trains", 0),
                "peak": max(s["traffic_density_profile"]) if s.get("traffic_density_profile") else 0,
            }
            for s in data["sections"]
        ],
        "corridors": data.get("corridors", []),
    }


@app.get("/api/impact")
def impact(section_id: str, start: str, end: str) -> dict:
    """Which trains a closure actually stops.

    A closure costs train-hours, which is an abstraction. These are the named
    services that would otherwise have run through that section in that
    window — the same trains the traffic profile was counted from.
    """
    from datetime import datetime

    try:
        begins = datetime.fromisoformat(start)
        finishes = datetime.fromisoformat(end)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"start and end must be ISO datetimes: {exc}"
        ) from exc

    data = _network()
    section = next(
        (s for s in data["sections"] if s["id"] == section_id), None
    )
    if section is None:
        raise HTTPException(status_code=404, detail=f"unknown section {section_id}")

    weekday = begins.weekday()
    first = begins.hour * 60 + begins.minute
    span = max(1, int((finishes - begins).total_seconds() // 60))

    affected = []
    for train in section.get("trains", []):
        if train["days"] and weekday not in train["days"]:
            continue
        # Minutes from the closure's start, wrapping past midnight.
        offset = (train["entry"] - first) % (24 * 60)
        if offset < span:
            affected.append({
                **train,
                "at": (begins + __import__("datetime").timedelta(minutes=offset))
                      .isoformat(timespec="minutes"),
            })
    affected.sort(key=lambda t: t["at"])

    return {
        "section_id": section_id,
        "section_name": section.get("name", section_id),
        "start": begins.isoformat(), "end": finishes.isoformat(),
        "affected_count": len(affected),
        "trains": affected,
    }


# ── decisions: approvals and completions ────────────────────────────────
#
# These are the only things this system persists. Everything else is
# reproducible from a seed and the cached timetable.


class ApprovalIn(BaseModel):
    instance_id: str
    section_id: str
    start_iso: str
    decided_by: str = "demo-planner"
    note: str = ""


class CompletionIn(BaseModel):
    instance_id: str
    task_id: str
    completed_by: str = "demo-planner"
    note: str = ""


def _caller(authorization: str | None) -> Caller:
    """Who is making this request. 401 if we cannot say."""
    try:
        return verify(bearer(authorization))
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _store_as(caller: Caller):
    """A store scoped to the caller, so Postgres RLS applies to them."""
    try:
        return store_for(caller)
    except Exception as exc:  # noqa: BLE001
        # 503, not 500: the request was fine, the store is not reachable.
        # Never silently record the decision somewhere else.
        raise HTTPException(
            status_code=503,
            detail=f"Decisions are stored in Supabase, which is not available. {exc}",
        ) from exc


def _forbidden(exc: Exception) -> HTTPException:
    """Translate an RLS refusal into something a person can act on.

    Postgres rejects the write; we do not re-check the role here, because two
    places deciding the same thing is two places to disagree.
    """
    text = str(exc)
    if "row-level security" in text or "42501" in text or "violates" in text:
        return HTTPException(
            status_code=403,
            detail="Only the divisional head can grant or withdraw a closure.",
        )
    return HTTPException(status_code=502, detail=f"Supabase rejected the write: {text}")


@app.get("/api/store")
def store_state() -> dict:
    return store_status()


@app.get("/api/me")
def me(authorization: str | None = Header(default=None)) -> dict:
    """Who is signed in, and what they are allowed to do."""
    caller = _caller(authorization)
    store = _store_as(caller)
    role = store.role() or "engineer"
    return {
        "user_id": caller.user_id,
        "email": caller.email,
        "role": role,
        "can_approve": role == "head",
        "can_complete": True,
    }


@app.get("/api/decisions")
def decisions(
    instance_id: str, authorization: str | None = Header(default=None)
) -> dict:
    store = _store_as(_caller(authorization))
    return {
        "approvals": [a.model_dump() for a in store.approvals(instance_id)],
        "completions": [c.model_dump() for c in store.completions(instance_id)],
    }


@app.post("/api/approvals")
def add_approval(
    body: ApprovalIn, authorization: str | None = Header(default=None)
) -> dict:
    caller = _caller(authorization)
    store = _store_as(caller)
    record = Approval(**{**body.model_dump(), "decided_by": caller.label})
    try:
        return store.approve(record).model_dump()
    except Exception as exc:  # noqa: BLE001
        raise _forbidden(exc) from exc


@app.delete("/api/approvals")
def remove_approval(
    instance_id: str, section_id: str, start_iso: str,
    authorization: str | None = Header(default=None),
) -> dict:
    store = _store_as(_caller(authorization))
    try:
        store.unapprove(instance_id, section_id, start_iso)
    except Exception as exc:  # noqa: BLE001
        raise _forbidden(exc) from exc
    return {"removed": True}


@app.post("/api/completions")
def add_completion(
    body: CompletionIn, authorization: str | None = Header(default=None)
) -> dict:
    caller = _caller(authorization)
    store = _store_as(caller)
    record = Completion(**{**body.model_dump(), "completed_by": caller.label})
    try:
        return store.complete(record).model_dump()
    except Exception as exc:  # noqa: BLE001
        raise _forbidden(exc) from exc


@app.delete("/api/completions")
def remove_completion(
    instance_id: str, task_id: str,
    authorization: str | None = Header(default=None),
) -> dict:
    store = _store_as(_caller(authorization))
    try:
        store.uncomplete(instance_id, task_id)
    except Exception as exc:  # noqa: BLE001
        raise _forbidden(exc) from exc
    return {"removed": True}


@app.get("/api/criticality")
def criticality(
    grounded: bool = True, tasks: int = 120, days: int = 7, seed: int = 42,
    horizon_start: str | None = None,
) -> dict:
    start = _parse_start(horizon_start)
    model, report, scores = _criticality(grounded, tasks, days, seed, start)
    instance = _load(grounded, tasks, days, seed, start)
    tasks_by_id = {t.id: t for t in instance.tasks}
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    return {
        "backend": model.backend,
        "auc": round(report.auc, 3),
        "log_loss": round(report.log_loss, 3),
        "records": report.n_records,
        "failure_rate": round(report.failure_rate, 4),
        "importances": [
            {"feature": name, "gain": float(value)} for name, value in report.importances
        ],
        "top_tasks": [
            {
                "id": tid, "score": round(score, 4),
                "activity": tasks_by_id[tid].activity_type,
                "department": tasks_by_id[tid].department.value,
                "section": tasks_by_id[tid].section_id,
                "severity": tasks_by_id[tid].defect_severity.value,
                "overdue": tasks_by_id[tid].is_overdue,
            }
            for tid, score in ranked[:25]
        ],
    }


@app.get("/api/criticality/{task_id}")
def explain_task(
    task_id: str, grounded: bool = True, tasks: int = 120,
    days: int = 7, seed: int = 42, horizon_start: str | None = None,
) -> dict:
    start = _parse_start(horizon_start)
    model, _, scores = _criticality(grounded, tasks, days, seed, start)
    instance = _load(grounded, tasks, days, seed, start)
    if task_id not in scores:
        raise HTTPException(status_code=404, detail=f"unknown task {task_id}")
    return {
        "task_id": task_id,
        "score": round(scores[task_id], 4),
        "contributions": [
            {"feature": name, "contribution": round(float(value), 4)}
            for name, value in model.explain(instance, task_id)
        ],
    }


# ── field intake ────────────────────────────────────────────────────────
#
# Everything above answers "when should we close the line?". This part
# answers the question that comes first: "there is something wrong with the
# track — who needs to know?".
#
# Today that question is answered three times over, once per department, in
# three systems that cannot see each other. A single intake is not a
# convenience feature; it is the precondition for co-locating anything. See
# PROJECT_BRIEF.md section 2.


class ReportIn(BaseModel):
    """One defect or work request, as filed from the field."""

    section_id: str
    activity_type: str
    summary: str
    department: str
    concerns: list[str] = []
    severity: int = 3
    emergency: bool = False
    duration_minutes: int = 120
    crew_required: int = 2
    detail: str = ""


class DecisionIn(BaseModel):
    status: ReportStatus
    note: str = ""


@app.get("/api/activities")
def activities() -> dict:
    """The maintenance vocabulary, grouped by department.

    Served rather than hardcoded in the browser so the intake form offers
    exactly the activities the planner knows how to schedule. A form with its
    own list would drift, and a report naming work the optimiser has never
    heard of cannot be planned.
    """
    return {
        "activities": [
            {
                "activity_type": spec.activity_type,
                "label": spec.label,
                "department": spec.department.value,
                "interval_days": spec.interval_days,
                "typical_minutes": spec.duration_minutes_range[1],
                "typical_crew": spec.crew_range[1],
                "co_locatable": spec.co_locatable,
                # Surfaced, not hidden: every periodicity here is still
                # provisional, and the form should not imply otherwise.
                "source": spec.source,
            }
            for spec in CATALOGUE
        ],
        "departments": ["ENGG", "TRD", "S&T"],
    }


@app.get("/api/reports")
def list_reports(authorization: str | None = Header(default=None)) -> dict:
    store = _store_as(_caller(authorization))
    return {"reports": [r.model_dump(mode="json") for r in store.reports()]}


@app.post("/api/reports")
def file_report(
    body: ReportIn, authorization: str | None = Header(default=None)
) -> dict:
    caller = _caller(authorization)
    store = _store_as(caller)
    record = Report(**{**body.model_dump(), "reported_by": caller.label})
    try:
        return store.file_report(record).model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001
        raise _forbidden(exc) from exc


@app.patch("/api/reports/{report_id}")
def decide_report(
    report_id: str, body: DecisionIn,
    authorization: str | None = Header(default=None),
) -> dict:
    """Accept or turn down a report. The head's decision, enforced by RLS."""
    caller = _caller(authorization)
    store = _store_as(caller)
    try:
        decided = store.decide_report(
            report_id, body.status, caller.label, body.note
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise _forbidden(exc) from exc
    return decided.model_dump(mode="json")


@app.get("/api/window")
def quiet_windows(
    section_id: str, minutes: int = 120, grounded: bool = True,
    tasks: int = 120, days: int = 7, seed: int = 42,
    horizon_start: str | None = None, limit: int = 6,
    not_before: str | None = None,
) -> dict:
    """Where a job of this length could go on this section, cheapest first.

    Pure arithmetic over the section's own traffic profile — no solve, no
    cache, milliseconds. It answers the question an engineer filing a report
    actually has: "if this needs its own closure, what does that cost?".

    The answer is deliberately about ONE job in isolation, which is the
    expensive case. The browser compares it against the closures already
    planned on the same section, and the gap between the two is the whole
    argument for co-locating.

    Windows that have already passed are never offered. The horizon is a
    calendar month and people file reports in the middle of one, so without
    this the honest-looking answer to "when is the soonest?" was a date last
    week. `not_before` defaults to now and exists so tests can pin it.
    """
    if minutes <= 0:
        raise HTTPException(status_code=400, detail="minutes must be positive")

    start = _parse_start(horizon_start)
    instance = _load(grounded, tasks, days, seed, start)
    if not any(s.id == section_id for s in instance.sections):
        raise HTTPException(status_code=404, detail=f"unknown section {section_id}")

    grid = TimeGrid(horizon_start=start, horizon_days=days)
    series = traffic_by_slot(instance, grid)[section_id]
    permitted = permitted_slots(series, DEFAULT_PERCENTILE)
    length = grid.minutes_to_slots(minutes)
    starts = feasible_starts(permitted, length)

    floor = (
        datetime.fromisoformat(not_before) if not_before else datetime.now()
    )
    remaining = [s for s in starts if grid.to_datetime(s) >= floor]
    # The horizon being over is a different fact from the job not fitting,
    # and the two need different words in front of an engineer.
    horizon_over = bool(starts) and not remaining
    starts = remaining

    def cost(slot: int) -> float:
        return round(sum(series[slot:slot + length]) * grid.slot_hours, 2)

    priced = sorted(((cost(s), s) for s in starts), key=lambda pair: (pair[0], pair[1]))
    cheapest = [
        {
            "start": grid.to_datetime(slot).isoformat(),
            "end": grid.to_datetime(slot + length).isoformat(),
            "train_hours": price,
        }
        for price, slot in priced[:limit]
    ]
    return {
        "section_id": section_id,
        "section_name": next(
            s.name for s in instance.sections if s.id == section_id
        ),
        "minutes": minutes,
        # Empty means the job is longer than any quiet stretch this section
        # has. That is a real answer, not an error: it needs a traffic block,
        # which is a different authority's decision.
        "candidates": cheapest,
        "earliest": (
            {
                "start": grid.to_datetime(min(starts)).isoformat(),
                "end": grid.to_datetime(min(starts) + length).isoformat(),
                "train_hours": cost(min(starts)),
            }
            if starts else None
        ),
        "permitted_share": round(sum(permitted) / len(permitted), 3),
        "horizon_over": horizon_over,
    }


@app.get("/api/traffic")
def section_traffic(
    section_id: str, start: str | None = None, end: str | None = None,
    grounded: bool = True, tasks: int = 120, days: int = 7, seed: int = 42,
    horizon_start: str | None = None,
) -> dict:
    """The traffic case for one closure: why this hour, and not another.

    A divisional officer being told to hand over the line at 01:15 is owed
    the reason, and "the optimiser said so" is not one. This returns the
    section's own daily traffic shape, the threshold that makes an hour
    blockable at all, and where the chosen window sits against both.

    Arithmetic over data already loaded — no solve, so it costs nothing to
    open and cannot be the thing that runs the demo box out of memory.
    """
    start_date = _parse_start(horizon_start)
    instance = _load(grounded, tasks, days, seed, start_date)
    section = next((s for s in instance.sections if s.id == section_id), None)
    if section is None:
        raise HTTPException(status_code=404, detail=f"unknown section {section_id}")

    grid = TimeGrid(horizon_start=start_date, horizon_days=days)
    series = traffic_by_slot(instance, grid)[section_id]
    threshold = percentile(series, DEFAULT_PERCENTILE)
    permitted = permitted_slots(series, DEFAULT_PERCENTILE)

    profile = list(section.traffic_density_profile)
    peak = max(profile)

    window: dict = {}
    if start and end:
        try:
            began, finished = datetime.fromisoformat(start), datetime.fromisoformat(end)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="start and end must be ISO datetimes"
            ) from exc
        origin = grid.to_datetime(0)
        first = int((began - origin).total_seconds() // 60 // grid.slot_minutes)
        last = int((finished - origin).total_seconds() // 60 // grid.slot_minutes)
        first, last = max(0, first), min(len(series), max(first + 1, last))
        inside = series[first:last]
        hours = sorted({grid.day_hour(slot)[1] for slot in range(first, last)})
        window = {
            "hours": hours,
            "mean_trains_per_hour": round(sum(inside) / len(inside), 2) if inside else 0.0,
            "train_hours": round(sum(inside) * grid.slot_hours, 2),
            # What the same closure would have cost in the section's busiest
            # hour — the number that shows the placement was not arbitrary.
            "at_peak_train_hours": round(peak * (last - first) * grid.slot_hours, 2),
        }

    return {
        "section_id": section_id,
        "section_name": section.name,
        "profile": [round(v, 2) for v in profile],
        "peak": round(peak, 2),
        "peak_hour": profile.index(peak),
        "quietest": round(min(profile), 2),
        "daily_trains": section.daily_trains,
        # An hour is blockable only if it is in the section's own quietest
        # slice. Stated per section, because a flat rule leaves the busiest
        # trunk with no usable window at all.
        "threshold": round(threshold, 2),
        "percentile": DEFAULT_PERCENTILE,
        "blockable_hours": [h for h, v in enumerate(profile) if v <= threshold],
        "permitted_share": round(sum(permitted) / len(permitted), 3),
        "window": window,
    }


# ── when the plan meets reality ─────────────────────────────────────────
#
# A block plan survives contact with the railway for about a shift. A tamping
# machine fails, a possession is handed back late, a section is released
# early. The question a controller actually asks is not "what was the plan"
# but "given where we are now, what should the rest of the month look like".


class DisruptionIn(BaseModel):
    """One thing going wrong, at a point in the plan."""

    section_id: str
    #: When the overrun starts — normally the closure's own start.
    at: str
    overrun_minutes: int = 90
    description: str = ""


@app.post("/api/replan")
def replan(
    body: DisruptionIn, grounded: bool = True, tasks: int = 120, days: int = 7,
    seed: int = 42, time_limit: float = DEFAULT_UI_BUDGET,
    percentile: float = 25.0, horizon_start: str | None = None,
) -> dict:
    """Freeze the past, subtract what is done, re-plan the remainder.

    Re-planning is not a special solver mode: the same model runs on what is
    left, with the disrupted section made unavailable for the length of the
    overrun.

    The re-plan can legitimately come out WORSE than the original, because the
    horizon has shrunk and the overrun ate a quiet window other work needed.
    Reporting that honestly is the point — a re-planner that always claims an
    improvement is not measuring anything.
    """
    if body.overrun_minutes <= 0:
        raise HTTPException(status_code=400, detail="overrun_minutes must be positive")

    start = _parse_start(horizon_start)
    instance = _load(grounded, tasks, days, seed, start)
    if not any(s.id == body.section_id for s in instance.sections):
        raise HTTPException(
            status_code=404, detail=f"unknown section {body.section_id}")

    grid = TimeGrid(horizon_start=start, horizon_days=days)
    try:
        moment = datetime.fromisoformat(body.at)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="`at` must be an ISO datetime") from exc

    at_slot = int((moment - grid.to_datetime(0)).total_seconds() // 60 // grid.slot_minutes)
    if not 0 <= at_slot < grid.n_slots:
        raise HTTPException(
            status_code=400,
            detail="the disruption falls outside the planning horizon",
        )

    # Same gate as /api/plan: where the model will not fit in memory, take the
    # constructive route rather than being OOM-killed mid-request.
    if ALLOW_RUNTIME_SOLVE:
        _, planner, original, scores = _plan(
            grounded, tasks, days, seed, time_limit, percentile, start
        )
    else:
        _, planner, scores = _cheap_plan(grounded, tasks, days, seed, percentile, start)
        original = planner.greedy_only()

    def _run(overrun_slots: int):
        return replan_after(
            instance, original,
            Disruption(
                at_slot=at_slot, section_id=body.section_id,
                overrun_slots=overrun_slots,
                description=body.description or (
                    f"{body.overrun_minutes} minute overrun on {body.section_id}"
                ),
            ),
            time_limit=time_limit, percentile=percentile, criticality=scores,
            greedy_only=not ALLOW_RUNTIME_SOLVE,
        )

    result = _run(grid.minutes_to_slots(body.overrun_minutes))

    # The control: the SAME remaining work, re-solved with the SAME budget,
    # with nothing gone wrong.
    #
    # Without it the headline is a lie in the flattering direction. Re-solving
    # 71 leftover jobs searches a far smaller problem than the original
    # 300-job month did, so it finds a better arrangement for that stretch —
    # measured at -32.5 train-hours on a disruption that cannot possibly have
    # helped. Comparing against the original plan's remainder therefore
    # credits the disruption with the second look. Comparing against this
    # attributes to the disruption only what the disruption caused.
    control = _run(0)

    tasks_by_id = {t.id: t for t in instance.tasks}
    replanned_grid = TimeGrid(horizon_start=start, horizon_days=days)
    before = round(
        sum(b.train_hours for b in original.blocks if b.start_slot >= at_slot), 2)
    undisrupted = round(control.replanned.train_hours_lost, 2)
    disrupted = round(result.replanned.train_hours_lost, 2)

    return {
        "section_id": body.section_id,
        "section_name": next(
            s.name for s in instance.sections if s.id == body.section_id),
        "at": moment.isoformat(),
        "overrun_minutes": body.overrun_minutes,
        "description": result.disruption.description,
        "status": result.replanned.status,
        "wall_time": round(result.replanned.wall_time, 2),
        "completed": len(result.completed_task_ids),
        "carried": len(result.carried_task_ids),
        # What the original month-long plan had booked for this stretch.
        # Context, not the comparison — see the note on `control` above.
        "train_hours_before": before,
        # The same leftover work re-solved with nothing gone wrong.
        "train_hours_control": undisrupted,
        "train_hours_after": disrupted,
        # The disruption's own cost, and the only figure worth quoting.
        # Positive means it cost us, which is the usual case; the UI says so
        # plainly rather than hiding it.
        "delta": round(disrupted - undisrupted, 2),
        # Kept because it is what a naive reading would report, and a judge
        # who asks "why is this different" deserves to see both.
        "delta_vs_original": result.train_hours_delta,
        "blocks_before": sum(1 for b in original.blocks if b.start_slot >= at_slot),
        "blocks_after": len(result.replanned.blocks),
        "blocks_control": len(control.replanned.blocks),
        "scheduled_after": result.replanned.scheduled_count,
        "unplaceable": len(result.replanned.unscheduled_task_ids),
        "unplaceable_control": len(control.replanned.unscheduled_task_ids),
        "blocks": [
            _block_payload(b, replanned_grid, tasks_by_id)
            for b in sorted(result.replanned.blocks, key=lambda b: b.start_slot)[:40]
        ],
    }


# ── serving the UI ──────────────────────────────────────────────────────
#
# In production the Next.js app is built to static files and served from
# here, so a deployment is one process on one origin: no Node at runtime, no
# CORS, no proxy, and nothing to keep in sync between two services.
#
# Mounted LAST so every /api route is matched first — Starlette resolves
# routes in registration order, and a mount at "/" would otherwise swallow
# them.
UI_DIR = pathlib.Path(__file__).resolve().parents[2] / "web" / "out"

if UI_DIR.is_dir():
    app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")
    log.info("serving the UI from %s", UI_DIR)
else:
    log.info(
        "no built UI at %s — run: STATIC_EXPORT=1 npm --prefix web run build",
        UI_DIR,
    )
