from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from financial_ai.analysis.decision import (
    DecisionFramework,
    EvidenceStrength,
    RegisterItem,
    Scenario,
    ScenarioName,
    SensitivityRow,
    ThesisInvalidation,
    evidence_strength,
    scenario_probabilities_are_omitted,
)


NOW = datetime(2026, 8, 30, tzinfo=UTC)


def test_decision_framework_is_dated_evidence_first_and_has_no_uncalibrated_probabilities() -> None:
    evidence = uuid4()
    catalyst = RegisterItem(
        "Earnings release",
        NOW,
        "Reported results may validate margins.",
        (evidence,),
        EvidenceStrength.MODERATE,
    )
    risk = RegisterItem(
        "Demand slowdown",
        None,
        "Volume may miss the base-case assumption.",
        (evidence,),
        EvidenceStrength.WEAK,
    )
    invalidation = ThesisInvalidation(
        "Revenue declines for two consecutive periods.", (evidence,), "revenue_growth"
    )
    scenarios = tuple(
        Scenario(
            name, f"{name.value} case", ("Documented assumption",), (invalidation,), (evidence,)
        )
        for name in ScenarioName
    )
    framework = DecisionFramework(
        (catalyst,),
        (risk,),
        scenarios,
        (SensitivityRow("Revenue growth", "-5%", "5%", "12%", "percent", (evidence,)),),
    )
    assert framework.catalysts[0].due_at == NOW
    assert scenario_probabilities_are_omitted()
    assert evidence_strength((evidence,), 2) is EvidenceStrength.STRONG


def test_decision_framework_rejects_missing_scenarios_and_unsupported_citations() -> None:
    with pytest.raises(ValueError, match="exactly bull"):
        DecisionFramework((), (), (Scenario(ScenarioName.BULL, "bull", (), (), ()),), ())
    with pytest.raises(ValueError, match="cannot cite"):
        RegisterItem("Unsupported", None, "No source", (uuid4(),), EvidenceStrength.UNSUPPORTED)
