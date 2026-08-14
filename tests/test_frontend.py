from __future__ import annotations


def test_api_ask_returns_json_from_mocked_rag(import_frontend, monkeypatch) -> None:
    frontend = import_frontend
    monkeypatch.setattr(frontend, "get_vectorstore", lambda _path: object())
    monkeypatch.setattr(
        frontend,
        "answer_question_with_rag",
        lambda _store, ticker, question, k: {
            "answer": f"{ticker}: {question}",
            "sources": ["https://example.com/evidence"],
        },
    )

    response = frontend.app.test_client().post(
        "/api/ask", json={"ticker": "AAPL", "question": "What changed?"}
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
        lambda _ticker, _path: {"report_md": "## Research\nOffline report"},
    )

    class FakeThread:
        daemon = False

        def __init__(self, target, args):
            self.target = target
            self.args = args

        def start(self):
            return None

    monkeypatch.setattr(frontend.threading, "Thread", FakeThread)

    response = frontend.app.test_client().post("/run", data={"ticker": "aapl"})

    assert response.status_code == 200
    assert b"Offline report" in response.data
    assert b"AAPL" in response.data
