"""Content-free HTTP tracing, including streaming-response lifetimes."""

from uuid import uuid4

from financial_ai.observability import identifier, observe, telemetry_context


class TelemetryMiddleware:
    def __init__(self, app, database):
        self.app, self.database = app, database

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        correlation = identifier(headers.get(b"x-correlation-id", b"").decode("latin1")) or str(
            uuid4()
        )
        scope.setdefault("state", {})["correlation_id"] = correlation
        parts = scope.get("path", "").split("/")
        run_id = (
            identifier(parts[4])
            if len(parts) > 4 and parts[1:4] == ["api", "v1", "research-runs"]
            else None
        )
        with telemetry_context(self.database, run_id, correlation):
            with observe("api", "api") as event:

                async def traced_send(message):
                    if message["type"] == "http.response.start":
                        event["status_code"] = message["status"]
                        event["outcome"] = "error" if message["status"] >= 400 else "ok"
                    await send(message)

                await self.app(scope, receive, traced_send)
