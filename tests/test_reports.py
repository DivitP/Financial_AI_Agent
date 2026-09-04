from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from financial_ai.agents.models import AgentFinding
from financial_ai.api import create_app
from financial_ai.domain.models import AssetType, Evidence, EvidenceKind, Instrument, ResearchRun
from financial_ai.reporting import EvidenceBackedReportComposer, EvidenceLink
from financial_ai.storage import Database, ResearchRepository


def test_composer_persists_all_material_claim_links_and_api_returns_them(tmp_path) -> None:
    database = Database(tmp_path / "report.db")
    database.migrate_to_latest()
    repository = ResearchRepository(database)
    now, instrument_id, run_id, evidence_id = (
        datetime(2026, 9, 4, tzinfo=UTC),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    with database.transaction() as connection:
        repository.add_instrument(
            Instrument(
                id=instrument_id, symbol="AAPL", asset_type=AssetType.EQUITY, currency="USD"
            ),
            connection,
        )
        repository.add_run(
            ResearchRun(
                id=run_id,
                instrument_id=instrument_id,
                requested_at=now,
                provider_config_version="test",
            ),
            connection,
        )
        repository.add_evidence(
            Evidence(
                id=evidence_id,
                run_id=run_id,
                provider="sec",
                kind=EvidenceKind.FILING,
                retrieved_at=now,
                locator="10-k",
                content_hash="hash",
            ),
            connection,
        )
    report = EvidenceBackedReportComposer().compose(
        run_id=run_id,
        sections={
            "Fundamentals": [
                AgentFinding(summary="Revenue evidence is available.", evidence_ids=[evidence_id])
            ]
        },
        evidence_links=[
            EvidenceLink(evidence_id=evidence_id, exact_url="https://www.sec.gov/example")
        ],
        as_of=now,
        model_config={"composer": "deterministic-v1", "llm": "disabled"},
    )
    EvidenceBackedReportComposer().persist(report, repository)
    assert (
        repository.report_evidence_links(report.id)[str(evidence_id)]
        == "https://www.sec.gov/example"
    )

    app = create_app(tmp_path / "report.db")
    response = TestClient(app).get(f"/api/v1/research-runs/{run_id}/reports/latest")
    assert response.status_code == 200
    assert response.json()["evidence_links"][str(evidence_id)] == "https://www.sec.gov/example"


def test_composer_rejects_material_findings_without_exact_evidence_links() -> None:
    evidence_id = uuid4()
    with pytest.raises(ValueError, match="exact evidence"):
        EvidenceBackedReportComposer().compose(
            run_id=uuid4(),
            sections={
                "Technical": [AgentFinding(summary="Unlinked claim", evidence_ids=[evidence_id])]
            },
            evidence_links=[],
            as_of=datetime(2026, 9, 4, tzinfo=UTC),
        )
