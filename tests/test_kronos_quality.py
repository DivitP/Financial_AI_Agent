from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from financial_ai.analysis.backtest import WalkForwardConfig
from financial_ai.analysis.forecast_evaluation import BASELINES
from financial_ai.kronos import quality
from financial_ai.kronos.inference import InferenceConfig
from financial_ai.kronos.quality import KronosQuality, PromotionPolicy, Scope, fingerprint, gate
from financial_ai.storage.database import Database
from financial_ai.storage.model_runs import ModelRunRepository
from test_forecast_evaluation import history
from test_kronos_preprocessing import bar, prepare


def comparison():
    metrics = {
        "mae": 1.0,
        "rmse": 1.0,
        "mase": 0.5,
        "terminal_direction_accuracy": 0.7,
        "interval_coverage": 0.9,
    }
    candidate: dict = {
        "windows": [{"as_of": f"2026-01-{d}T16:00:00+00:00"} for d in [20, 23]],
        "mean_window_metrics": metrics,
        "turnover": 4.0,
        "max_fold_end_drawdown": 0.1,
    }
    models = {"kronos": candidate}
    for name in BASELINES:
        models[name] = deepcopy(candidate)
        models[name]["mean_window_metrics"].update(mae=2.0, rmse=2.0)
    return {"models": models, "warnings": ["Fixture evaluation; not a real validation."]}


def setup(tmp_path):
    database = Database(tmp_path / "research.sqlite3")
    database.migrate_to_latest()
    policy = PromotionPolicy(
        version="test-v1", frozen_at=datetime(2025, 1, 1, tzinfo=UTC), min_windows=2
    )
    service = KronosQuality(ModelRunRepository(database), policy)
    scope = Scope(
        symbol="TEST",
        currency="USD",
        timezone="UTC",
        adjustment_policy="raw",
        context=24,
        horizon=3,
        model_fingerprint="a" * 64,
    )
    return service, scope, database


def evaluate(service, scope):
    return service.evaluate(
        scope,
        history(),
        WalkForwardConfig(train_sessions=24, horizon=3),
        kronos=lambda view: None,
        training_cutoff=datetime(2025, 1, 1, tzinfo=UTC),
    )


def test_pass_persists_and_latest_failure_revokes(tmp_path, monkeypatch):
    service, scope, db = setup(tmp_path)
    monkeypatch.setattr(quality, "compare_forecasts", lambda *a, **kw: comparison())
    result = evaluate(service, scope)
    assert result["promotion_status"] == "promoted"
    restarted = KronosQuality(ModelRunRepository(db), service.policy)
    assert restarted.eligibility(scope, as_of=datetime.now(UTC))["status"] == "promoted"
    bad = comparison()
    bad["models"]["kronos"]["mean_window_metrics"]["mae"] = 3
    monkeypatch.setattr(quality, "compare_forecasts", lambda *a, **kw: bad)
    result = evaluate(service, scope)
    assert result["promotion_status"] == "experimental"
    assert any("baseline_not_beaten" in r for r in result["reasons"])
    assert restarted.eligibility(scope, as_of=datetime.now(UTC))["status"] == "experimental"
    assert len(restarted.repository.history(scope.key, "evaluation")) == 2


def test_policy_expiry_scope_and_evaluation_failure(tmp_path, monkeypatch):
    service, scope, db = setup(tmp_path)
    monkeypatch.setattr(quality, "compare_forecasts", lambda *a, **kw: comparison())
    evaluate(service, scope)
    assert (
        service.eligibility(scope, as_of=datetime.now(UTC) + timedelta(days=31))["status"]
        == "experimental"
    )
    assert (
        service.eligibility(scope.model_copy(update={"horizon": 1}), as_of=datetime.now(UTC))[
            "status"
        ]
        == "experimental"
    )
    changed = KronosQuality(
        service.repository, service.policy.model_copy(update={"version": "new"})
    )
    assert changed.eligibility(scope, as_of=datetime.now(UTC))["reasons"] == ["policy_changed"]

    def fail(*args, **kwargs):
        raise RuntimeError("secret-provider-token")

    monkeypatch.setattr(quality, "compare_forecasts", fail)
    result = evaluate(service, scope)
    assert result["promotion_status"] == "experimental"
    assert result["error_type"] == "RuntimeError"
    assert "secret-provider-token" not in str(service.repository.history(scope.key, "evaluation"))
    db.migrate_to(7)
    db.migrate_to_latest()
    assert service.repository.history(scope.key, "evaluation") == []


