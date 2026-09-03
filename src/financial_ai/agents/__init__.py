"""Agent orchestration over structured evidence, never direct provider facts."""

from financial_ai.agents.events import EventEvidence, NewsEventAnalystNode
from financial_ai.agents.fundamental import FundamentalAnalystNode, verify_numeric_claims
from financial_ai.agents.planner import AssetAwareResearchPlanner, ResearchPlan
from financial_ai.agents.risk import RiskAnalystNode, compose_final_findings
from financial_ai.agents.technical import TechnicalQuantAnalystNode
from financial_ai.agents.verifier import ClaimContradictionVerifier

__all__ = [
    "AssetAwareResearchPlanner",
    "EventEvidence",
    "FundamentalAnalystNode",
    "NewsEventAnalystNode",
    "ResearchPlan",
    "RiskAnalystNode",
    "TechnicalQuantAnalystNode",
    "ClaimContradictionVerifier",
    "compose_final_findings",
    "verify_numeric_claims",
]
