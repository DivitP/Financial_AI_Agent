from __future__ import annotations

from types import SimpleNamespace


def test_search_agent_extracts_exact_urls(import_main, monkeypatch) -> None:
    main = import_main

    class FakeExecutor:
        def invoke(self, _payload):
            return {
                "output": "Research summary\n- https://example.com/one\nhttps://example.com/two"
            }

    monkeypatch.setattr(main, "search_agent_executor", FakeExecutor())

    result = main.run_search_agent("aapl")

    assert result.name == "research"
    assert result.ticker == "aapl"
    assert result.sources == ["https://example.com/one", "https://example.com/two"]


def test_fundamental_agent_declares_legacy_provider_sources(import_main, monkeypatch) -> None:
    main = import_main

    class FakeExecutor:
        def invoke(self, _payload):
            return {"output": "Fundamental summary"}

    monkeypatch.setattr(main, "fundamental_agent_executor", FakeExecutor())

    result = main.run_fundamental_agent("MSFT")

    assert result.name == "fundamental"
    assert result.content == "Fundamental summary"
    assert result.sources == ["https://financialmodelingprep.com/", "https://finance.yahoo.com/"]


def test_research_and_fundamental_run_persists_offline_results(
    import_main, monkeypatch, tmp_path
) -> None:
    main = import_main
    search = main.AgentResult("research", "AAPL", "News evidence", ["https://example.com/news"])
    fundamental = main.AgentResult(
        "fundamental", "AAPL", "Financial evidence", ["https://example.com/financials"]
    )
    monkeypatch.setattr(
        "financial_ai.reporting_legacy.build_live_research",
        lambda _ticker, _path, **_kwargs: [
            (r.name, r.content, r.sources) for r in (search, fundamental)
        ],
    )

    output = main.run_research_and_fundamental_agents("AAPL", str(tmp_path / "runtime"))
    stored = output["vectorstore"].similarity_search_with_relevance_scores("AAPL evidence", k=5)

    assert "Research Analysis" in output["report_md"]
    assert output["report_md"].startswith("## Fundamental Analysis")
    assert not (tmp_path / "runtime" / "vectorstore.db").exists()
    assert len(stored) == 2


def test_technical_analysis_flow_uses_agent_summary_and_images(import_main, monkeypatch) -> None:
    main = import_main

    class FakeTechnicalAgent:
        def __init__(self, ticker, period):
            self.ticker = ticker
            self.period = period

        def calculate_all_indicators(self):
            return None

        def get_analysis_summary(self):
            return {
                "symbol": "AAPL",
                "current_price": 100.0,
                "daily_change": 2.0,
                "daily_change_pct": 2.04,
                "volatility_atr": 1.5,
                "volume_ratio": 1.2,
                "rsi": 55.0,
                "signals": {"RSI": "NEUTRAL"},
                "forecast_trend": "Bullish",
                "forecast_confidence": 0.6,
                "analysis_date": "2026-08-13",
            }

        def generate_technical_analysis_png(self):
            return b"technical-image"

        def simple_forecast(self, days):
            assert days == 30
            return {"forecast_prices": [101.0]}

        def generate_forecast_png(self, forecast):
            assert forecast["forecast_prices"] == [101.0]
            return b"forecast-image"

    monkeypatch.setattr(main, "TechnicalAnalysisAgent", FakeTechnicalAgent)

    result = main.run_technical_agent("aapl")

    assert "TECHNICAL ANALYSIS REPORT - AAPL" in result.content
    assert "<<IMAGE:TECH_ANALYSIS>>" in result.content
    assert "<<IMAGE:FORECAST>>" in result.content


def test_unscoped_legacy_rag_is_refused(import_main):
    import pytest
    from financial_ai.storage.report_evidence import ReportScopeError

    with pytest.raises(ReportScopeError, match="report_id"):
        import_main.answer_question_with_rag(object(), "GOOG", "What news?")
