"""Read-only allowlisted diagnostics. Never serialize settings or provider payloads."""

from contextlib import closing
from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter, Request, Response

from financial_ai.data.http import SharedHttpClient


def installed(package):
    try:
        version(package)
        return True
    except PackageNotFoundError:
        return False


def console_snapshot(database, settings, client=None):
    flags = {
        name: bool(getattr(settings, name))
        for name in (
            "enable_fmp",
            "enable_groq",
            "enable_local_llm",
            "enable_kronos",
            "kronos_allow_downloads",
        )
    }
    configured = {
        "fmp": settings.enable_fmp,
        "groq": settings.enable_groq,
        "ollama": settings.enable_local_llm,
        "kronos": settings.enable_kronos,
    }
    providers = []
    with closing(database.connect()) as db:
        for name in ("fmp", "groq", "ollama", "kronos", "sec", "yfinance", "openbb", "gdelt"):
            row = db.execute(
                """SELECT
                MAX(CASE WHEN status_code BETWEEN 200 AND 299 THEN
                    strftime('%Y-%m-%dT%H:%M:%SZ',completed_at) END) AS last_success,
                SUM(CASE WHEN status_code=429 AND julianday(requested_at)>=julianday('now','-1 day') THEN 1 ELSE 0 END) AS rate_limited,
                COUNT(*) AS recorded_requests
                FROM provider_requests WHERE provider=?""",
                (name,),
            ).fetchone()
            providers.append(
                {
                    "provider": name,
                    "enabled": configured.get(name),
                    "selection": "configured flag"
                    if name in configured
                    else "workflow-selected; no global enable flag",
                    "credential_configured": bool(settings.fmp_api_key)
                    if name == "fmp"
                    else bool(settings.groq_api_key)
                    if name == "groq"
                    else None,
                    "free_tier_status": "local execution; hardware costs apply"
                    if name in ("ollama", "kronos")
                    else "unverified; account plan and remaining quota are not queried",
                    "last_successful_request": row["last_success"],
                    "recorded_requests": row["recorded_requests"],
                    "quota_warnings": ["Rate-limit responses recorded in the last 24 hours"]
                    if row["rate_limited"]
                    else [],
                    "rate_limit_responses_24h": row["rate_limited"] or 0,
                }
            )
    # Model names can contain arbitrary user-supplied strings. Never echo them.
    models = [
        {
            "provider": name,
            "enabled": configured[name],
            "identifier": "configured (identifier hidden)",
            "dependencies_installed": all(installed(package) for package in packages),
            "availability": "not probed; installed dependencies do not establish model or service availability",
        }
        for name, packages in (
            ("groq", ("langchain-groq",)),
            ("ollama", ("langchain-ollama",)),
            ("kronos", ("torch", "transformers")),
        )
    ]
    return {
        "providers": providers,
        "models": models,
        "feature_flags": flags,
        "cache": client.health_summary()
        if isinstance(client, SharedHttpClient)
        else {
            "state": "unobserved",
            "reason": "No shared HTTP client attached to this API process",
        },
        "configured_defaults": {
            "cache_ttl_seconds": settings.cache_ttl_seconds,
            "request_timeout_seconds": settings.request_timeout_seconds,
            "provider_rate_limit_per_minute": settings.provider_rate_limit_per_minute,
        },
        "notice": "Read-only local diagnostics. No provider calls, model loading, or account/quota probes. Request history may be incomplete; absence of warnings does not mean quota remains. Configured defaults may differ from client overrides.",
    }


def console_router(database, settings):
    router = APIRouter(tags=["settings"])

    @router.get("/api/v1/settings/health")
    def health(request: Request, response: Response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return console_snapshot(
            database, settings, getattr(request.app.state, "provider_http_client", None)
        )

    return router
