"""Disk-backed cache for solved plans.

A solve costs seconds and the answer is deterministic given the inputs — the
same params always describe the same instance. Recomputing it on every page
load, and again after every restart, is pure waiting.

Keyed on the request parameters plus a version stamp. Bump `CACHE_VERSION`
whenever the model, objective, or generator changes, or the cache will hand
back plans built by code that no longer exists.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import pathlib
import threading

log = logging.getLogger(__name__)

# Bump on any change to the model, objective, warm start, or generator.
CACHE_VERSION = "5"

# Overridable, because some hosts give the app a writable directory
# elsewhere. Hugging Face Spaces, for instance, runs the container as a
# non-root user against a root-owned image.
CACHE_DIR = pathlib.Path(os.environ.get("PLAN_CACHE_DIR", "data/cache/plans"))
_lock = threading.Lock()


def key(**params) -> str:
    blob = json.dumps({"v": CACHE_VERSION, **params}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


def load(cache_key: str) -> dict | None:
    path = CACHE_DIR / f"{cache_key}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        # A truncated cache file is worth nothing; recompute rather than
        # serving half a plan.
        log.warning("discarding unreadable cache entry %s", path.name)
        path.unlink(missing_ok=True)
        return None


def store(cache_key: str, payload: dict) -> None:
    """Write a plan to the cache, or carry on without one.

    A read-only or unwritable cache directory is a performance problem, not a
    correctness one — the plan has already been computed and is about to be
    returned. Some hosts run the container as a user that cannot write to the
    image, so failing the request over it would turn a slow page into a
    broken one.
    """
    try:
        with _lock:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path = CACHE_DIR / f"{cache_key}.json"
            # Write then rename, so a crash mid-write cannot leave a partial
            # file that looks valid.
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload))
            tmp.replace(path)
    except OSError as exc:
        log.warning("could not cache the plan (%s); serving it anyway", exc)


def clear() -> int:
    if not CACHE_DIR.exists():
        return 0
    files = list(CACHE_DIR.glob("*.json"))
    for f in files:
        f.unlink(missing_ok=True)
    return len(files)
