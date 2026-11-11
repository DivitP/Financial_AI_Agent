from __future__ import annotations

import httpx
import pytest
from groq import APIStatusError, AuthenticationError, NotFoundError, RateLimitError


def test_api_ask_returns_json_from_mocked_rag(import_frontend, monkeypatch) -> None:
    frontend = import_frontend
    monkeypatch.setattr(frontend, "get_vectorstore", lambda _path: object())
    monkeypatch.setattr(
        frontend,
        "ask_selected_report",
        lambda _path, ticker, _report, question, _settings: {
            "answer": f"{ticker}: {question}",
            "sources": ["https://example.com/evidence"],
        },
    )

    response = frontend.app.test_client().post(
        "/api/ask", json={"ticker": "AAPL", "question": "What changed?", "report_id": "selected"}
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "answer": "AAPL: What changed?",
        "sources": ["https://example.com/evidence"],
    }


def test_run_route_starts_technical_work_after_mocked_report(import_frontend, monkeypatch) -> None:
    frontend = import_frontend
    monkeypatch.setattr(
        frontend,
        "run_research_and_fundamental_agents",
        lambda _ticker, _path: {
            "report_md": '## Research\nOffline report\n<img src=x onerror="alert(1)"><script>alert(1)</script>'
        },
    )

    class FakeThread:
        daemon = False

        def __init__(self, target, args):
            self.target = target
            self.args = args

        def start(self):
            return None

    monkeypatch.setattr(frontend.threading, "Thread", FakeThread)

    client = frontend.app.test_client()
    client.get("/")
    with client.session_transaction() as session:
        token = session["csrf_token"]
    response = client.post("/run", data={"ticker": "aapl", "csrf_token": token})

    assert response.status_code == 200
    assert b"Offline report" in response.data
    assert b"AAPL" in response.data
    assert b"onerror" not in response.data
    assert b"<script>alert" not in response.data


def test_failed_technical_result_is_not_marked_completed(import_frontend, monkeypatch, tmp_path):
    frontend = import_frontend
    monkeypatch.setattr(
        "financial_ai.analysis.legacy_technical.build_technical_report",
        lambda *_args, **_kwargs: {"status": "error", "text": "History unavailable."},
    )
    frontend.run_optimized_technical_analysis("failed-fixture", "NVDA", str(tmp_path))
    status = frontend.background_tasks.pop("failed-fixture")
    assert status["status"] == "failed"
    assert status["tech_text"] == "History unavailable."
    assert status["tech_image"] is None


def test_valuation_assumptions_are_validated_before_collection(import_frontend, monkeypatch):
    def unexpected(*_args, **_kwargs):
        raise AssertionError("Invalid assumptions must not call a provider")

    monkeypatch.setattr(import_frontend, "run_research_and_fundamental_agents", unexpected)
    client = import_frontend.app.test_client()
    client.get("/")
    with client.session_transaction() as session:
        token = session["csrf_token"]
    response = client.post(
        "/run", data={"ticker": "GOOG", "csrf_token": token, "exit_multiple": "NaN"}
    )
    assert response.status_code == 422
    assert "Check the valuation assumptions" in response.text


@pytest.mark.parametrize("path", ["/run", "/ask"])
@pytest.mark.parametrize(
    ("error_type", "status", "guidance"),
    [
        (NotFoundError, 404, "GROQ_MODEL"),
        (AuthenticationError, 401, "GROQ_API_KEY"),
        (RateLimitError, 429, "limit was reached"),
        (APIStatusError, 500, "provider status"),
    ],
)
def test_groq_failure_shows_safe_actionable_page(
    import_frontend, monkeypatch, path, error_type, status, guidance
):
    frontend = import_frontend
    private = "private-prompt-and-secret-sentinel"
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.groq.com"))
    error = error_type(private, response=response, body={"error": private})

    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(frontend, "run_research_and_fundamental_agents", fail)
    monkeypatch.setattr(frontend, "ask_selected_report", fail)
    monkeypatch.setattr(frontend, "get_vectorstore", lambda _path: object())
    client = frontend.app.test_client()
    client.get("/")
    with client.session_transaction() as session:
        token = session["csrf_token"]
    result = client.post(path, data={"ticker": "AAPL", "question": "Revenue?", "csrf_token": token})
    assert result.status_code == 503
    assert guidance in result.text
    assert private not in result.text
    assert 'role="alert"' in result.text
    assert 'action="/run"' in result.text
    assert result.headers["X-Content-Type-Options"] == "nosniff"


def test_followup_requires_explicit_report_scope(import_frontend):
    client = import_frontend.app.test_client()
    assert (
        client.post("/api/ask", json={"ticker": "GOOG", "question": "What news?"}).status_code
        == 400
    )
    response = client.post(
        "/api/ask", json={"ticker": "GOOG", "question": "What news?", "report_id": "bad"}
    )
    assert response.status_code == 404
    assert "sources" not in response.get_json()


def test_native_followup_reopens_selected_report_and_escapes_source_text(
    import_frontend, monkeypatch, tmp_path
):
    from financial_ai.storage.report_evidence import ReportEvidenceStore

    frontend = import_frontend
    monkeypatch.setattr(
        frontend, "settings", frontend.settings.model_copy(update={"persist_dir": tmp_path})
    )
    store = ReportEvidenceStore(tmp_path / "report_evidence.sqlite3")
    ident = store.create("GOOG")
    store.finalize(ident, "GOOG", "# Preserved selected report")
    monkeypatch.setattr(
        frontend,
        "ask_selected_report",
        lambda *args: dict(
            answer="Verified excerpt",
            claims=[
                dict(
                    classification="publisher-labelled opinion",
                    quote="<script>alert(1)</script>",
                    url="https://publisher.test/article",
                    title="Original article",
                    passage_id="exact-passage",
                    published_at=None,
                )
            ],
        ),
    )
    client = frontend.app.test_client()
    client.get("/")
    with client.session_transaction() as session:
        token = session["csrf_token"]
    result = client.post(
        "/ask",
        data={
            "ticker": "GOOG",
            "report_id": ident,
            "question": "What does the article say?",
            "csrf_token": token,
        },
    )
    assert result.status_code == 200
    html = result.get_data(as_text=True)
    assert "Preserved selected report" in html and ident in html
    assert "&lt;script&gt;" in html and "<script>alert(1)</script>" not in html
    assert "Original article" in html and "exact-passage" in html
