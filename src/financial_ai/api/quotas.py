"""Fail-fast API throttling including streaming connections, without trusting proxy IPs."""

import asyncio
import re

from starlette.responses import JSONResponse

from financial_ai.quotas import QuotaExceeded


def quota_response(error):
    return JSONResponse(
        {
            "error": {"code": "quota_exceeded", "message": str(error)},
            "retry_after": error.retry_after,
        },
        status_code=429,
        headers={"Retry-After": str(error.retry_after)},
    )


class QuotaMiddleware:
    def __init__(self, app, quotas):
        self.app, self.quotas = app, quotas

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)
        # Cancellation remains usable even when the application is saturated.
        cancel_run = scope["method"] == "POST" and re.fullmatch(
            r"/api/v1/research-runs/[a-fA-F0-9-]{36}/cancel", scope["path"]
        )
        cancel_job = scope["method"] == "DELETE" and re.fullmatch(
            r"/api/v1/research-jobs/[a-fA-F0-9-]{36}", scope["path"]
        )
        if cancel_run or cancel_job:
            return await self.app(scope, receive, send)
        started = False

        async def tracked_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            self.quotas.consume("api", "API requests", self.quotas.settings.api_requests_per_minute)
            match = re.search(r"/research-runs/([a-fA-F0-9-]{36})(?:/|$)", scope["path"])
            with self.quotas.context(match[1] if match else None):
                with self.quotas.slot("API requests", self.quotas.settings.api_concurrency):
                    # Shorter than the crash-recovery lease; streams reconnect normally.
                    await asyncio.wait_for(self.app(scope, receive, tracked_send), timeout=540)
        except QuotaExceeded as error:
            if started:
                raise
            await quota_response(error)(scope, receive, send)
