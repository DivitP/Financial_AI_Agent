import importlib
import json
import logging
import socket
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pydantic import SecretStr

from settings import Settings
from financial_ai.api import create_app
from financial_ai.data.http import SharedHttpClient, HttpRequest, HttpResponse
from financial_ai.storage.repositories import ProviderRequest


def test_console_allowlist_hides_secrets_and_never_probes(tmp_path, monkeypatch, caplog):
    sentinel = "fixture-private-value-not-a-real-key"
    settings = Settings.model_construct(
        enable_fmp=True,
        fmp_api_key=SecretStr(sentinel),
        groq_api_key=SecretStr(sentinel),
        groq_model=sentinel,
        local_llm_model=sentinel,
        local_llm_base_url="https://user:" + sentinel + "@example.invalid",
    )
    monkeypatch.setattr(
        importlib.import_module("financial_ai.api.app"), "get_settings", lambda: settings
    )
    app = create_app(tmp_path / "console.db")
    client = TestClient(app)
    run = UUID(client.post("/api/v1/research-runs", json={"ticker": "AAPL"}).json()["id"])
    now = datetime.now(UTC)
    for status, timestamp in (
        (200, now - timedelta(hours=1)),
        (429, now),
        (429, now - timedelta(days=2)),
    ):
        app.state.repository.add_provider_request(
            ProviderRequest(
                id=uuid4(),
                run_id=run,
                provider="fmp",
                request_kind=sentinel,
                requested_at=timestamp,
                completed_at=timestamp,
                status_code=status,
                error_message=sentinel,
                raw_artifact_id=sentinel,
            )
        )

    def forbidden(*args, **kwargs):
        raise AssertionError("Console cannot contact providers or create jobs")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(app.state.runner, "create", forbidden)
    caplog.set_level(logging.DEBUG)
    response = client.get("/api/v1/settings/health", headers={"X-Correlation-ID": sentinel})
    assert response.status_code == 200
    result = response.json()
    assert sentinel not in response.text + str(response.headers) + caplog.text
    assert response.headers["cache-control"] == "no-store"
    UUID(response.headers["x-correlation-id"])
    fmp = next(p for p in result["providers"] if p["provider"] == "fmp")
    assert fmp["enabled"] and fmp["credential_configured"]
    assert fmp["recorded_requests"] == 3 and fmp["rate_limit_responses_24h"] == 1
    assert fmp["quota_warnings"] and fmp["last_successful_request"]
    assert "unverified" in fmp["free_tier_status"]
    assert result["cache"]["state"] == "unobserved"
    assert all("not probed" in m["availability"] for m in result["models"])
    assert client.post("/api/v1/settings/health", json={"secret": sentinel}).status_code == 405


def test_cache_summary_only_exposes_counts_and_expiry(tmp_path, monkeypatch):
    clock = [0.0]
    secret = "private-cache-payload"
    http = SharedHttpClient(
        lambda *args: HttpResponse(200, {"secret": secret}, secret.encode()),
        cache_ttl_seconds=10,
        monotonic=lambda: clock[0],
    )
    request = HttpRequest(
        "fmp", "https://example.invalid/?apikey=" + secret, headers={"Authorization": secret}
    )
    http.fetch(request)
    http.fetch(request)
    summary = http.health_summary()
    assert summary["hits"] == 1 and summary["misses"] == 1
    assert summary["active_entries"] == 1
    clock[0] = 11
    assert http.health_summary()["expired_entries"] == 1
    assert secret not in json.dumps(http.health_summary())
    app = create_app(tmp_path / "cache.db")
    app.state.provider_http_client = http
    result = TestClient(app).get("/api/v1/settings/health").json()
    assert result["cache"]["state"] == "observed"
    assert result["cache"]["expired_entries"] == 1
    assert secret not in json.dumps(result)
