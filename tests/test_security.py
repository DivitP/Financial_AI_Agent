import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from financial_ai.security import SecurityBoundary, safe_link, sanitized_markdown


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,test",
        "//evil.test",
        "https://user:pass@example.com",
        "https://example.com\n",
        "java\tscript:alert(1)",
    ],
)
def test_unsafe_links(url):
    assert safe_link(url) is None


def test_markdown_is_sanitized():
    result = sanitized_markdown(
        '<script>alert(1)</script><img src=x onerror=alert(1)><svg onload=alert(1)></svg><a href="javascript:alert(1)" onclick="alert(1)">bad</a>\n\n[Good](https://example.com/filing)'
    )
    for forbidden in ("<script", "<img", "<svg", "onerror", "onclick", "javascript:"):
        assert forbidden not in result
    assert 'href="https://example.com/filing"' in result


def test_api_browser_boundary():
    app = FastAPI()
    app.add_middleware(SecurityBoundary, origins=["http://testserver"], hosts=["testserver"])

    @app.post("/change")
    def change():
        return {"ok": True}

    @app.get("/failure")
    def failure():
        raise ValueError("secret")

    client = TestClient(app)
    for headers in (
        {"Origin": "https://evil.test"},
        {"Origin": "null"},
        {"Origin": "http://testserver"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Host": "evil.test"},
        {"Content-Type": "text/plain"},
    ):
        response = client.post("/change", headers=headers)
        assert response.status_code == 403
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert "access-control-allow-origin" not in response.headers
    assert client.post("/change", json={}).status_code == 200
    assert (
        client.post(
            "/change",
            json={},
            headers={"Origin": "http://testserver", "X-Requested-With": "FinancialAI"},
        ).status_code
        == 200
    )
    for path in ("/missing", "/failure"):
        response = client.get(path)
        assert "script-src 'self'" in response.headers["Content-Security-Policy"]
        assert "secret" not in response.text


def test_legacy_form_requires_session_token(import_frontend):
    client = import_frontend.app.test_client()
    assert client.post("/run", data={"ticker": "AAPL"}).status_code == 403
    assert client.get("/").headers["X-Frame-Options"] == "DENY"
    assert client.post("/run", data={"ticker": "AAPL", "csrf_token": "☃"}).status_code == 403
    assert client.get("/api/not-found").is_json


def test_legacy_has_no_html_sinks():
    from pathlib import Path

    script = Path("frontend/static/legacy.js").read_text()
    assert "innerHTML" not in script
    assert "insertAdjacentHTML" not in script


@pytest.mark.parametrize("path", ["/run", "/ask"])
def test_legacy_native_forms_preserve_origin_and_require_csrf(import_frontend, path):
    client = import_frontend.app.test_client()
    origin = "http://localhost:8501"
    page = client.get("/", base_url=origin)
    # no-referrer would turn native form navigation's Origin into "null".
    assert page.headers["Referrer-Policy"] == "same-origin"
    with client.session_transaction(base_url=origin) as session:
        token = session["csrf_token"]
    headers = {"Origin": origin, "Sec-Fetch-Site": "same-origin"}
    # Blank input exercises form validation without calling live providers.
    response = client.post(path, base_url=origin, data={"csrf_token": token}, headers=headers)
    assert response.status_code == 200
    assert response.headers["Referrer-Policy"] == "same-origin"
    assert client.post(path, base_url=origin, data={}, headers=headers).status_code == 403
    for bad_headers in (
        {"Origin": "null", "Sec-Fetch-Site": "same-origin"},
        {"Origin": "https://evil.test", "Sec-Fetch-Site": "cross-site"},
        {"Origin": origin, "Sec-Fetch-Site": "cross-site"},
        {"Origin": origin, "Host": "evil.test"},
    ):
        assert (
            client.post(
                path, base_url=origin, data={"csrf_token": token}, headers=bad_headers
            ).status_code
            == 403
        )
