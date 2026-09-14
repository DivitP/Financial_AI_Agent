"""Matched-window forecast baselines and explicitly separated trading metrics."""

import warnings
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal

import numpy as np
from pydantic import Field, model_validator

from financial_ai.analysis.backtest import (
    Dataset,
    Decision,
    Record,
    Snapshot,
    WalkForwardConfig,
    walk_forward,
)


class Prediction(Record):
    sessions: tuple[str, ...]
    point: tuple[float, ...]
    lower: tuple[float, ...] | None = None
    upper: tuple[float, ...] | None = None
    interval_level: float | None = Field(default=None, ge=0.9, le=0.9)

    @model_validator(mode="after")
    def aligned(self):
        if not self.point or len(self.sessions) != len(self.point):
            raise ValueError("Prediction horizon mismatch")
        if any(v <= 0 for v in self.point):
            raise ValueError("Nonpositive price forecast")
        if self.interval_level is None:
            if self.lower is not None or self.upper is not None:
                raise ValueError("Intervals require a nominal level")
        elif (
            self.lower is None
            or self.upper is None
            or not len(self.lower) == len(self.upper) == len(self.point)
        ):
            raise ValueError("Incomplete forecast intervals")
        elif any(a > b for a, b in zip(self.lower, self.upper)):
            raise ValueError("Reversed forecast intervals")
        return self


BASELINES = ("last_value", "drift", "random_walk", "linear", "arima", "volatility")


def baseline(view: Snapshot, name: str, *, seed: int = 0, samples: int = 512) -> Prediction:
    if name not in BASELINES or samples < 2:
        raise ValueError("Unknown baseline or insufficient samples")
    y = np.array([float(p.close) for p in view.prices])
    h = len(view.forecast_sessions)
    steps = np.arange(1, h + 1)
    lower = upper = None
    point: np.ndarray
    if name == "last_value":
        point = np.repeat(y[-1], h)
    elif name == "drift":
        point = y[-1] + steps * (y[-1] - y[0]) / (len(y) - 1)
    elif name == "linear":
        coefficients = np.polyfit(np.arange(len(y)), y, 1)
        point = np.polyval(coefficients, np.arange(len(y), len(y) + h))
    elif name == "arima":
        from statsmodels.tsa.arima.model import ARIMA
        from statsmodels.tools.sm_exceptions import ConvergenceWarning

        if len(y) < 8:
            raise ValueError("ARIMA requires at least eight training observations")
        with warnings.catch_warnings():
            warnings.simplefilter("error", ConvergenceWarning)
            fitted = ARIMA(y, order=(1, 1, 0), trend="t").fit()
        if not fitted.mle_retvals.get("converged", False):
            raise ValueError("ARIMA did not converge")
        forecast = fitted.get_forecast(steps=h)
        point = forecast.predicted_mean
        lower, upper = np.asarray(forecast.conf_int(alpha=0.1)).T
    else:
        rng = np.random.default_rng(seed)
        if name == "random_walk":
            sigma = np.std(np.diff(y), ddof=1) if len(y) > 2 else 0.0
            paths = y[-1] + np.cumsum(rng.normal(0, sigma, (samples, h)), axis=1)
            point = np.repeat(y[-1], h)
        else:
            returns = np.diff(np.log(y))
            variance = float(returns[0] ** 2)
            for r in returns[1:]:
                variance = 0.94 * variance + 0.06 * float(r**2)
            paths = y[-1] * np.exp(
                np.cumsum(rng.normal(0, np.sqrt(variance), (samples, h)), axis=1)
            )
            point = np.repeat(y[-1], h)  # median of zero-log-drift process
        lower, upper = np.quantile(paths, [0.05, 0.95], axis=0)
    return Prediction(
        sessions=tuple(s.day.isoformat() for s in view.forecast_sessions),
        point=tuple(point),
        lower=None if lower is None else tuple(lower),
        upper=None if upper is None else tuple(upper),
        interval_level=None if lower is None else 0.9,
    )


def kronos_prediction(result: dict) -> Prediction:
    """Adapt local provider output; obtaining PIT OHLCV stays with the caller."""
    if result["summary"]["sample_count"] < 2:
        raise ValueError("Kronos interval evaluation requires multiple paths")
    if [c["session"] for c in result["candles"]] != [
        b["session"] for b in result["summary"]["bands"]
    ]:
        raise ValueError("Kronos bands do not match candle sessions")
    return Prediction(
        sessions=tuple(c["session"] for c in result["candles"]),
        point=tuple(float(c["close"]) for c in result["candles"]),
        lower=tuple(float(b["close_percentiles"]["5"]) for b in result["summary"]["bands"]),
        upper=tuple(float(b["close_percentiles"]["95"]) for b in result["summary"]["bands"]),
        interval_level=0.9,
    )


