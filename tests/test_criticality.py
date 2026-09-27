"""Criticality model: it must rank sensibly and stay explainable."""

from __future__ import annotations

import pytest

from src.adapters import SyntheticHistorySource
from src.ml.criticality import CriticalityModel
from src.ml.features import FEATURE_NAMES, task_features
from src.generator.history import failure_probability
from tests.test_optimiser_constraints import NIGHT_SPARSE, build_instance, task


@pytest.fixture(scope="module")
def trained():
    from src.adapters import SyntheticDataSource

    instance = SyntheticDataSource(n_tasks=40).load()
    model = CriticalityModel()
    report = model.train(instance.sections, n_records=3000)
    return model, report, instance


def test_hazard_rises_with_severity_overrun_and_traffic():
    """Direction of each coefficient is arguable from first principles."""
    base = failure_probability(3, 1.0, 150)
    assert failure_probability(5, 1.0, 150) > base
    assert failure_probability(3, 2.0, 150) > base
    assert failure_probability(3, 1.0, 400) > base


def test_history_has_both_outcomes(trained):
    _, _, instance = trained
    records = SyntheticHistorySource().records(
        instance.sections, 800, instance.horizon_start
    )
    outcomes = {r.failed for r in records}
    assert outcomes == {True, False}, "history must contain both outcomes"


def test_model_beats_chance_but_is_not_suspiciously_perfect(trained):
    """AUC near 1.0 would mean we fitted our own formula, not learnt from
    noisy events. See ASSUMPTIONS.md (A-08)."""
    _, report, _ = trained
    assert 0.55 < report.auc < 0.95


def test_scores_are_probabilities(trained):
    model, _, instance = trained
    scores = model.score_instance(instance)
    assert len(scores) == len(instance.tasks)
    assert all(0.0 <= v <= 1.0 for v in scores.values())


def test_overdue_work_scores_higher_on_average(trained):
    model, _, instance = trained
    scores = model.score_instance(instance)
    overdue = [scores[t.id] for t in instance.tasks if t.is_overdue]
    fresh = [scores[t.id] for t in instance.tasks if not t.is_overdue]
    if overdue and fresh:
        assert sum(overdue) / len(overdue) > sum(fresh) / len(fresh)


def test_feature_vector_matches_declared_names(trained):
    _, _, instance = trained
    section = instance.sections[0]
    row = task_features(instance.tasks[0], section, instance.horizon_start)
    assert len(row) == len(FEATURE_NAMES)


def test_explanation_is_available_and_ordered(trained):
    """A judge will ask why one task outranked another."""
    model, _, instance = trained
    task_id = instance.tasks[0].id
    contributions = model.explain(instance, task_id)
    assert contributions
    magnitudes = [abs(v) for _, v in contributions]
    assert magnitudes == sorted(magnitudes, reverse=True)


def test_scoring_before_training_is_refused():
    model = CriticalityModel()
    instance = build_instance({"S1": NIGHT_SPARSE}, [task("T1", "S1", 60)])
    with pytest.raises(RuntimeError):
        model.score_instance(instance)


def test_missing_native_library_falls_back_to_sklearn(monkeypatch):
    """LightGBM is a native wheel linking against OpenMP.

    On a slim base image it installs cleanly and then raises
    OSError("libgomp.so.1: cannot open shared object file") on first use.
    Catching only ImportError turned a missing system library into a 500 on
    every request, so OSError must fall back too.
    """
    import builtins

    from src.adapters import SyntheticDataSource

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "lightgbm":
            raise OSError("libgomp.so.1: cannot open shared object file")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    instance = SyntheticDataSource(n_tasks=20).load()
    model = CriticalityModel()
    report = model.train(instance.sections, n_records=600)
    assert model.backend == "sklearn"
    assert 0.0 < report.auc < 1.0
    scores = model.score_instance(instance)
    assert len(scores) == len(instance.tasks)
