"""RailRadar API client.

RailRadar (https://railradar.in) aggregates public Indian Railways timetable
data (NTES). It is NOT an official Indian Railways endpoint and carries no
Railways sanction — it is a third-party aggregator of public data. Describe
it that way in the deck; do not imply otherwise.

What it gives us: the train timetable. That is the public half of what COA
holds internally, which means the traffic side of our data model can stop
being synthetic. See src/adapters/railradar.py.

Design constraints:
  * The free tier allows 1,000 requests/month. Every response is cached to
    disk permanently and never re-fetched, and a persisted counter enforces a
    per-run and per-month budget.
  * The fetch is offline and one-time. Nothing calls this at solve time.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date

log = logging.getLogger(__name__)

BASE_URL = "https://api.railradar.in/v1"
ENV_VAR = "RAILRADAR_API_KEY"
DEFAULT_CACHE_DIR = pathlib.Path("data/cache/railradar")
USER_AGENT = "SIH26027-block-planner/0.1 (academic project; contact via repo)"

# Free sandbox tier, per RailRadar developer docs (fetched 2026-08-28).
FREE_TIER_MONTHLY_REQUESTS = 1000

# Observed live, and NOT in the published docs: the API returns HTTP 429
# "Maximum 10 requests per minute" above this rate. We self-throttle rather
# than discover it by being refused, and leave a margin.
MAX_REQUESTS_PER_MINUTE = 10
MIN_REQUEST_INTERVAL = 60.0 / MAX_REQUESTS_PER_MINUTE + 0.5

# A 429 means the minute window is full; waiting less than the window is
# pointless. Backoff of 2/4/8s never clears it.
RATE_LIMIT_COOLDOWN = 62.0
# Leave headroom: never spend the whole allowance in one sitting.
DEFAULT_RUN_BUDGET = 60


def load_dotenv(path: pathlib.Path | str = ".env") -> dict[str, str]:
    """Minimal .env reader — no dependency, no surprises.

    Values already in the real environment win, so an inline
    `RAILRADAR_API_KEY=... command` still overrides the file.
    """
    path = pathlib.Path(path)
    loaded: dict[str, str] = {}
    if not path.exists():
        return loaded
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and value:
            loaded[key] = value
            os.environ.setdefault(key, value)
    return loaded


def find_api_key(explicit: str | None = None) -> str | None:
    """Resolve the key: explicit argument, then environment, then .env."""
    if explicit:
        return explicit
    if os.environ.get(ENV_VAR):
        return os.environ[ENV_VAR]
    # Walk up from the working directory so scripts work from subdirectories.
    here = pathlib.Path.cwd()
    for directory in (here, *here.parents):
        candidate = directory / ".env"
        if candidate.exists():
            load_dotenv(candidate)
            if os.environ.get(ENV_VAR):
                return os.environ[ENV_VAR]
        if (directory / ".git").exists():
            break
    return None


class RailRadarError(RuntimeError):
    """Any failure talking to RailRadar."""


class MissingAPIKey(RailRadarError):
    def __init__(self) -> None:
        super().__init__(
            "No RailRadar API key found.\n"
            "  Add it to a .env file in the repo root (gitignored):\n"
            "      echo 'RAILRADAR_API_KEY=rr_live_...' >> .env\n"
            "  or pass it inline:\n"
            "      RAILRADAR_API_KEY=rr_live_... .venv/bin/python scripts/probe_api.py --station NDLS\n"
            "  Free sandbox keys (1,000 requests/month): https://railradar.in/developers"
        )


class BudgetExceeded(RailRadarError):
    """Refuses to spend beyond the configured request allowance."""


@dataclass
class RequestBudget:
    """Persisted request counter, so the monthly allowance survives restarts."""

    path: pathlib.Path
    run_budget: int = DEFAULT_RUN_BUDGET
    monthly_budget: int = FREE_TIER_MONTHLY_REQUESTS
    spent_this_run: int = 0
    _state: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._state = self._read()

    def _month_key(self) -> str:
        return date.today().strftime("%Y-%m")

    def _read(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except json.JSONDecodeError:
                pass
        return {}

    @property
    def spent_this_month(self) -> int:
        return int(self._state.get(self._month_key(), 0))

    def remaining_this_month(self) -> int:
        return max(0, self.monthly_budget - self.spent_this_month)

    def check(self) -> None:
        if self.spent_this_run >= self.run_budget:
            raise BudgetExceeded(
                f"per-run budget of {self.run_budget} requests reached. "
                f"Responses already fetched are cached; re-run to continue."
            )
        if self.spent_this_month >= self.monthly_budget:
            raise BudgetExceeded(
                f"monthly allowance of {self.monthly_budget} requests is spent "
                f"({self._month_key()}). Cached data remains usable."
            )

    def record(self) -> None:
        self.spent_this_run += 1
        self._state[self._month_key()] = self.spent_this_month + 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._state, indent=2, sort_keys=True))


class RailRadarClient:
    """Caching, budget-aware client. One network call per uncached endpoint."""

    def __init__(
        self,
        api_key: str | None = None,
        cache_dir: pathlib.Path | str = DEFAULT_CACHE_DIR,
        run_budget: int = DEFAULT_RUN_BUDGET,
        offline: bool = False,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = find_api_key(api_key)
        self.cache_dir = pathlib.Path(cache_dir)
        self.offline = offline
        self.timeout = timeout
        self.budget = RequestBudget(
            path=self.cache_dir / "_budget.json", run_budget=run_budget
        )
        self._last_request_at: float = 0.0

    # -- cache ---------------------------------------------------------------

    def _cache_path(self, path: str, params: dict | None) -> pathlib.Path:
        slug = path.strip("/").replace("/", "_")
        if params:
            qs = "_".join(f"{k}-{v}" for k, v in sorted(params.items()))
            slug = f"{slug}__{qs}"
        return self.cache_dir / f"{slug}.json"

    def cached_paths(self) -> list[pathlib.Path]:
        if not self.cache_dir.exists():
            return []
        return sorted(p for p in self.cache_dir.glob("*.json") if not p.name.startswith("_"))

    # -- fetch ---------------------------------------------------------------

    def get(self, path: str, params: dict | None = None, force: bool = False) -> dict:
        """GET an endpoint, serving from disk cache when possible."""
        cache_path = self._cache_path(path, params)
        if cache_path.exists() and not force:
            return json.loads(cache_path.read_text())

        if self.offline:
            raise RailRadarError(
                f"offline mode and no cached response for {path} {params or ''}. "
                f"Expected at {cache_path}"
            )
        if not self.api_key:
            raise MissingAPIKey()

        self.budget.check()
        url = f"{BASE_URL}/{path.lstrip('/')}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"

        payload = self._request_with_retries(url)
        self.budget.record()

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
        return payload

    def _throttle(self) -> None:
        """Keep under the 10-per-minute ceiling without being told."""
        elapsed = time.monotonic() - self._last_request_at
        if self._last_request_at and elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)

    def _request_with_retries(self, url: str, attempts: int = 4) -> dict:
        last: Exception | None = None
        for attempt in range(attempts):
            self._throttle()
            self._last_request_at = time.monotonic()
            request = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "X-API-Key": str(self.api_key),
                    "Accept": "application/json",
                    "User-Agent": USER_AGENT,
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")[:400]
                if exc.code in (401, 403):
                    raise RailRadarError(
                        f"HTTP {exc.code} — API key rejected. {body}"
                    ) from exc
                if exc.code == 404:
                    raise RailRadarError(f"HTTP 404 — not found: {url}. {body}") from exc
                if exc.code in (429, 503):
                    # 429 means the per-minute window is full: wait it out
                    # rather than hammering with a short backoff.
                    retry_after = exc.headers.get("Retry-After") if exc.headers else None
                    if exc.code == 429:
                        wait = float(retry_after) if retry_after else RATE_LIMIT_COOLDOWN
                    else:
                        wait = 2 ** (attempt + 1)
                    last = RailRadarError(f"HTTP {exc.code} — {body}")
                    log.warning("HTTP %s, waiting %.0fs before retry", exc.code, wait)
                    time.sleep(wait)
                    continue
                raise RailRadarError(f"HTTP {exc.code} — {body}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last = RailRadarError(f"network error: {exc}")
                time.sleep(2 ** (attempt + 1))
        raise last or RailRadarError("request failed")

    # -- endpoints -----------------------------------------------------------

    def station_board(self, station_code: str, include_intermediate: bool = True) -> dict:
        """All scheduled trains at a station.

        include_intermediate=True is essential: without it the response omits
        pass-through trains, which on a trunk section are most of the traffic.
        Undercounting them would understate the cost of blocking and inflate
        our headline improvement.
        """
        return self.get(
            f"stations/{station_code.upper()}/trains",
            {"includeIntermediate": str(include_intermediate).lower()},
        )

    def train_details(self, number: str, halts_only: bool = False) -> dict:
        return self.get(f"trains/{number}", {"haltsOnly": str(halts_only).lower()})

    def station_lookup(self) -> dict:
        return self.get("lookup/stations")
