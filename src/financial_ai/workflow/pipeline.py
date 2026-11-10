"""Evidence-first worker assembly, shared by local and Redis execution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid5, NAMESPACE_URL

from financial_ai.providers.collected import CollectedLane

from financial_ai.agents.models import AgentFinding
from financial_ai.analysis.technical import PricePoint, analyze_technical_regime
from financial_ai.domain.models import Evidence, EvidenceKind, SourceTier
from financial_ai.reporting import EvidenceBackedReportComposer, EvidenceLink
from financial_ai.retrieval.index import ResearchIndex, SourceText
from financial_ai.storage.artifacts import FileSystemArtifactStore
from financial_ai.workflow.failures import failure_reason


class ResearchPipeline:
    lanes = ("instrument", "quote", "ohlcv", "filings", "statements", "news")

    def __init__(self, repository, run_id, collector, *, runtime: Path):
        self.repository, self.run_id, self.collector = repository, run_id, collector
        self.run = repository.get_run(run_id)
        if self.run is None:
            raise KeyError("Unknown research run")
        self.artifacts = FileSystemArtifactStore(runtime / "artifacts")
        self.index = ResearchIndex(
            repository.database,
            runtime / "research.index.db"
            if repository.database.postgres
            else repository.database.path.with_suffix(".index.db"),
        )

    def __call__(self, step):
        {"collect": self.collect, "analyze": self.analyze, "report": self.report}[step]()

    def collect(self):
        from financial_ai.data.documents import document_text
        from financial_ai.observability import observe
        from financial_ai.quotas import current_quotas

        prior = {r["lane"]: r for r in self.repository.snapshots(self.run_id)}
        for lane in self.lanes:
            if self.repository.get_run(self.run_id)["status"] == "cancelled":
                return
            if prior.get(lane) and prior[lane]["status"] == "completed":
                continue
            if self.run["asset_type"] == "etf" and lane in {"filings", "statements"}:
                self.repository.upsert_snapshot(
                    self.run_id,
                    lane,
                    "completed",
                    {
                        "status": "not_applicable",
                        "limitations": [
                            "Corporate financial statement collection is not applicable to ETF research."
                        ],
                    },
                )
                continue
            try:
                with observe("node", lane):
                    current_quotas().charge("calls")
                    source = CollectedLane.model_validate(self.collector.collect(lane, self.run))
                    if lane == "instrument" and source.payload.get("asset_type") in {
                        "equity",
                        "etf",
                    }:
                        asset = source.payload["asset_type"]
                        exchange = source.payload.get("exchange", "")
                        ident = str(
                            uuid5(NAMESPACE_URL, f"{self.run['symbol']}:{asset}:{exchange}")
                        )
                        with self.repository.database.transaction() as db:
                            db.execute(
                                "INSERT INTO instruments(id,symbol,asset_type,name,exchange,currency) VALUES (?,?,?,?,?,?) ON CONFLICT(symbol,asset_type,exchange) DO NOTHING",
                                (
                                    ident,
                                    self.run["symbol"],
                                    asset,
                                    source.payload.get("name"),
                                    exchange,
                                    source.payload["currency"],
                                ),
                            )
                            saved = db.execute(
                                "SELECT id FROM instruments WHERE symbol=? AND asset_type=? AND exchange=?",
                                (self.run["symbol"], asset, exchange),
                            ).fetchone()
                            db.execute(
                                "UPDATE research_runs SET instrument_id=? WHERE id=?",
                                (saved["id"], str(self.run_id)),
                            )
                        self.run = self.repository.get_run(self.run_id)
                    # External content must pass the untrusted-document boundary before indexing.
                    text = document_text(source.text)
                    checksum = hashlib.sha256(text.encode()).hexdigest()
                    evidence_id = uuid5(self.run_id, f"{lane}:{source.url}:{checksum}")
                    artifact = self.artifacts.put_text(source.model_dump_json(), category="raw")
                    evidence = Evidence(
                        id=evidence_id,
                        run_id=self.run_id,
                        provider=source.provider,
                        kind=EvidenceKind.MARKET_DATA
                        if lane in {"quote", "ohlcv"}
                        else EvidenceKind.DATASET,
                        retrieved_at=source.retrieved_at,
                        locator=lane,
                        content_hash=checksum,
                        excerpt=text,
                        raw_artifact_id=artifact,
                        exact_url=source.url,
                        source_tier=SourceTier.SYNTHETIC
                        if source.payload.get("synthetic") is True
                        else SourceTier.OFFICIAL
                        if source.provider == "sec"
                        else SourceTier.REPUTABLE,
                    )
                    self.repository.add_evidence(evidence)
                    warnings = (
                        []
                        if lane == "ohlcv"
                        else self.index.index(
                            SourceText(
                                ticker=self.run["symbol"],
                                run_id=self.run_id,
                                evidence_id=evidence_id,
                                source_url=source.url,
                                kind="article" if lane == "news" else "filing",
                                period="as retrieved",
                                published_at=source.published_at,
                                retrieved_at=source.retrieved_at,
                                text=text,
                            )
                        )
                    )
                    payload = {
                        **source.payload,
                        "provider": source.provider,
                        "retrieved_at": source.retrieved_at.isoformat(),
                        "evidence_id": str(evidence_id),
                        "url": str(source.url),
                        "limitations": source.limitations + warnings,
                    }
                    self.repository.upsert_snapshot(self.run_id, lane, "completed", payload)
            except Exception as error:
                self.repository.upsert_snapshot(
                    self.run_id, lane, "failed", None, failure_reason(error)
                )
        # Partial outputs remain inspectable. A report must not hide failed coverage.
        rows = self.repository.snapshots(self.run_id)
        if not any(r["lane"] == "quote" and r["status"] == "completed" for r in rows):
            raise RuntimeError("Quote collection failed; retained other lane evidence")

    def analyze(self):
        from financial_ai.analysis.sec_periods import financial_periods
        from financial_ai.analysis.fundamentals import analyze_financial_quality

        rows = {r["lane"]: r for r in self.repository.snapshots(self.run_id)}
        statements = rows.get("statements")
        if statements and statements["status"] == "completed":
            data = json.loads(statements["payload_json"])
            if data.get("status") == "not_applicable":
                data = None
        else:
            data = None
        if data:
            periods = financial_periods(data.get("facts", []))
            metrics = analyze_financial_quality(periods)
            self.repository.upsert_snapshot(
                self.run_id,
                "fundamentals",
                "completed",
                {
                    "metrics": {
                        name: {**asdict(metric), "display": metric.display()}
                        for name, metric in metrics.items()
                    },
                    "evidence_id": data["evidence_id"],
                    "limitations": [
                        "Latest-filed annual USD facts only; missing metrics are not estimated."
                    ],
                    "synthetic": data.get("synthetic", False),
                },
            )
        row = rows.get("ohlcv")
        if row and row["status"] == "completed":
            payload = json.loads(row["payload_json"])
            points = [
                PricePoint(datetime.fromisoformat(c["timestamp"]), c["close"], c.get("volume"))
                for c in payload.get("candles", [])
            ]
            result = analyze_technical_regime(points)
            self.repository.upsert_snapshot(
                self.run_id,
                "technical",
                "completed",
                {
                    **asdict(result),
                    "evidence_id": payload["evidence_id"],
                    "limitations": [
                        "Descriptive historical indicators, not a trading signal or forecast."
                    ],
                    "synthetic": payload.get("synthetic", False),
                },
            )
            # Persist the chart before the report captures its immutable snapshot manifest.
            import io
            from matplotlib.figure import Figure

            figure = Figure(figsize=(7, 3))
            axis = figure.subplots()
            axis.plot([p.timestamp for p in points], [p.close for p in points])
            title = (
                "SYNTHETIC SAMPLE - " if payload.get("synthetic") else ""
            ) + "Historical closing prices"
            axis.set(
                title=title,
                ylabel=payload.get("currency", "Currency unavailable"),
                xlabel="Observation date",
            )
            figure.autofmt_xdate()
            figure.tight_layout()
            image = io.BytesIO()
            figure.savefig(image, format="png")
            artifact_id = self.artifacts.put_bytes(
                image.getvalue(), category="charts", suffix=".png"
            )
            self.repository.upsert_snapshot(
                self.run_id,
                "charts",
                "completed",
                {
                    "synthetic": payload.get("synthetic", False),
                    "charts": [
                        {
                            "artifact_id": artifact_id,
                            "title": title,
                            "evidence_ids": [payload["evidence_id"]],
                            "adjustment_policy": payload.get("adjustment_policy", "unknown"),
                            "as_of": payload.get("as_of", "unknown"),
                        }
                    ],
                },
            )

    def report(self):
        from contextlib import closing

        snapshots = self.repository.snapshots(self.run_id)
        failures = [r["lane"] for r in snapshots if r["status"] == "failed"]
        with closing(self.repository.database.connect()) as db:
            evidence = db.execute(
                "SELECT * FROM evidence WHERE run_id=? ORDER BY id", (str(self.run_id),)
            ).fetchall()
        sections: dict[str, list[AgentFinding]] = {}
        links = []
        for row in evidence:
            # Extractive composition: no free-form model claims can bypass source checking.
            ident = UUID(row["id"])
            finding = AgentFinding(
                summary=row["excerpt"][:1500],
                evidence_ids=[ident],
                limitations=["Extractive source summary; not personalized investment advice."]
                + (
                    ["SYNTHETIC SAMPLE: invented data, not real financial evidence."]
                    if row["source_tier"] == "synthetic"
                    else []
                )
                + (["Unavailable lanes: " + ", ".join(failures)] if failures else []),
            )
            sections.setdefault(row["locator"], []).append(finding)
            links.append(EvidenceLink(evidence_id=ident, exact_url=row["exact_url"]))
        for row in snapshots:
            if row["lane"] not in {"technical", "fundamentals"} or row["status"] != "completed":
                continue
            data = json.loads(row["payload_json"])
            if row["lane"] == "technical":
                summary = f"Historical technical conditions: {data['trend']}; momentum {data['momentum']}; regime {data['regime']}."
            else:
                summary = "Annual financial quality: " + "; ".join(
                    f"{name}: {metric['display']}" for name, metric in data["metrics"].items()
                )
            sections[row["lane"]] = [
                AgentFinding(
                    summary=("SYNTHETIC SAMPLE — invented data. " if data.get("synthetic") else "")
                    + summary,
                    evidence_ids=[UUID(data["evidence_id"])],
                    limitations=data["limitations"],
                )
            ]
        composer = EvidenceBackedReportComposer()
        mode = (
            "synthetic"
            if evidence and all(r["source_tier"] == "synthetic" for r in evidence)
            else "live"
            if evidence
            and all(
                r["provider"] in {"yahoo", "sec", "rss"} and r["source_tier"] != "synthetic"
                for r in evidence
            )
            else "unknown"
        )
        previous = self.repository.latest_report(self.run_id)
        report = composer.compose(
            run_id=self.run_id,
            sections=sections,
            evidence_links=links,
            as_of=datetime.now(UTC),
            version=int(previous["version"]) + 1 if previous else 1,
            model_config={
                "composer": "extractive-pipeline-v1",
                "llm": "disabled",
                "research_mode": mode,
            },
        )
        composer.persist(report, self.repository)
        if failures:
            raise RuntimeError("Research coverage incomplete; partial report and evidence retained")


def handler(repository, run_id):
    from settings import get_settings
    from financial_ai.providers.live import LiveCollector

    settings = get_settings()
    if not settings.enable_live_research:
        raise ValueError("Set ENABLE_LIVE_RESEARCH=true and SEC_USER_AGENT before live research")
    runtime = (
        settings.persist_dir / "scaled"
        if repository.database.postgres
        else repository.database.path.parent
    )
    return ResearchPipeline(repository, run_id, LiveCollector(settings), runtime=runtime)
