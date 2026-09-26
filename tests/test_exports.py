import io
import json
import socket
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from matplotlib.figure import Figure
from pypdf import PdfReader
from pydantic import AnyUrl

from financial_ai.api import create_app
from financial_ai.domain.models import Evidence, EvidenceKind
from financial_ai.storage.artifacts import FileSystemArtifactStore
from financial_ai.exports import pdf_export


def saved_export(tmp_path):
    app = create_app(tmp_path / "export.db")
    client = TestClient(app)
    run = UUID(client.post("/api/v1/research-runs", json={"ticker": "AAPL"}).json()["id"])
    eid = uuid4()
    repo = app.state.repository
    repo.add_evidence(
        Evidence(
            id=eid,
            run_id=run,
            provider="fixture",
            kind=EvidenceKind.FILING,
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
            locator=str(eid),
            content_hash="fixture",
            exact_url=AnyUrl("https://example.com/filing#revenue"),
        )
    )
    figure = Figure(figsize=(6, 3))
    axis = figure.subplots()
    axis.plot([1, 2, 3, 4], [10, 12, 11, 14])
    axis.set(title="Saved fixture revenue", xlabel="Period", ylabel="USD millions")
    figure.tight_layout()
    image = io.BytesIO()
    figure.savefig(image, format="png")
    store = FileSystemArtifactStore(tmp_path / "artifacts")
    chart_id = store.put_bytes(image.getvalue(), category="charts", suffix=".png")
    repo.upsert_snapshot(
        run,
        "charts",
        "completed",
        {
            "charts": [
                {"artifact_id": chart_id, "title": "Saved revenue", "evidence_ids": [str(eid)]}
            ]
        },
    )
    repo.upsert_report(
        report_id=uuid4(),
        run_id=run,
        version=1,
        as_of=datetime(2026, 1, 1, tzinfo=UTC),
        model_config={"composer": "fixture-v1", "llm": "disabled"},
        decision_brief=["Revenue increased by 39%."],
        sections=[
            {
                "title": "Fundamentals",
                "findings": [
                    {
                        "summary": "Revenue increased by 39%.",
                        "limitations": ["Historical evidence only; not a forecast."],
                        "evidence_ids": [str(eid)],
                        "numeric_claims": [
                            {
                                "metric_name": "growth",
                                "value": 0.39,
                                "unit": "fraction",
                                "evidence_id": str(eid),
                            }
                        ],
                    }
                ],
            }
        ],
        evidence_links={eid: "https://example.com/filing#revenue"},
    )
    return client, app, run, chart_id


def test_exports_exact_version_content_citations_charts_and_no_live_calls(tmp_path, monkeypatch):
    client, app, run, _ = saved_export(tmp_path)
    original = client.get(f"/api/v1/research-runs/{run}/history?version=1").json()["report"]
    app.state.repository.upsert_snapshot(run, "charts", "completed", {"charts": []})

    def forbidden(*args, **kwargs):
        raise AssertionError("Export cannot use providers or jobs")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(app.state.runner, "create", forbidden)
    base = f"/api/v1/research-runs/{run}/export?version=1"
    result = client.get(base + "&format=json")
    bundle = result.json()
    assert bundle["report"] == original
    assert len(bundle["charts"]) == 1
    md = client.get(base + "&format=md").text
    assert json.dumps(original, ensure_ascii=False, indent=2) in md
    assert "data:image/png;base64," in md
    pdf = client.get(base + "&format=pdf")
    assert pdf.status_code == 200
    reader = PdfReader(io.BytesIO(pdf.content))
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert "Revenue increased by 39%." in text
    assert "https://example.com/filing#revenue" in text
    assert "2026-01-01" in text and "fixture-v1" in text
    assert sum(len(page.images) for page in reader.pages) == 1
    assert 'v1.pdf"' in pdf.headers["content-disposition"]
    assert client.get(base.replace("version=1", "version=2")).status_code == 404
    assert client.get(base + "&format=html").status_code == 422
    assert client.get(f"/api/v1/research-runs/{run}/export").status_code == 422


def test_missing_chart_warns_and_unicode_pdf_does_not_silently_replace_text(tmp_path):
    client, _, run, chart_id = saved_export(tmp_path)
    store = FileSystemArtifactStore(tmp_path / "artifacts")
    store._path_for(chart_id, ".png").unlink()
    bundle = client.get(f"/api/v1/research-runs/{run}/export?version=1").json()
    assert bundle["charts"] == []
    assert any("Saved chart unavailable" in w for w in bundle["warnings"])
    bundle["report"]["decision_brief"] = ["Unsupported glyph: \U0001f984"]
    with pytest.raises(ValueError, match="font"):
        pdf_export(bundle)
