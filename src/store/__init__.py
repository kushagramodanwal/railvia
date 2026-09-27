"""Store access. Supabase only — there is no local fallback by design.

Approvals must be visible to every planner, not trapped on one machine, so
this deliberately refuses to record a decision anywhere else. If Supabase is
not configured or not reachable, approval and completion stop working and say
why; planning itself is unaffected, because the planner is a pure function of
its inputs and needs no store at all.
"""

from __future__ import annotations

import logging

from src.store.auth import AuthError, Caller, bearer, verify
from src.store.base import Approval, Completion, Report, ReportStatus, Store
from src.store.supabase_store import SupabaseNotConfigured, SupabaseStore

log = logging.getLogger(__name__)

__all__ = [
    "Approval", "AuthError", "Caller", "Completion", "Report", "ReportStatus",
    "Store",
    "SupabaseNotConfigured", "SupabaseStore", "bearer", "get_store",
    "store_for", "store_status", "reset_store", "verify",
]

_store: Store | None = None
_error: str | None = None


def get_store() -> Store:
    """Return the process-wide Supabase store, or raise with the reason."""
    global _store, _error
    if _store is not None:
        return _store
    try:
        from src.ingest.railradar import load_dotenv

        load_dotenv()
        _store = SupabaseStore()
        _error = None
        return _store
    except Exception as exc:  # noqa: BLE001
        _error = str(exc)
        log.warning("Supabase unavailable: %s", exc)
        raise


def store_for(caller: Caller) -> Store:
    """A store acting as one signed-in user.

    Not cached: each user gets their own client so Postgres row-level
    security sees the right identity. Sharing one client across users would
    silently grant everyone the first caller's permissions.
    """
    from src.ingest.railradar import load_dotenv

    load_dotenv()
    return SupabaseStore(access_token=caller.token)


def store_status() -> dict:
    """Whether decisions can be recorded, for the UI to show plainly."""
    try:
        store = get_store()
        return {"connected": True, "backend": store.backend,
                "shared": store.shared, "detail": store.describe()}
    except Exception as exc:  # noqa: BLE001
        return {"connected": False, "backend": "Supabase", "shared": True,
                "detail": str(exc)}


def reset_store() -> None:
    """Testing hook."""
    global _store, _error
    _store, _error = None, None
