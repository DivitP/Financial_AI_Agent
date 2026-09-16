"""Local process-isolated inference with a disposable persistent forecast cache."""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from financial_ai.kronos import load_manifest
from financial_ai.kronos.preprocessing import PreparedCandles
from financial_ai.kronos.distribution import summarize_paths


class InferenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    device: Literal["cpu", "mps", "cuda"] = "cpu"
    seed: int = Field(default=0, ge=0, le=2**32 - 1)
    temperature: float = Field(default=1.0, gt=0, le=2)
    top_p: float = Field(default=0.9, gt=0, le=1)
    sample_count: int = Field(default=1, ge=1, le=16)
    timeout_seconds: float = Field(default=120, gt=0, le=600)
    cache_ttl_seconds: int = Field(default=3600, ge=0, le=86400)


class LocalKronosProvider:
    @classmethod
    def from_settings(cls, settings, *, config: InferenceConfig | None = None):
        return cls(
            enabled=settings.enable_kronos,
            assets=settings.kronos_cache_dir,
            source=settings.kronos_source_dir,
            cache=settings.kronos_cache_dir / "forecasts.sqlite3",
            config=config or InferenceConfig(device=settings.kronos_device),
        )

    def __init__(
        self,
        *,
        enabled: bool,
        assets: Path,
        source: Path,
        cache: Path,
        config: InferenceConfig | None = None,
    ):
        self.enabled, self.assets, self.source, self.cache = enabled, assets, source, cache
        self.config = config or InferenceConfig()

    def forecast(self, prepared: PreparedCandles) -> dict:
        if not self.enabled:
            raise ValueError("Kronos is disabled; set ENABLE_KRONOS=true")
        manifest = load_manifest()
        if (
            not 2 <= len(prepared.candles) <= manifest.max_context
            or not 1 <= len(prepared.future_timestamps) <= 512
        ):
            raise ValueError("Invalid forecast context or horizon")
        if len(prepared.historical_timestamps) != len(prepared.candles):
            raise ValueError("Historical timestamp count mismatch")
        times = prepared.historical_timestamps + prepared.future_timestamps
        if any(a >= b for a, b in zip(times, times[1:])):
            raise ValueError("Forecast timestamps must increase")
        if (
            prepared.historical_timestamps[-1] > prepared.as_of
            or prepared.future_timestamps[0] <= prepared.as_of
        ):
            raise ValueError("Forecast timestamps cross the as-of boundary")
        request = {
            "prepared": prepared.model_dump(mode="json"),
            "config": self.config.model_dump(),
            "manifest": manifest.model_dump(mode="json"),
            "adapter_version": "local-v2-paths",
        }
        key = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.cache)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS forecasts(key TEXT PRIMARY KEY, expires REAL, payload TEXT)"
            )
            db.execute("DELETE FROM forecasts WHERE expires<=?", (time.time(),))
            row = db.execute("SELECT payload FROM forecasts WHERE key=?", (key,)).fetchone()
        if row:
            return dict(
                json.loads(row[0]),
                cache_hit=True,
                quality={"status": "experimental"},
                research_only=True,
            )
        request.update(assets=str(self.assets.resolve()), source=str(self.source.resolve()))
        try:
            result = self._execute(request)
            summary = summarize_paths(
                result["paths"],
                sessions=[t.date() for t in prepared.future_timestamps],
                count=self.config.sample_count,
                last_close=prepared.candles[-1].close,
            )
            if result["device"] != self.config.device:
                raise ValueError("Forecast device mismatch")
        except subprocess.TimeoutExpired:
            raise TimeoutError(
                "Kronos timed out; worker terminated and no forecast cached"
            ) from None
        output = {
            "quality": {"status": "experimental"},
            "research_only": True,
            "model_id": manifest.artifacts[0].repository,
            "tokenizer_id": manifest.artifacts[1].repository,
            **summary,
            "path_seeds": [(self.config.seed + i) % 2**32 for i in range(self.config.sample_count)],
            "timestamps": [t.isoformat() for t in prepared.future_timestamps],
            "model_version": manifest.artifacts[0].revision,
            "tokenizer_version": manifest.artifacts[1].revision,
            "source_version": manifest.source.revision,
            "device": result["device"],
            "configuration": self.config.model_dump(),
            "as_of": prepared.as_of.isoformat(),
            "generated_at": datetime.now(UTC).isoformat(),
            "input_hash": key,
            "timezone": prepared.timezone,
            "currency": prepared.currency,
            "adjustment_policy": prepared.adjustment_policy,
            "provider": "kronos-local",
            "units": {"prices": prepared.currency, "volume": "shares"},
            "warnings": prepared.warnings
            + ["Unvalidated model output; not forecast confidence or investment advice."]
            + [
                "Percentile bands and direction frequencies describe model samples, not calibrated probabilities."
            ]
            + (
                ["One path cannot characterize forecast uncertainty."]
                if self.config.sample_count == 1
                else []
            )
            + (
                []
                if all(b.amount is not None for b in prepared.candles)
                else [
                    "Missing turnover encoded as a zero model-input placeholder, not an observation."
                ]
            ),
            "cache_hit": False,
        }
        with closing(sqlite3.connect(self.cache)) as db, db:
            db.execute(
                "INSERT OR REPLACE INTO forecasts VALUES (?, ?, ?)",
                (key, time.time() + self.config.cache_ttl_seconds, json.dumps(output)),
            )
        return output

    def _execute(self, request: dict) -> dict:
        env = dict(
            os.environ,
            HF_HUB_OFFLINE="1",
            TRANSFORMERS_OFFLINE="1",
            PYTHONHASHSEED=str(self.config.seed),
            CUBLAS_WORKSPACE_CONFIG=":4096:8",
        )
        process = subprocess.run(
            self._worker_command(),
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=self.config.timeout_seconds,
            env=env,
        )
        if process.returncode:
            raise RuntimeError(
                "Local Kronos failed; verify optional dependencies, pinned source/assets and device availability"
            )
        return json.loads(process.stdout)

    def _worker_command(self) -> list[str]:
        return [sys.executable, "-m", "financial_ai.kronos.worker"]
