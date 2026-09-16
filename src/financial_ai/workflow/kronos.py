"""Optional bounded forecast lane; never a prerequisite for the stock report."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from financial_ai.domain.forecast import KronosResponse, KronosForecastData
from financial_ai.kronos.inference import InferenceConfig, LocalKronosProvider
from financial_ai.kronos.preprocessing import Candle, CorporateAction, Session, prepare_candles
from financial_ai.kronos.quality import KronosQuality, PromotionPolicy, Scope, fingerprint
from financial_ai.storage.model_runs import ModelRunRepository
from financial_ai.workflow.jobs import LocalResearchJobRunner


class KronosWorkflowNode:
    def read(self, run_id, *, include_experimental=False):
        rows = {r["lane"]: r for r in self.repository.snapshots(run_id)}
        row = rows.get("kronos")
        if row is None:
            return KronosResponse(status="pending")
        if not row["payload_json"]:
            return KronosResponse(status="failed", warning="Optional forecast unavailable")
        response = KronosResponse.model_validate_json(row["payload_json"])
        eligible = False
        if response.model_run_id:
            with self.repository.database.connect() as db:
                audit = db.execute(
                    "SELECT payload_json FROM model_runs WHERE id=? AND kind='forecast'",
                    (response.model_run_id,),
                ).fetchone()
            if audit:
                scope = Scope.model_validate(json.loads(audit["payload_json"])["scope"])
                eligible = (
                    self.quality.eligibility(scope, as_of=datetime.now(UTC))["status"] == "promoted"
                )
        if not eligible or response.quality != "promoted":
            response.quality = "experimental"
            if response.forecast:
                response.forecast.research_only = True
                response.forecast.quality = {"status": "experimental"}
            if not include_experimental:
                response.forecast = None
                if response.status == "completed":
                    response.warning = (
                        "Experimental research forecast; opt in to view unvalidated output."
                    )
        return response

    def __init__(self, repository, settings, *, provider=None, quality=None):
        self.repository, self.settings = repository, settings
        self.provider = provider or LocalKronosProvider.from_settings(
            settings,
            config=InferenceConfig(
                device=settings.kronos_device,
                timeout_seconds=settings.kronos_timeout_seconds,
                sample_count=8,
            ),
        )
        # No policy file means a fresh, unmatched policy: experimental only.
        policy = (
            PromotionPolicy.model_validate_json(Path(settings.kronos_policy_path).read_text())
            if settings.kronos_policy_path
            else PromotionPolicy(
                version="experimental-default",
                frozen_at=datetime.now(UTC),
            )
        )
        self.quality = quality or KronosQuality(ModelRunRepository(repository.database), policy)

    def _event(self, run_id, status, attempt=0, warning=None):
        with self.repository.database.transaction() as db:
            row = db.execute(
                "SELECT id FROM jobs WHERE run_id=? ORDER BY created_at DESC LIMIT 1",
                (str(run_id),),
            ).fetchone()
            if row:
                LocalResearchJobRunner._event(
                    db,
                    row["id"],
                    "progress",
                    {
                        "lane": "kronos",
                        "status": status,
                        "attempt": attempt,
                        "percentage": 100
                        if status in {"completed", "failed", "skipped", "disabled", "cancelled"}
                        else 0,
                        "retry_state": "retrying" if status == "retrying" else None,
                        "warning": warning,
                    },
                )

    def _save(self, run_id, response):
        self.repository.upsert_snapshot(
            run_id,
            "kronos",
            "failed" if response.status == "failed" else "completed",
            response.model_dump(mode="json"),
        )
        self._event(run_id, response.status, warning=response.warning)
        return response

    async def run(self, run_id):
        run = self.repository.get_run(run_id)
        options = json.loads(run["scope_json"])
        if not options.get("include_kronos") or not self.settings.enable_kronos:
            return self._save(
                run_id,
                KronosResponse(
                    status="disabled",
                    warning="Kronos requires request opt-in and ENABLE_KRONOS=true.",
                ),
            )
        if run["status"] == "cancelled":
            return self._save(run_id, KronosResponse(status="cancelled"))
        self._event(run_id, "preparing")
        try:
            snapshots = {r["lane"]: r for r in self.repository.snapshots(run_id)}
            raw = json.loads(snapshots["ohlcv"]["payload_json"])["kronos_input"]
            prepared = prepare_candles(
                [Candle.model_validate(c) for c in raw["candles"]],
                sessions=[Session.model_validate(s) for s in raw["sessions"]],
                actions=[CorporateAction.model_validate(a) for a in raw["actions"]],
                as_of=datetime.fromisoformat(raw["as_of"]),
                timezone=raw["timezone"],
                currency=raw["currency"],
                provider=raw["provider"],
                calendar_source=raw["calendar_source"],
                input_policy=raw["input_policy"],
                actions_complete=raw["actions_complete"],
                horizon=options.get("forecast_horizon", 5),
            )
        except Exception:
            return self._save(
                run_id,
                KronosResponse(
                    status="skipped",
                    warning="Complete validated OHLCV, exchange schedule and corporate-action coverage are required.",
                ),
            )
        prepared = prepared.model_copy(update={"instrument": run["symbol"]})
        key = hashlib.sha256(
            json.dumps(
                {
                    "symbol": run["symbol"],
                    "prepared": prepared.model_dump(mode="json"),
                    "model": fingerprint(self.provider),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        # Provider cache is content-keyed; always recheck promotion rather than
        # returning a checkpoint's possibly stale quality status.
        for attempt in range(1, self.settings.kronos_max_retries + 2):
            if self.repository.get_run(run_id)["status"] == "cancelled":
                return self._save(run_id, KronosResponse(status="cancelled", cache_key=key))
            self._event(run_id, "running", attempt)
            self.repository.upsert_graph_checkpoint(
                run_id, "kronos", "running", attempt, {"cache_key": key}
            )
            try:
                record = await asyncio.to_thread(
                    self.quality.forecast, self.provider, prepared, symbol=run["symbol"]
                )
                if self.repository.get_run(run_id)["status"] == "cancelled":
                    return self._save(run_id, KronosResponse(status="cancelled", cache_key=key))
                if record["status"] != "completed":
                    raise RuntimeError("Local forecast unavailable")
                result = KronosForecastData.model_validate(record["result"])
                response = KronosResponse(
                    status="completed",
                    quality=record["quality"]["status"],
                    cache_key=key,
                    model_run_id=record["run_id"],
                    forecast=result,
                )
                self.repository.upsert_graph_checkpoint(
                    run_id, "kronos", "completed", attempt, response.model_dump(mode="json")
                )
                return self._save(run_id, response)
            except Exception:
                self.repository.upsert_graph_checkpoint(
                    run_id,
                    "kronos",
                    "failed",
                    attempt,
                    {"cache_key": key},
                    error_message="Local forecast unavailable",
                )
                if attempt <= self.settings.kronos_max_retries:
                    self._event(
                        run_id, "retrying", attempt, "Local forecast unavailable; retry scheduled."
                    )
                    await asyncio.sleep(min(2 ** (attempt - 1), 4))
        return self._save(
            run_id,
            KronosResponse(
                status="failed",
                cache_key=key,
                warning="Kronos unavailable; other research remains usable.",
            ),
        )
