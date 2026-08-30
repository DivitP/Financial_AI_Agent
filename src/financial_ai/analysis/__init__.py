"""Deterministic financial analysis and validated forecasting services."""

from financial_ai.analysis.fundamentals import analyze_financial_quality
from financial_ai.analysis.earnings import EarningsScorecard
from financial_ai.analysis.guidance import GuidanceStatement
from financial_ai.analysis.news import cluster_articles
from financial_ai.analysis.macro import select_macro_series
from financial_ai.analysis.positioning import build_positioning_context
from financial_ai.analysis.etf import analyze_etf, research_sections
from financial_ai.analysis.quality import assess_data_quality
from financial_ai.analysis.technical import analyze_technical_regime
from financial_ai.analysis.decision import DecisionFramework
from financial_ai.analysis.sentiment import LocalFinanceSentiment
from financial_ai.analysis.peers import compare_company
from financial_ai.analysis.valuation import analyze_valuation

__all__ = [
    "EarningsScorecard",
    "DecisionFramework",
    "GuidanceStatement",
    "LocalFinanceSentiment",
    "analyze_etf",
    "assess_data_quality",
    "analyze_technical_regime",
    "analyze_financial_quality",
    "analyze_valuation",
    "compare_company",
    "cluster_articles",
    "select_macro_series",
    "build_positioning_context",
    "research_sections",
]
