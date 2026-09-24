from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4
import socket

import pytest
from fastapi.testclient import TestClient
from pydantic import AnyUrl

from financial_ai.api import create_app
from financial_ai.analysis.portfolio import exposures, path_risk, risk_comparison
from financial_ai.domain.models import Evidence, EvidenceKind


def history(reverse=False):
    sessions = [date(2026, 1, 1) + timedelta(days=i) for i in range(45)]
    sessions = [d for d in sessions if d.weekday() < 5]
    value = 100.0
    bars = []
    for i, day in enumerate(sessions):
        value *= 1 + (0.01 if i % 2 else -0.01) * (-1 if reverse else 1)
        bars.append({"session": day.isoformat(), "close": value})
    return {
        "bars": bars,
        "currency": "USD",
        "timezone": "America/New_York",
        "interval": "1d",
        "adjustment_policy": "split",
    }


def test_known_correlations_drawdowns_and_candidate_risk():
    data = {"A": {"ohlcv": history()}, "B": {"ohlcv": history(True)}}
    result = risk_comparison(data, {"A": 1.0}, {"A": 0.5, "B": 0.5})
    assert result["available"]
    assert result["correlations"]["A"]["B"] == pytest.approx(-1)
    assert result["after"]["daily_volatility"] < 1e-12
    assert result["change"]["daily_volatility"] < 0
    assert path_risk({"A": [-0.2, 0.25]}, {"A": 1})["max_drawdown"] == pytest.approx(-0.2)
    constant = history()
    for bar in constant["bars"]:
        bar["close"] = 100
    assert (
        risk_comparison({"A": {"ohlcv": constant}}, {"A": 1}, {"A": 1})["correlations"]["A"]["A"]
        is None
    )


def test_incompatible_and_missing_data_are_not_silently_dropped():
    for key, value in (
        ("currency", "EUR"),
        ("adjustment_policy", "raw"),
        ("timezone", ""),
        ("interval", "1wk"),
    ):
        data = {"A": {"ohlcv": history()}, "B": {"ohlcv": history() | {key: value}}}
        assert not risk_comparison(data, {"A": 1}, {"A": 0.5, "B": 0.5})["available"]
    data = {"A": {"ohlcv": history()}, "B": {"ohlcv": history()}}
    data["B"]["ohlcv"]["bars"].pop(5)
    assert "sessions" in risk_comparison(data, {"A": 1}, {"A": 0.5, "B": 0.5})["reason"]
    assert not risk_comparison({"A": {}}, {"A": 1}, {"A": 1})["available"]


def test_exposure_coverage_is_not_invented():
    data = {
        "A": {
            "asset_type": "etf",
            "etf": {"sector_exposure": {"Tech": 0.6}},
            "factors": {"model": "fixture-v1", "loadings": {"market": 1.2}},
        },
        "B": {},
    }
    result = exposures(data, {"A": 0.5, "B": 0.5})
    assert result["sector_weights"] == {"Tech": 0.3, "Unknown": 0.7}
    assert result["factor_loadings"]["fixture-v1:market"] == {
        "weighted_loading": 0.6,
        "covered_weight": 0.5,
    }


def test_portfolio_api_uses_only_saved_data_and_validates_weights(tmp_path, monkeypatch):
    app = create_app(tmp_path / "portfolio.db")
    client = TestClient(app)
    for ticker in ("AAPL", "MSFT"):
        run = UUID(client.post("/api/v1/research-runs", json={"ticker": ticker}).json()["id"])
        app.state.repository.update_run_status(run, "completed")
        eid = uuid4()
        app.state.repository.add_evidence(
            Evidence(
                id=eid,
                run_id=run,
                provider="fixture",
                kind=EvidenceKind.FILING,
                retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
                locator=str(eid),
                content_hash="fixture",
                exact_url=AnyUrl(f"https://example.com/prices/{ticker}"),
            )
        )
        app.state.repository.upsert_snapshot(
            run, "ohlcv", "completed", history(ticker == "MSFT") | {"evidence_ids": [str(eid)]}
        )

    def forbidden(*args, **kwargs):
        raise AssertionError("No network or job creation")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(app.state.runner, "create", forbidden)
    payload = {
        "holdings": [{"ticker": "AAPL", "weight": 100.0}],
        "candidate": {"ticker": "MSFT", "weight": 50.0},
    }
    response = client.post("/api/v1/portfolio-context", json=payload)
    assert response.status_code == 200
    assert response.json()["historical_risk"]["available"]
    assert response.json()["before"]["hhi"] == 1
    assert response.json()["after"]["hhi"] == 0.5
    for bad in (-10, 0, 100, 101):
        assert (
            client.post(
                "/api/v1/portfolio-context",
                json=payload | {"candidate": {"ticker": "MSFT", "weight": bad}},
            ).status_code
            == 422
        )
    assert (
        client.post(
            "/api/v1/portfolio-context",
            json=payload | {"holdings": [{"ticker": "AAPL", "weight": 99}]},
        ).status_code
        == 422
    )
    assert (
        client.post("/api/v1/portfolio-context", json=payload | {"execute": True}).status_code
        == 422
    )
    same = client.post(
        "/api/v1/portfolio-context", json=payload | {"candidate": {"ticker": "AAPL", "weight": 10}}
    ).json()
    assert same["after"]["weights"] == {"AAPL": 1}
