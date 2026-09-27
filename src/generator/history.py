"""Synthetic maintenance history with observed outcomes.

Why outcomes rather than a formula
----------------------------------
The model has to learn from something. The tempting shortcut is to compute a
criticality score with a formula and then fit a model to reproduce it — but
that model has learned nothing except our own arithmetic, and a judge is
right to dismiss it.

Instead the generator simulates *events*: a maintenance task is deferred for
a while, and sometimes a failure follows — a rail defect worsens, an OHE
dropper snaps, a point machine fails. Failure is sampled as a noisy binary
outcome whose probability rises with severity, with how far past its interval
the asset has gone, and with how heavily the section is used. The model then
learns P(failure) from observed events, which is a genuine learning problem
with irreducible noise, and is the shape a real TMS/SMMS/TDMS history would
take.

The honest caveat, stated in ASSUMPTIONS.md (A-08) and worth repeating in the
deck: **we still wrote the hazard function underneath.** The model's value is
not that it discovers the relationship, but that it combines several features
into one calibrated, explainable ranking, and that it can be retrained on
real history the day a feed exists. We claim nothing more than that.
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta

from dataclasses import dataclass

from src.models.catalogue import CATALOGUE
from src.generator.synthetic import DEPARTMENT_WEIGHTS, _make_task
from src.models import Section, Task

# Hazard coefficients. These describe our modelled world, not a measured one.
# Each is signed so the direction is arguable from first principles:
#   severity     — a worse defect is likelier to fail
#   overrun      — an asset past its mandated interval is likelier to fail
#   utilisation  — heavier traffic wears track and OHE faster
BASE_LOG_ODDS = -3.2
SEVERITY_COEF = 0.55
OVERRUN_COEF = 1.30
TRAFFIC_COEF = 0.004


def failure_probability(
    severity: int, interval_fraction_elapsed: float, daily_trains: float
) -> float:
    """Logistic hazard. Rises with severity, overrun and traffic."""
    overrun = max(0.0, interval_fraction_elapsed - 1.0)
    log_odds = (
        BASE_LOG_ODDS
        + SEVERITY_COEF * severity
        + OVERRUN_COEF * min(overrun, 3.0)
        + TRAFFIC_COEF * daily_trains
    )
    return 1.0 / (1.0 + math.exp(-log_odds))


@dataclass(frozen=True)
class HistoryRecord:
    """One past observation: a task, its section, when it was seen, and
    whether a failure followed before it was attended to.

    Deliberately raw. Turning this into model input is the ML layer's job, so
    feature engineering can change without touching the generator.
    """

    task: Task
    section: Section
    observed_on: date
    failed: bool


def build_history(
    sections: list[Section],
    n_records: int = 6000,
    seed: int = 7,
    as_of: date = date(2026, 3, 2),
) -> list[HistoryRecord]:
    """Generate observed maintenance outcomes."""
    rng = random.Random(seed)
    departments = list(DEPARTMENT_WEIGHTS)
    weights = [DEPARTMENT_WEIGHTS[d] for d in departments]
    by_dept = {d: [a for a in CATALOGUE if a.department == d] for d in departments}

    records: list[HistoryRecord] = []

    for index in range(n_records):
        section = rng.choice(sections)
        dept = rng.choices(departments, weights=weights, k=1)[0]
        spec = rng.choice(by_dept[dept])
        # Observation date spread over two years of history.
        observed = as_of - timedelta(days=rng.randint(0, 730))
        task = _make_task(rng, index, section, spec, observed, 30)

        days_since = (observed - task.last_done_date).days
        elapsed = days_since / task.interval_days if task.interval_days else 0.0
        probability = failure_probability(
            task.defect_severity.value, elapsed, section.daily_trains
        )
        records.append(
            HistoryRecord(
                task=task,
                section=section,
                observed_on=observed,
                failed=rng.random() < probability,
            )
        )

    return records
