"""Shared browser boundary policy; not a substitute for authentication."""

import re
from urllib.parse import urlsplit

import bleach  # type: ignore[import-untyped]
import markdown  # type: ignore[import-untyped]
from bs4 import BeautifulSoup
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


CSP = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def safe_link(value):
    if not isinstance(value, str) or re.search(r"[\x00-\x20\x7f\\]", value):
        return None
    try:
        url = urlsplit(value)
        if (
            url.scheme.lower() in ("https", "http")
            and url.hostname
            and not url.username
            and not url.password
        ):
            return value
    except ValueError:
        pass
    return None


def sanitized_markdown(value):
    cleaned = bleach.clean(
        markdown.markdown(value or "", extensions=["tables", "fenced_code", "sane_lists"]),
        tags={
            "p",
            "h1",
            "h2",
            "h3",
            "h4",
            "ul",
            "ol",
            "li",
            "strong",
            "em",
            "blockquote",
            "pre",
            "code",
            "a",
            "br",
            "hr",
            "table",
            "thead",
            "tbody",
            "tr",
            "th",
            "td",
            "details",
            "summary",
        },
        attributes=lambda tag, name, val: tag == "a" and name == "href" and bool(safe_link(val)),
        protocols={"http", "https"},
        strip=True,
    )
    document = BeautifulSoup(cleaned, "html.parser")
    for table in document.find_all("table"):
        wrapper = document.new_tag(
            "div",
            attrs={
                "class": "report-table",
                "role": "region",
                "tabindex": "0",
                "aria-label": "Research data table",
            },
        )
        table.wrap(wrapper)
        for header in table.select("thead th"):
            header["scope"] = "col"
    return str(document)


def rejected_browser_request(method, headers, origins):
    origin = headers.get("origin")
    if origin is not None and origin not in origins:
        return True
    if headers.get("sec-fetch-site") == "cross-site":
        return True
    if method not in ("GET", "HEAD", "OPTIONS"):
        browser = origin is not None or headers.get("sec-fetch-site") is not None
        if browser and headers.get("x-requested-with") != "FinancialAI":
            return True
        content_type = headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type and content_type != "application/json":
            return True
    return False


class SecurityBoundary(BaseHTTPMiddleware):
    def __init__(self, app, origins, hosts):
        super().__init__(app)
        self.origins, self.hosts = origins, hosts

    async def dispatch(self, request, call_next):
        if request.url.hostname not in self.hosts or rejected_browser_request(
            request.method, request.headers, self.origins
        ):
            response = JSONResponse(
                {
                    "error": {
                        "code": "request_forbidden",
                        "message": "Request origin, host or request headers are not permitted.",
                    }
                },
                status_code=403,
            )
        else:
            try:
                response = await call_next(request)
            except Exception:
                response = JSONResponse(
                    {
                        "error": {
                            "code": "internal_error",
                            "message": "An unexpected error occurred.",
                        }
                    },
                    status_code=500,
                )
        for key, value in HEADERS.items():
            response.headers.setdefault(key, value)
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response
