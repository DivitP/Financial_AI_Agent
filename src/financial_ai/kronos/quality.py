"""Scoped, fail-closed promotion backed by persisted out-of-sample evaluations."""

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta

from pydantic import AwareDatetime, Field

from financial_ai.analysis.backtest import Record, WalkForwardConfig
from financial_ai.analysis.forecast_evaluation import BASELINES, compare_forecasts
from financial_ai.kronos import load_manifest
from financial_ai.storage.model_runs import ModelRunRepository


class Scope(Record):
    symbol: str = Field(min_length=1)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    timezone: str
    adjustment_policy: str
    horizon: int = Field(ge=1)
    context: int = Field(ge=2)
    model_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")

    @property
    def key(self):
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


def fingerprint(provider) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "manifest": load_manifest().model_dump(mode="json"),
                "configuration": provider.config.model_dump(mode="json"),
                "adapter": "local-v2-paths",
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()


class PromotionPolicy(Record):
    version: str = Field(min_length=1)
    # Recorded before the evaluated holdout: not a post-hoc tuning timestamp.
    frozen_at: AwareDatetime
    min_windows: int = Field(default=30, ge=2)
    max_mase: float = Field(default=1, gt=0)
    min_direction: float = Field(default=0.55, ge=0, le=1)
    min_coverage: float = Field(default=0.85, ge=0, le=1)
    max_coverage: float = Field(default=0.95, ge=0, le=1)
    min_error_improvement: float = Field(default=0.05, ge=0, lt=1)
    max_drawdown: float = Field(default=0.25, ge=0, le=1)
    max_turnover: float = Field(default=100, ge=0)
    valid_days: int = Field(default=30, ge=1, le=365)


def gate(comparison: dict, policy: PromotionPolicy) -> list[str]:
    reasons = []
    models = comparison["models"]
    candidate = models["kronos"]
    windows = candidate["windows"]
    if len(windows) < policy.min_windows:
        reasons.append("insufficient_out_of_sample_windows")
    if not windows or any(datetime.fromisoformat(w["as_of"]) < policy.frozen_at for w in windows):
        reasons.append("policy_not_frozen_before_holdout")
    if policy.min_coverage > policy.max_coverage:
        reasons.append("invalid_coverage_thresholds")
    metrics = candidate["mean_window_metrics"]
    for name, minimum, maximum in [
        ("mase", 0, policy.max_mase),
        ("terminal_direction_accuracy", policy.min_direction, 1),
        ("interval_coverage", policy.min_coverage, policy.max_coverage),
    ]:
        value = metrics.get(name)
        if value is None or not math.isfinite(value) or not minimum <= value <= maximum:
            reasons.append(f"threshold_failed:{name}")
    for name, maximum in [
        ("max_fold_end_drawdown", policy.max_drawdown),
        ("turnover", policy.max_turnover),
    ]:
        value = candidate[name]
        if not math.isfinite(value) or not 0 <= value <= maximum:
            reasons.append(f"threshold_failed:{name}")
    for baseline in BASELINES:
        for metric in ["mae", "rmse"]:
            value, reference = metrics[metric], models[baseline]["mean_window_metrics"][metric]
            if (
                value is None
                or reference is None
                or not math.isfinite(value)
                or not math.isfinite(reference)
                or reference <= 0
                or value < 0
                or value > reference * (1 - policy.min_error_improvement)
            ):
                reasons.append(f"baseline_not_beaten:{baseline}:{metric}")
    return reasons