def accuracy(training: list[float], actual: list[float], prediction: Prediction) -> dict:
    if len(training) < 2 or not actual or not np.all(np.isfinite(training + actual)):
        raise ValueError("Metrics require finite training and outcome observations")
    truth, point = np.array(actual), np.array(prediction.point)
    if len(truth) != len(point):
        raise ValueError("Outcome horizon mismatch")
    error = point - truth
    scale = float(np.mean(np.abs(np.diff(training))))
    mae = float(np.mean(np.abs(error)))
    return {
        "mae": mae,
        "rmse": float(np.sqrt(np.mean(error**2))),
        "mase": mae / scale if scale > 0 else None,
        "mase_limitation": None if scale > 0 else "Training naive-error scale is zero",
        "terminal_direction_accuracy": float(
            np.sign(point[-1] - training[-1]) == np.sign(truth[-1] - training[-1])
        ),
        "interval_coverage": None
        if prediction.lower is None
        else float(
            np.mean((truth >= np.array(prediction.lower)) & (truth <= np.array(prediction.upper)))
        ),
    }


def trading_metrics(run: dict, initial_cash: float) -> dict:
    peak, drawdown = initial_cash, 0.0
    for fold in run["folds"]:
        equity = float(fold["final_equity"])
        peak = max(peak, equity)
        drawdown = max(drawdown, 1 - equity / peak)
    return {
        "turnover": sum(
            float(f["traded_notional"]) / float(f["initial_equity"]) for f in run["folds"]
        ),
        "max_fold_end_drawdown": drawdown,
    }


def compare_forecasts(
    data: Dataset,
    config: WalkForwardConfig,
    *,
    kronos: Callable[[Snapshot], Prediction],
    kronos_version: str,
    kronos_training_cutoff: datetime,
    seed: int = 0,
    samples: int = 512,
) -> dict:
    """Fail the comparison on any missing model/window, never silently select survivors."""
    # Matched raw-price comparisons cannot cross action discontinuities. Do not
    # retroactively adjust training with evaluation-period actions.
    if any(data.sessions[0].day <= a.session <= data.sessions[-1].day for a in data.actions):
        raise ValueError(
            "Forecast comparison requires action-free windows; explicit common-basis adapter needed"
        )
    versions = {
        s.day.isoformat(): min(
            (p for p in data.prices if p.session == s.day), key=lambda p: p.available_at
        )
        for s in data.sessions
    }
    results = {}
    for name in (*BASELINES, "kronos"):
        windows = []

        def strategy(view):
            prediction = Prediction.model_validate(
                kronos(view)
                if name == "kronos"
                else baseline(view, name, seed=seed, samples=samples)
            )
            expected = tuple(s.day.isoformat() for s in view.forecast_sessions)
            if prediction.sessions != expected:
                raise ValueError(f"{name}: mismatched forecast sessions")
            training = [float(p.close) for p in view.prices]
            windows.append(
                {
                    "as_of": view.as_of.isoformat(),
                    "training_evidence": [p.evidence_id for p in view.prices],
                    "outcome_evidence": [versions[s].evidence_id for s in expected],
                    "actual": [float(versions[s].close) for s in expected],
                    "forecast": prediction.model_dump(mode="json"),
                    "metrics": accuracy(
                        training, [float(versions[s].close) for s in expected], prediction
                    ),
                }
            )
            # Fixed simulation policy only, never an exposed trading instruction.
            return Decision(
                allocation=Decimal(int(prediction.point[-1] > training[-1])),
                evidence_ids=(view.prices[-1].evidence_id,),
            )

        run_config = WalkForwardConfig.model_validate(
            config.model_dump()
            | {
                "strategy_version": kronos_version if name == "kronos" else f"{name}-v1",
                "strategy_kind": "trained_model" if name == "kronos" else "deterministic",
                "model_training_cutoff": kronos_training_cutoff if name == "kronos" else None,
            }
        )
        run = walk_forward(data, run_config, strategy)
        results[name] = {
            "mean_window_metrics": {
                metric: None
                if any(w["metrics"][metric] is None for w in windows)
                else (
                    float(np.sqrt(np.mean([w["metrics"][metric] ** 2 for w in windows])))
                    if metric == "rmse"
                    else float(np.mean([w["metrics"][metric] for w in windows]))
                )
                for metric in [
                    "mae",
                    "rmse",
                    "mase",
                    "terminal_direction_accuracy",
                    "interval_coverage",
                ]
            },
            "windows": windows,
            "backtest": run,
            **trading_metrics(run, float(config.initial_cash)),
        }
    return {
        "models": results,
        "seed": seed,
        "samples": samples,
        "metric_units": {
            "mae": data.currency,
            "rmse": data.currency,
            "mase": "ratio",
            "coverage_direction_drawdown": "fraction",
            "turnover": "equity_multiple",
        },
        "warnings": [
            "Nominal 90% intervals are not calibrated confidence.",
            "Drawdown is sampled at fold exits, not intraperiod maximum drawdown.",
            "Trading policy: long when terminal point exceeds last close; otherwise cash; same costs for all models.",
        ],
    }
