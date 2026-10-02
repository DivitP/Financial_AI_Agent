import asyncio
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from financial_ai.api import create_app
from financial_ai.data.http import SharedHttpClient, HttpRequest, HttpResponse
from financial_ai.quotas import Quotas, QuotaExceeded, complete_chat
from financial_ai.storage.database import Database
from financial_ai.workflow.research import InitialResearchWorkflow
from settings import Settings


def quota_store(tmp_path, **settings):
    db = Database(tmp_path / "quotas.db")
    db.migrate_to_latest()
    return Quotas(db, Settings(_env_file=None, **settings))  # type: ignore[call-arg]


def test_atomic_budget_survives_restart(tmp_path):
    quotas = quota_store(tmp_path, run_call_budget=3)

    def charge(_):
        try:
            with quotas.context("run"):
                quotas.charge("calls")
            return True
        except QuotaExceeded:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(charge, range(12))) == 3
    with Quotas(quotas.database, quotas.settings).context("run"):
        with pytest.raises(QuotaExceeded):
            quotas.charge("calls")


def test_slots_release_and_expired_leases_recover(tmp_path):
    quotas = quota_store(tmp_path)
    with quotas.slot("model", 1):
        with pytest.raises(QuotaExceeded):
            with quotas.slot("model", 1):
                pass
    with pytest.raises(ValueError), quotas.slot("model", 1):
        raise ValueError("fixture")
    with quotas.database.connect() as db:
        db.execute("INSERT INTO quota_leases VALUES ('dead', 'model', 0)")
        db.commit()
    with quotas.slot("model", 1):
        pass


def test_http_cache_does_not_spend_budget_and_429_is_bounded(tmp_path):
    quotas = quota_store(tmp_path, run_call_budget=2)
    transport = Mock(return_value=HttpResponse(200, {}, b"ok"))
    client = SharedHttpClient(transport, quotas=quotas)
    request = HttpRequest("fixture", "https://example.test/doc")
    with quotas.context("run"):
        assert client.fetch(request).body == b"ok"
        assert client.fetch(request).body == b"ok"
        quotas.charge("calls")
        with pytest.raises(QuotaExceeded):
            quotas.charge("calls")
    assert transport.call_count == 1
    transport = Mock(return_value=HttpResponse(429, {"retry-after": "86400"}, b""))
    sleep = Mock()
    client = SharedHttpClient(transport, quotas=quotas, sleep=sleep)
    with pytest.raises(QuotaExceeded):
        client.fetch(request)
    with pytest.raises(QuotaExceeded):
        client.fetch(request)
    assert transport.call_count == 1
    sleep.assert_not_called()


@pytest.mark.parametrize("header", ["nonsense", "NaN", "Infinity", "-5"])
def test_malformed_retry_after_is_finite(header):
    assert (
        0 <= SharedHttpClient._retry_delay(HttpResponse(429, {"Retry-After": header}, b""), 0) <= 1
    )


def test_api_quota_and_queue_backpressure(tmp_path):
    app = create_app(tmp_path / "api.db")
    app.state.quotas.settings = app.state.quotas.settings.model_copy(
        update={"api_requests_per_minute": 1}
    )
    client = TestClient(app)
    assert client.get("/api/v1/research-runs").status_code == 200
    blocked = client.get("/api/v1/research-runs")
    assert blocked.status_code == 429 and blocked.headers["retry-after"]
    assert blocked.json()["error"]["code"] == "quota_exceeded"
    assert client.get("/health").status_code == 200
    app.state.quotas.settings = app.state.quotas.settings.model_copy(
        update={"api_requests_per_minute": 120}
    )
    app.state.runner.quotas.settings = app.state.runner.quotas.settings.model_copy(
        update={"max_pending_jobs": 1}
    )
    run = client.post("/api/v1/research-runs", json={"ticker": "AAPL"}).json()
    response = client.post("/api/v1/research-runs", json={"ticker": "MSFT"})
    assert response.status_code == 429
    with app.state.database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM research_runs").fetchone()[0] == 1
    assert client.post(f"/api/v1/research-runs/{run['id']}/cancel").status_code == 200


def test_repeated_provider_429_stops_after_retry_budget(tmp_path):
    quotas = quota_store(tmp_path)
    transport = Mock(return_value=HttpResponse(429, {}, b""))
    sleep = Mock()
    client = SharedHttpClient(transport, quotas=quotas, max_retries=2, sleep=sleep)
    with pytest.raises(QuotaExceeded):
        client.fetch(HttpRequest("fixture", "https://example.test/"))
    assert transport.call_count == 3
    assert [c.args[0] for c in sleep.call_args_list] == [1, 2]
    with pytest.raises(QuotaExceeded):
        client.fetch(HttpRequest("fixture", "https://example.test/"))
    assert transport.call_count == 3


def test_model_provider_429_cools_down_without_retry(tmp_path):
    quotas = quota_store(tmp_path)

    class ProviderLimited(Exception):
        status_code = 429

    class Model:
        provider = "fixture"
        calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            raise ProviderLimited("Sensitive provider details")

    model = Model()
    with quotas.context("run"):
        for _ in range(2):
            with pytest.raises(QuotaExceeded) as result:
                asyncio.run(complete_chat(model, [], token_budget=10))
            assert "Sensitive" not in str(result.value)
    assert model.calls == 1


def test_model_and_article_budget_prevents_calls(tmp_path):
    quotas = quota_store(tmp_path, run_model_budget=1, run_article_budget=1)

    class Model:
        provider = "fixture"
        calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            return "result"

    model = Model()
    with quotas.context("run"):
        asyncio.run(complete_chat(model, [], token_budget=10))
        with pytest.raises(QuotaExceeded):
            asyncio.run(complete_chat(model, [], token_budget=10))
        from financial_ai.providers.news import budget_articles

        assert budget_articles(["one"]) == ["one"]
        with pytest.raises(QuotaExceeded):
            budget_articles(["two"])
    assert model.calls == 1


def test_exhausted_lane_preserves_successes(tmp_path):
    app = create_app(tmp_path / "partial.db")
    run_id = UUID(
        TestClient(app).post("/api/v1/research-runs", json={"ticker": "AAPL"}).json()["id"]
    )

    async def good():
        return {"source": "fixture"}

    async def limited():
        raise QuotaExceeded("Provider free-tier")

    lanes = {name: good for name in InitialResearchWorkflow.required_lanes}
    lanes["filings"] = limited
    snapshots = asyncio.run(InitialResearchWorkflow(app.state.repository, lanes).run(run_id))
    assert sum(s.status == "completed" for s in snapshots) == 4
    assert "limit reached" in next(s.error for s in snapshots if s.lane == "filings")
    assert app.state.repository.get_run(run_id)["status"] == "failed"


def test_quota_migration_downgrade(tmp_path):
    quotas = quota_store(tmp_path)
    with quotas.context("run"):
        quotas.charge("models")
    quotas.database.migrate_to(10)
    quotas.database.migrate_to_latest()
    with quotas.context("new"):
        quotas.charge("models")