class KronosQuality:
    def __init__(self, repository: ModelRunRepository, policy: PromotionPolicy):
        self.repository, self.policy = repository, policy

    def evaluate(
        self, scope: Scope, data, config: WalkForwardConfig, *, kronos, training_cutoff
    ) -> dict:
        payload = {
            "scope": scope.model_dump(mode="json"),
            "policy": self.policy.model_dump(mode="json"),
            "limitations": [
                "Trusted point-in-time inputs and callback required; not calibrated forecast confidence."
            ],
            "backtest_config": config.model_dump(mode="json"),
            "training_cutoff": training_cutoff.isoformat(),
            "dataset_hash": hashlib.sha256(data.model_dump_json().encode()).hexdigest(),
        }
        try:
            if (
                scope.symbol != data.symbol
                or scope.currency != data.currency
                or scope.timezone != data.timezone
                or scope.horizon != config.horizon
                or scope.context != config.train_sessions
                or config.mode != "rolling"
                or scope.adjustment_policy not in {"raw", "total_return_adjusted_as_of"}
            ):
                raise ValueError("Evaluation scope mismatch")
            if data.sessions[-1].closes_at > datetime.now(UTC):
                raise ValueError("Evaluation outcomes are not yet observable")
            comparison = compare_forecasts(
                data,
                config,
                kronos=kronos,
                kronos_version=scope.model_fingerprint,
                kronos_training_cutoff=training_cutoff,
            )
            json.dumps(comparison, allow_nan=False)
            reasons = gate(comparison, self.policy)
            payload.update(
                comparison=comparison,
                reasons=reasons,
                limitations=payload["limitations"] + comparison["warnings"],
            )
            status = "experimental" if reasons else "promoted"
        except Exception as exc:
            # Provider errors can contain keys/URLs. Store a safe failure category.
            payload.update(reasons=["evaluation_failed"], error_type=type(exc).__name__)
            status = "failed"
        payload["promotion_status"] = "promoted" if status == "promoted" else "experimental"
        run_id = self.repository.append(scope.key, "evaluation", status, payload)
        return {"run_id": run_id, **payload}

    def eligibility(self, scope: Scope, *, as_of: datetime) -> dict:
        rows = self.repository.history(scope.key, "evaluation")
        reason = "no_matching_validation"
        if rows:
            latest = rows[0]
            record = latest["payload"]
            created = datetime.fromisoformat(latest["created_at"])
            if record["policy"] != self.policy.model_dump(mode="json"):
                reason = "policy_changed"
            elif not created <= as_of <= created + timedelta(days=self.policy.valid_days):
                reason = "validation_expired_or_not_yet_available"
            elif latest["status"] == "promoted":
                return {"status": "promoted", "validation_run_id": latest["id"], "reasons": []}
            else:
                reason = "latest_evaluation_did_not_pass"
        return {"status": "experimental", "validation_run_id": None, "reasons": [reason]}

    def forecast(self, provider, prepared, *, symbol: str) -> dict:
        scope = Scope(
            symbol=symbol,
            currency=prepared.currency,
            timezone=prepared.timezone,
            adjustment_policy=prepared.adjustment_policy,
            horizon=len(prepared.future_timestamps),
            context=len(prepared.candles),
            model_fingerprint=fingerprint(provider),
        )
        quality = self.eligibility(scope, as_of=prepared.as_of)
        payload = {"scope": scope.model_dump(mode="json"), "quality": quality}
        payload["input_hash"] = hashlib.sha256(prepared.model_dump_json().encode()).hexdigest()
        payload["configuration"] = provider.config.model_dump(mode="json")
        try:
            result = provider.forecast(prepared)
            result = dict(result, quality=quality, research_only=quality["status"] != "promoted")
            json.dumps(result, allow_nan=False)
            payload.update(result=result, limitations=result.get("warnings", []))
            status = "completed"
        except Exception as exc:
            payload.update(
                error_type=type(exc).__name__, limitations=["Inference failed; no usable forecast."]
            )
            status = "failed"
        run_id = self.repository.append(scope.key, "forecast", status, payload)
        return {"run_id": run_id, "status": status, **payload}

    def visible_forecasts(self, scope: Scope, *, experimental: bool = False) -> list[dict]:
        rows = self.repository.history(scope.key, "forecast")
        if experimental:
            return rows
        current = self.eligibility(scope, as_of=datetime.now(UTC))
        return [
            r
            for r in rows
            if r["status"] == "completed"
            and current["status"] == "promoted"
            and r["payload"]["quality"]["status"] == "promoted"
        ]