def test_gate_rejects_missing_uncalibrated_and_posthoc_results(tmp_path):
    service, _, _ = setup(tmp_path)
    for value in [None, float("nan"), 1.0]:
        result = comparison()
        result["models"]["kronos"]["mean_window_metrics"]["interval_coverage"] = value
        assert "threshold_failed:interval_coverage" in gate(result, service.policy)
    assert "policy_not_frozen_before_holdout" in gate(
        comparison(),
        service.policy.model_copy(update={"frozen_at": datetime(2026, 2, 1, tzinfo=UTC)}),
    )
    assert "insufficient_out_of_sample_windows" in gate(
        comparison(), service.policy.model_copy(update={"min_windows": 30})
    )


def test_forecasts_persist_failures_and_experimental_visibility(tmp_path):
    service, _, _ = setup(tmp_path)
    prepared = prepare([bar(d, 50) for d in [3, 4, 8, 9]])
    provider = SimpleNamespace(
        config=InferenceConfig(), forecast=lambda p: {"warnings": ["unvalidated"], "paths": []}
    )
    first = service.forecast(provider, prepared, symbol="TEST")
    scope = Scope.model_validate(first["scope"])
    assert scope.model_fingerprint == fingerprint(provider)
    assert first["result"]["research_only"]
    assert service.visible_forecasts(scope) == []
    assert len(service.visible_forecasts(scope, experimental=True)) == 1

    def fail(p):
        raise TimeoutError("private")

    provider.forecast = fail
    failed = service.forecast(provider, prepared, symbol="TEST")
    assert failed["status"] == "failed"
    assert len(service.visible_forecasts(scope, experimental=True)) == 2
    assert "private" not in str(failed)


def test_promoted_view_requires_live_matching_gate(tmp_path):
    service, _, _ = setup(tmp_path)
    prepared = prepare([bar(d, 50) for d in [3, 4, 8, 9]])
    provider = SimpleNamespace(config=InferenceConfig(), forecast=lambda p: {"warnings": []})
    first = service.forecast(provider, prepared, symbol="TEST")
    scope = Scope.model_validate(first["scope"])
    # Fixture persisted gate; production writes this through evaluate().
    service.repository.append(
        scope.key,
        "evaluation",
        "promoted",
        {
            "policy": service.policy.model_dump(mode="json"),
            "comparison": comparison(),
        },
    )
    prepared = prepared.model_copy(update={"as_of": datetime.now(UTC)})
    promoted = service.forecast(provider, prepared, symbol="TEST")
    assert not promoted["result"]["research_only"]
    assert len(service.visible_forecasts(scope)) == 1
    service.repository.append(
        scope.key,
        "evaluation",
        "failed",
        {
            "policy": service.policy.model_dump(mode="json"),
            "reasons": ["evaluation_failed"],
        },
    )
    assert service.visible_forecasts(scope) == []
    assert len(service.visible_forecasts(scope, experimental=True)) == 2


def test_append_rolls_back_nonfinite_results(tmp_path):
    service, scope, _ = setup(tmp_path)
    with pytest.raises(ValueError):
        service.repository.append(scope.key, "evaluation", "promoted", {"bad": float("nan")})
    assert service.repository.history(scope.key, "evaluation") == []
