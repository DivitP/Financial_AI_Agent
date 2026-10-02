"""Hand-calculated synthetic goldens, citation controls and fixture prompt evaluations."""

import asyncio
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest

from financial_ai.agents.models import AgentFinding
from financial_ai.analysis.etf import ETFHolding, ETFProfile, analyze_etf, research_sections
from financial_ai.analysis.fundamentals import (
    FinancialPeriod,
    StatementValue,
    analyze_financial_quality,
)
from financial_ai.analysis.valuation import ValuationInput, analyze_valuation
from financial_ai.domain.models import AssetType
from financial_ai.llm.contracts import ChatResponse
from financial_ai.prompts import MalformedModelResponse, StructuredPromptExecutor
from financial_ai.reporting import EvidenceBackedReportComposer, EvidenceLink

CORPUS = json.loads((Path(__file__).parent / "fixtures/system/corpus.json").read_text())


@pytest.mark.parametrize("case", CORPUS["cases"], ids=lambda case: case["ticker"])
def test_financial_goldens(case):
    asset = AssetType(case["asset_type"])
    if asset == AssetType.ETF:
        holdings = tuple(
            ETFHolding(f"FIX{i}", "Synthetic constituent", Decimal(weight), "Technology")
            for i, weight in enumerate(case["weights"])
        )
        result = analyze_etf(ETFProfile(Decimal("0.001"), holdings, Decimal("100000"), None))
        assert result.top_ten_weight == Decimal(case["expected_top_weight"])
        assert result.concentration_hhi == Decimal(case["expected_hhi"])
        assert "earnings" not in research_sections(asset)
    else:
        profit = case["gross_profit"]
        metrics = analyze_financial_quality(
            [
                FinancialPeriod(
                    "2025",
                    revenue=StatementValue(case["revenue"], "usd_millions"),
                    gross_profit=None if profit is None else StatementValue(profit, "usd_millions"),
                )
            ]
        )
        assert metrics["revenue"].value == case["revenue"] * 1_000_000
        margin = metrics["gross_margin"]
        if case["expected_margin"] is None:
            assert not margin.available
        else:
            assert margin.display() == case["expected_margin"]
        pe = analyze_valuation(
            ValuationInput(market_cap=case["market_cap"], net_income=case["net_income"])
        )["price_to_earnings"]
        assert pe.value == case["expected_pe"]


@pytest.mark.parametrize("case", CORPUS["cases"], ids=lambda case: case["ticker"])
def test_citations_and_prompt_contracts(case, isolated_budget):
    ticker = case["ticker"]
    evidence = uuid5(NAMESPACE_URL, "fixture/" + ticker)
    exact_url = f"https://example.test/{ticker}/filing#risk"
    wording = f"{ticker}: {case['scenario']} (synthetic fixture)."
    finding = AgentFinding(summary=wording, evidence_ids=[evidence])
    composer = EvidenceBackedReportComposer()
    arguments: dict[str, Any] = dict(
        run_id=uuid5(NAMESPACE_URL, "run/" + ticker),
        sections={"Fixture": [finding]},
        as_of=datetime.fromisoformat(CORPUS["as_of"]),
    )
    report = composer.compose(
        **arguments, evidence_links=[EvidenceLink(evidence_id=evidence, exact_url=exact_url)]
    )
    assert report.sections[0].findings[0].summary == wording
    with pytest.raises(ValueError, match="exact evidence"):
        composer.compose(**arguments, evidence_links=[])

    class Model:
        provider = "fixture"
        model = "release-fixture-v1"

        def __init__(self, valid):
            self.valid, self.calls = valid, 0

        async def complete(self, messages, *, token_budget):
            self.calls += 1
            assert token_budget == 400
            content = (
                json.dumps(
                    {
                        "summary": wording,
                        "evidence_ids": [str(evidence)],
                        "limitations": ["Synthetic data only"],
                    }
                )
                if self.valid
                else "{}"
            )
            return ChatResponse(content=content, provider=self.provider, model=self.model)

    valid = Model(True)
    response = asyncio.run(
        StructuredPromptExecutor(valid).execute("research_brief", {"evidence": wording})
    )
    assert response.output.model_dump()["evidence_ids"] == [str(evidence)]
    assert response.prompt_version == "1.0.0" and response.model == valid.model
    invalid = Model(False)
    with pytest.raises(MalformedModelResponse):
        asyncio.run(
            StructuredPromptExecutor(invalid).execute("research_brief", {"evidence": wording})
        )
    assert invalid.calls == 2
