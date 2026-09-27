"""Criticality scorer: LightGBM over the synthetic maintenance history.

Output is a probability of failure-if-deferred in [0,1], used directly as the
optimiser's criticality weight. It scales both the unscheduled penalty and
the lateness penalty, so the model changes *what gets deferred*, never where
a block is placed. Placement stays with CP-SAT.

Explainability is not optional here (PROJECT_BRIEF.md section 6). A judge
will ask why one task outranked another, and "the model decided" loses. The
scorer therefore reports gain-based feature importance, and can explain any
single task's score as a contribution breakdown.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import numpy as np

from src.adapters.history import HistorySource, SyntheticHistorySource
from src.ml.features import FEATURE_NAMES, instance_features, task_features
from src.models import PlanningInstance, Section

log = logging.getLogger(__name__)


@dataclass
class TrainingReport:
    n_records: int
    failure_rate: float
    auc: float
    log_loss: float
    importances: list[tuple[str, float]]

    def summary(self) -> str:
        lines = [
            f"trained on {self.n_records} synthetic history records "
            f"({self.failure_rate:.1%} failures)",
            f"held-out AUC {self.auc:.3f}, log-loss {self.log_loss:.3f}",
            "feature importance (gain):",
        ]
        total = sum(v for _, v in self.importances) or 1.0
        for name, value in self.importances:
            share = value / total
            bar = "█" * max(0, int(share * 40))
            lines.append(f"    {name:28} {share:6.1%} {bar}")
        return "\n".join(lines)


class CriticalityModel:
    """Gradient-boosted scorer. Falls back to sklearn if LightGBM is absent."""

    def __init__(self, seed: int = 11, history: HistorySource | None = None) -> None:
        self.seed = seed
        self.history = history or SyntheticHistorySource(seed=seed)
        self.model = None
        self.report: TrainingReport | None = None
        self.backend = "lightgbm"

    def train(
        self, sections: list[Section], n_records: int = 8000, test_fraction: float = 0.25
    ) -> TrainingReport:
        from sklearn.metrics import log_loss, roc_auc_score
        from sklearn.model_selection import train_test_split

        records = self.history.records(sections, n_records, date(2026, 3, 2))
        names = list(FEATURE_NAMES)
        X = np.asarray(
            [task_features(r.task, r.section, r.observed_on) for r in records],
            dtype=float,
        )
        y = np.asarray([1 if r.failed else 0 for r in records], dtype=int)

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_fraction, random_state=self.seed, stratify=y
        )

        try:
            import lightgbm as lgb

            self.model = lgb.LGBMClassifier(
                n_estimators=250, learning_rate=0.05, num_leaves=15,
                min_child_samples=40, subsample=0.9, colsample_bytree=0.9,
                random_state=self.seed, verbose=-1,
            )
            self.model.fit(X_train, y_train)
            importances = list(
                zip(names, self.model.booster_.feature_importance(importance_type="gain"))
            )
            self.backend = "lightgbm"
        except (ImportError, OSError) as exc:  # pragma: no cover
            # OSError as well as ImportError: LightGBM is a native wheel that
            # links against OpenMP, and on a slim base image it installs
            # cleanly then raises OSError("libgomp.so.1: cannot open shared
            # object file") on first use. Catching only ImportError turned a
            # missing system library into a 500 on every request.
            log.warning("LightGBM unavailable (%s); using scikit-learn", exc)
            from sklearn.ensemble import GradientBoostingClassifier

            self.model = GradientBoostingClassifier(random_state=self.seed)
            self.model.fit(X_train, y_train)
            importances = list(zip(names, self.model.feature_importances_))
            self.backend = "sklearn"

        probabilities = self.model.predict_proba(X_test)[:, 1]
        self.report = TrainingReport(
            n_records=len(y),
            failure_rate=float(y.mean()),
            auc=float(roc_auc_score(y_test, probabilities)),
            log_loss=float(log_loss(y_test, probabilities)),
            importances=sorted(importances, key=lambda kv: -kv[1]),
        )
        log.info("criticality model trained (%s): AUC %.3f", self.backend, self.report.auc)
        return self.report

    def score_instance(self, instance: PlanningInstance) -> dict[str, float]:
        """Criticality weight in [0,1] for every task in the instance."""
        if self.model is None:
            raise RuntimeError("train() must be called before scoring")
        ids, rows = instance_features(instance)
        probabilities = self.model.predict_proba(np.asarray(rows, dtype=float))[:, 1]
        return {task_id: float(p) for task_id, p in zip(ids, probabilities)}

    def explain(self, instance: PlanningInstance, task_id: str) -> list[tuple[str, float]]:
        """Per-feature contribution for one task, most influential first.

        Uses LightGBM's SHAP output where available: exact, additive, and the
        thing to put on screen when asked why this task outranked that one.
        """
        if self.model is None:
            raise RuntimeError("train() must be called before explaining")
        ids, rows = instance_features(instance)
        index = ids.index(task_id)
        row = np.asarray([rows[index]], dtype=float)
        if self.backend == "lightgbm":
            contributions = self.model.predict(row, pred_contrib=True)[0]
            pairs = list(zip(FEATURE_NAMES, contributions[:-1]))
            pairs.append(("<base value>", float(contributions[-1])))
        else:  # pragma: no cover
            pairs = [
                (name, float(value * weight))
                for name, value, weight in zip(
                    FEATURE_NAMES, rows[index], self.model.feature_importances_
                )
            ]
        return sorted(pairs, key=lambda kv: -abs(kv[1]))
