from datetime import datetime, timedelta, UTC
from decimal import Decimal

import numpy as np
import pytest

from financial_ai.analysis.backtest import (
    Dataset,
    Price,
    TradingSession,
    Snapshot,
    WalkForwardConfig,
)
from financial_ai.analysis.forecast_evaluation import (
    Prediction,
    accuracy,
    baseline,
    compare_forecasts,
    kronos_prediction,
    trading_metrics,
)


def history():
    days = [datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(45)]
    days = [d for d in days if d.weekday() < 5][:30]
    sessions = tuple(
        TradingSession(
            day=d.date(),
            available_at=datetime(2025, 1, 1, tzinfo=UTC),
            opens_at=d.replace(hour=9),
            closes_at=d.replace(hour=16),
        )
        for d in days
    )
    y: np.ndarray = 100 + np.cumsum(np.random.default_rng(4).normal(0.2, 1, len(sessions)))
    prices = tuple(
        Price(
            session=s.day,
            open=float(p),
            close=float(p),
            available_at=s.closes_at,
            evidence_id=f"p-{i}",
        )
        for i, (s, p) in enumerate(zip(sessions, y))
    )
    return Dataset(
        symbol="TEST",
        provider="fixture",
        currency="USD",
        timezone="UTC",
        calendar_source="synthetic",
        actions_complete=True,
        sessions=sessions,
        prices=prices,
    )


def test_exact_metrics_and_zero_mase_scale():
    p = Prediction(
        sessions=("a", "b"), point=(12, 16), lower=(11, 12), upper=(13, 14), interval_level=0.9
    )
    m = accuracy([8, 10], [13, 14], p)
    assert m["mae"] == 1.5
    assert m["rmse"] == pytest.approx(2.5**0.5)
    assert m["mase"] == 0.75
    assert m["terminal_direction_accuracy"] == 1
    assert m["interval_coverage"] == 1
    assert accuracy([10, 10], [13, 17], p)["mase"] is None
    assert accuracy([10, 10], [13, 17], p)["interval_coverage"] == 0.5
    with pytest.raises(ValueError):
        Prediction(sessions=("a",), point=(float("nan"),))


def test_baseline_formulas_and_reproducibility():
    data = history()
    prices = tuple(
        p.model_copy(update={"close": Decimal(i + 100)}) for i, p in enumerate(data.prices[:24])
    )
    view = Snapshot(
        as_of=prices[-1].available_at,
        prices=prices,
        actions=(),
        forecast_sessions=data.sessions[24:27],
    )
    assert baseline(view, "last_value").point == (123, 123, 123)
    for name in ["linear", "drift"]:
        assert baseline(view, name).point == pytest.approx((124, 125, 126))
    view = view.model_copy(update={"prices": data.prices[:24]})
    for name in ["random_walk", "volatility"]:
        assert baseline(view, name, seed=4) == baseline(view, name, seed=4)
        assert baseline(view, name, seed=4).lower != baseline(view, name, seed=5).lower
    assert len(baseline(view, "arima").point) == 3  # real offline statsmodels fit


def test_all_models_use_identical_windows_horizons_and_costs():
    data = history()
    cfg = WalkForwardConfig(train_sessions=24, horizon=3, fee_bps=10, slippage_bps=5)
    kwargs: dict = dict(
        kronos=lambda v: baseline(v, "drift"),
        kronos_version="fixture-v1",
        kronos_training_cutoff=datetime(2025, 1, 1, tzinfo=UTC),
    )
    result = compare_forecasts(data, cfg, **kwargs)
    signatures = []
    for name, model in result["models"].items():
        signatures.append(
            [
                (w["as_of"], w["training_evidence"], w["forecast"]["sessions"])
                for w in model["windows"]
            ]
        )
        assert model["backtest"]["config"]["fee_bps"] == "10"
        assert 0 <= model["max_fold_end_drawdown"] <= 1
    assert all(s == signatures[0] for s in signatures)
    assert len(signatures[0]) == 2
    assert (
        result["models"]["kronos"]["mean_window_metrics"]
        == result["models"]["drift"]["mean_window_metrics"]
    )
    assert result["models"]["last_value"]["turnover"] == 0
    assert result["models"]["drift"]["turnover"] > 0

    def bad(v):
        return Prediction(sessions=("wrong",), point=(100,))

    with pytest.raises(ValueError, match="mismatched forecast sessions"):
        compare_forecasts(data, cfg, **(kwargs | {"kronos": bad}))


def test_kronos_adapter_intervals():
    result: dict = {
        "candles": [{"session": "2026-01-01", "close": "100"}],
        "summary": {
            "sample_count": 4,
            "bands": [{"session": "2026-01-01", "close_percentiles": {"5": "90", "95": "110"}}],
        },
    }
    assert kronos_prediction(result).lower == (90,)
    result["summary"]["sample_count"] = 1
    with pytest.raises(ValueError, match="multiple paths"):
        kronos_prediction(result)


def test_turnover_and_drawdown_exact_values():
    run = {
        "folds": [
            {"initial_equity": "100", "final_equity": "120", "traded_notional": "220"},
            {"initial_equity": "120", "final_equity": "90", "traded_notional": "210"},
        ]
    }
    metrics = trading_metrics(run, 100)
    assert metrics["max_fold_end_drawdown"] == 0.25
    assert metrics["turnover"] == pytest.approx(3.95)
