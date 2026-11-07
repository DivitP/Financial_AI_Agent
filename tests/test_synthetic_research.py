"""Deterministic invented data and safe, inspectable exact citations; no network."""

import json
import socket
from uuid import UUID, uuid4
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from financial_ai.api import create_app
from financial_ai.analysis.sec_periods import financial_periods
from financial_ai.analysis.fundamentals import analyze_financial_quality
from financial_ai.providers.synthetic import SyntheticCollector, SYMBOLS, LANES, AS_OF, NOTICE
from financial_ai.workflow.local_worker import process_one
from financial_ai.workflow.synthetic import handler
from settings import Settings


@pytest.fixture(autouse=True)
def no_outbound_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Synthetic collection must never use the network")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_all_sample_lanes_are_reproducible_and_coherent(symbol):
    collector = SyntheticCollector()
    sources = {lane: collector.collect(lane, {"symbol": symbol}) for lane in LANES}
    for lane, source in sources.items():
        assert (
            source.model_dump_json()
            == SyntheticCollector().collect(lane, {"symbol": symbol}).model_dump_json()
        )
        assert source.retrieved_at == source.published_at == AS_OF
        assert source.payload["synthetic"] is True
        assert source.payload["currency"] == source.payload["unit"] == "USD"
        assert source.payload["timezone"] == "UTC"
        assert source.payload["adjustment_policy"]
        assert NOTICE in source.text
        assert source.provider == "synthetic-v1"
        assert "sec.gov" not in source.model_dump_json()
        ident = UUID(urlsplit(str(source.url)).path.rsplit("/", 1)[-1])
        assert collector.lookup(ident) == source
    candles = sources["ohlcv"].payload["candles"]
    assert len(candles) == 60
    assert len({c["timestamp"] for c in candles}) == 60
    assert [c["timestamp"] for c in candles] == sorted(c["timestamp"] for c in candles)
    assert sources["quote"].payload["price"] == candles[-1]["close"]
    assert sources["quote"].payload["as_of"] == candles[-1]["timestamp"]
    assert all(
        c["low"] <= c["open"] <= c["high"] and c["low"] <= c["close"] <= c["high"] for c in candles
    )
    if symbol not in {"SPY", "QQQ"}:
        facts = sources["statements"].payload["facts"]
        metrics = analyze_financial_quality(financial_periods(facts))
        assert metrics["gross_margin"].display() == "39.0%"
        assert all(f["form"] == "SYNTHETIC-ANNUAL" for f in facts)
    else:
        assert sources["statements"].payload["facts"] == []


@pytest.mark.parametrize("symbol", ["", "UNKNOWN", "aapl", "AAPL<script>", "../.env"])
def test_unsupported_symbols_do_not_fall_back_to_live_sources(symbol):
    with pytest.raises(ValueError, match="Unsupported synthetic symbol"):
        SyntheticCollector().collect("quote", {"symbol": symbol})


def test_invalid_lane_origin_and_record_fail_closed():
    with pytest.raises(ValueError, match="lane"):
        SyntheticCollector().collect("unknown", {"symbol": "AAPL"})
    with pytest.raises(KeyError):
        SyntheticCollector().lookup(uuid4())
    for origin in (
        "file:///etc/passwd",
        "https://user:password@example.test",
        "http://localhost:8000/path",
        "http://localhost:8000?x=1",
    ):
        with pytest.raises(ValueError):
            Settings(_env_file=None, synthetic_evidence_origin=origin)


def test_caller_mutation_cannot_change_catalog():
    collector = SyntheticCollector()
    first = collector.collect("quote", {"symbol": "AAPL"})
    first.payload["price"] = -1
    assert collector.collect("quote", {"symbol": "AAPL"}).payload["price"] == 159


def test_synthetic_annual_form_requires_explicit_label():
    facts = SyntheticCollector().collect("statements", {"symbol": "AAPL"}).payload["facts"]
    for fact in facts:
        fact.pop("synthetic")
    assert financial_periods(facts) == []


def test_synthetic_pipeline_persists_report_with_readable_exact_records(tmp_path):
    app = create_app(tmp_path / "research.db")
    client = TestClient(app)
    created = client.post("/api/v1/research-runs", json={"ticker": "AAPL"}).json()
    assert process_one(app.state.runner, handler).status == "completed"
    report = client.get(f"/api/v1/research-runs/{created['id']}/reports/latest").json()
    assert len(report["evidence_links"]) == 6
    for link in report["evidence_links"].values():
        response = client.get(urlsplit(link).path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert NOTICE in response.text
        assert "sec.gov" not in response.text
    for section in report["sections"]:
        for finding in section["findings"]:
            assert "SYNTHETIC" in finding["summary"]
    with app.state.database.connect() as db:
        rows = db.execute(
            "SELECT source_tier FROM evidence WHERE run_id=?", (created["id"],)
        ).fetchall()
    assert all(row["source_tier"] == "synthetic" for row in rows)
    assert process_one(app.state.runner, handler) is None


def test_record_access_rejects_unknown_malformed_and_mutating_requests(tmp_path):
    client = TestClient(create_app(tmp_path / "research.db"))
    root = "/api/v1/synthetic-evidence/"
    assert client.get(root + str(uuid4())).status_code == 404
    invalid = client.get(root + "not-a-uuid")
    assert invalid.status_code == 422 and "traceback" not in invalid.text.lower()
    source = SyntheticCollector().collect("quote", {"symbol": "AAPL"})
    path = urlsplit(str(source.url)).path
    assert client.post(path, json={}).status_code == 405
    assert client.get(path, headers={"Host": "evil.test"}).status_code == 403
    response = client.get(path, headers={"X-Forwarded-Host": "evil.test"})
    assert response.status_code == 200 and "evil.test" not in response.text
    # This endpoint cannot inspect persisted user evidence, even with a valid UUID.
    assert client.get(root + str(uuid4()) + "?path=.env").status_code == 404


def test_record_content_is_never_rendered_as_html(tmp_path, monkeypatch):
    source = SyntheticCollector().collect("news", {"symbol": "AAPL"})
    source.text = '<script>alert("xss")</script>'
    monkeypatch.setattr(SyntheticCollector, "lookup", lambda *_: source)
    response = TestClient(create_app(tmp_path / "research.db")).get(urlsplit(str(source.url)).path)
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert json.loads(response.text.split("\n\n", 1)[1])["text"] == source.text
