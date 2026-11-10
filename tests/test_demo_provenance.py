"""Real demo pipeline and immutable provenance across report/history/export formats."""

import io
import json
import socket
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from financial_ai.api import create_app
from financial_ai.domain.research_mode import saved_mode
from financial_ai.workflow.demo import handler
from financial_ai.workflow.local_worker import process_one


def test_default_demo_report_chart_index_and_restart(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Demo must not call network providers")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    app = create_app(tmp_path / "research.db")
    client = TestClient(app)
    run = client.post("/api/v1/research-runs", json={"ticker": "AAPL"}).json()["id"]
    assert process_one(app.state.runner, handler).status == "completed"
    assert process_one(app.state.runner, handler) is None
    report = client.get(f"/api/v1/research-runs/{run}/reports/latest").json()
    assert report["research_mode"] == "synthetic"
    assert report["model_configuration"]["research_mode"] == "synthetic"
    assert any("39.0%" in f["summary"] for s in report["sections"] for f in s["findings"])
    # Index storage is shared with the API; source text exists without calling an LLM.
    import sqlite3

    with sqlite3.connect(tmp_path / "research.index.db") as db:
        assert db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] > 0
    client = TestClient(create_app(tmp_path / "research.db"))
    assert client.get("/api/v1/research-runs").json()[0]["research_mode"] == "synthetic"
    saved = client.get(f"/api/v1/research-runs/{run}/history").json()
    assert datetime.fromisoformat(saved["report"]["as_of"]) == datetime.fromisoformat(
        report["as_of"]
    )
    report["as_of"] = saved["report"]["as_of"]
    assert saved["report"] == report
    assert (
        len(next(s for s in saved["snapshots"] if s["lane"] == "ohlcv")["payload"]["candles"]) == 60
    )
    base = f"/api/v1/research-runs/{run}/export?version=1"
    bundle = client.get(base + "&format=json").json()
    assert bundle["report"] == report and len(bundle["charts"]) == 1
    assert "SYNTHETIC" in bundle["charts"][0]["reference"]["title"]
    assert "Research mode: synthetic" in client.get(base + "&format=md").text
    response = client.get(base + "&format=pdf")
    assert response.status_code == 200
    pdf = PdfReader(io.BytesIO(response.content))
    assert "Research mode: synthetic" in "\n".join(p.extract_text() for p in pdf.pages)
    assert any(page.images for page in pdf.pages)


def test_saved_versions_keep_mode_and_old_reports_remain_unknown(tmp_path):
    app = create_app(tmp_path / "research.db")
    client = TestClient(app)
    run = UUID(client.post("/api/v1/research-runs", json={"ticker": "MSFT"}).json()["id"])
    for version, mode in enumerate((None, "synthetic", "live"), start=1):
        config = {"composer": "fixture"}
        if mode:
            config["research_mode"] = mode
        app.state.repository.upsert_report(
            report_id=uuid4(),
            run_id=run,
            version=version,
            as_of=datetime(2025, 1, 1, tzinfo=UTC),
            model_config=config,
            decision_brief=["Versioned test report"],
            sections=[],
            evidence_links={},
        )
    # Current snapshots must not relabel an older report's provenance.
    app.state.repository.upsert_snapshot(run, "quote", "completed", {"synthetic": True})
    for version, expected in ((1, "unknown"), (2, "synthetic"), (3, "live")):
        saved = client.get(f"/api/v1/research-runs/{run}/history?version={version}").json()
        assert saved["run"]["research_mode"] == saved["report"]["research_mode"] == expected
        base = f"/api/v1/research-runs/{run}/export?version={version}"
        assert client.get(base + "&format=json").json()["report"]["research_mode"] == expected
        assert f"Research mode: {expected}" in client.get(base + "&format=md").text
        pdf = PdfReader(io.BytesIO(client.get(base + "&format=pdf").content))
        assert f"Research mode: {expected}" in "\n".join(p.extract_text() for p in pdf.pages)
    assert client.get("/api/v1/research-runs").json()[0]["research_mode"] == "live"
    assert (
        client.get(f"/api/v1/research-runs/{run}/reports/latest").json()["research_mode"] == "live"
    )
    with app.state.database.connect() as db:
        old = db.execute(
            "SELECT model_config_json FROM reports WHERE run_id=? AND version=1", (str(run),)
        ).fetchone()[0]
    assert "research_mode" not in json.loads(old)  # no silent database backfill


@pytest.mark.parametrize(
    "value", [None, "bad-json", {}, {"research_mode": []}, {"research_mode": "mixed"}]
)
def test_missing_or_invalid_mode_is_unknown(value):
    assert saved_mode(value) == "unknown"
