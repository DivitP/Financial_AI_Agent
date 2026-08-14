from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from financial_ai.domain import Evidence, Instrument, MetricObservation, ResearchRun
from financial_ai.domain.models import AssetType, EvidenceKind


NOW = datetime(2026, 8, 14, tzinfo=UTC)


def test_domain_models_accept_valid_research_records() -> None:
    instrument = Instrument(id=uuid4(), symbol="aapl", asset_type=AssetType.EQUITY, currency="usd")
    run = ResearchRun(
        id=uuid4(),
        instrument_id=instrument.id,
        requested_at=NOW,
        provider_config_version="2026-08-14",
    )
    evidence = Evidence(
        id=uuid4(),
        run_id=run.id,
        provider="sec",
        kind=EvidenceKind.FILING,
        retrieved_at=NOW,
        locator="https://www.sec.gov/Archives/example",
        content_hash="abc123",
    )
    metric = MetricObservation(
        id=uuid4(),
        run_id=run.id,
        instrument_id=instrument.id,
        metric_name="revenue",
        value=100.0,
        unit="USD",
        observed_at=NOW,
        provider="sec",
        evidence_id=evidence.id,
    )

    assert instrument.symbol == "AAPL"
    assert metric.evidence_id == evidence.id


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ({"asset_type": "bond"}, "asset_type"),
        ({"currency": ""}, "currency"),
    ],
)
def test_instrument_rejects_unsupported_asset_types_and_empty_currency(payload, error) -> None:
    base: dict[str, Any] = {
        "id": uuid4(),
        "symbol": "AAPL",
        "asset_type": AssetType.EQUITY,
        "currency": "USD",
    }
    base.update(payload)
    with pytest.raises(ValidationError, match=error):
        Instrument(**base)


def test_evidence_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        Evidence(
            id=uuid4(),
            run_id=uuid4(),
            provider="sec",
            kind=EvidenceKind.FILING,
            retrieved_at=datetime(2026, 8, 14),
            locator="filing",
            content_hash="hash",
        )


def test_metric_rejects_missing_unit_and_invalid_evidence_identifier() -> None:
    payload: dict[str, Any] = {
        "id": uuid4(),
        "run_id": uuid4(),
        "instrument_id": uuid4(),
        "metric_name": "revenue",
        "value": 1.0,
        "observed_at": NOW,
        "provider": "sec",
        "evidence_id": uuid4(),
    }
    with pytest.raises(ValidationError, match="unit"):
        MetricObservation(**payload, unit="")
    invalid_identifier = {**payload, "evidence_id": "not-a-uuid"}
    with pytest.raises(ValidationError, match="evidence_id"):
        MetricObservation(**invalid_identifier, unit="USD")
