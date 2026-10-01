"""Allowlisted, content-free telemetry. Diagnostic failures never fail research."""

import logging
import re
import time
from contextlib import closing, contextmanager
from contextvars import ContextVar
from functools import lru_cache
from uuid import UUID

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

KINDS = frozenset("api workflow node provider model cache run job".split())
COMPONENTS = frozenset(
    """api research instrument resolution quote profile ohlcv filings
statements planner fundamental fundamentals technical events risk verifier verify report
collect analyze kronos sec gdelt yfinance openbb fmp groq ollama article company_ir
approved_rss chat news sentiment valuation peers earnings guidance analysts macro
ownership positioning etf quality decision fixture stream""".split()
)
OUTCOMES = frozenset(
    """ok error cancelled hit miss deduplicated pending running completed
failed partial queued progress warning retry retrying cancellation_requested started recovered""".split()
)
_scope: ContextVar[tuple | None] = ContextVar("telemetry", default=None)


def identifier(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def safe_event(values):
    """A strict schema, not redaction heuristics: unknown strings never leave the process."""
    result = {
        "kind": values.get("kind") if values.get("kind") in KINDS else "api",
        "component": values.get("component") if values.get("component") in COMPONENTS else "other",
        "outcome": values.get("outcome") if values.get("outcome") in OUTCOMES else "error",
        "run_id": identifier(values.get("run_id")),
        "correlation_id": identifier(values.get("correlation_id")),
    }
    for key, maximum in (("duration_ms", 86400000), ("attempt", 1000), ("status_code", 599)):
        value = values.get(key)
        result[key] = value if type(value) in (int, float) and 0 <= value <= maximum else None
    for key, length in (("trace_id", 32), ("span_id", 16)):
        value = values.get(key)
        result[key] = (
            value
            if isinstance(value, str) and re.fullmatch(f"[0-9a-f]{{{length}}}", value)
            else None
        )
    return result


@lru_cache(maxsize=1)
def tracer_provider():
    from settings import get_settings

    provider = TracerProvider(resource=Resource({"service.name": "financial-ai"}))
    if get_settings().telemetry_export_enabled:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        except ImportError:
            raise RuntimeError(
                "Install uv sync --extra observability to enable trace export"
            ) from None
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        import requests

        session = requests.Session()
        session.trust_env = False
        # Nonempty explicit headers prevent fallback to OTEL environment credentials.
        exporter = OTLPSpanExporter(
            endpoint="http://127.0.0.1:4318/v1/traces",
            headers={"User-Agent": "financial-ai-telemetry"},
            timeout=2,
            session=session,
        )
        provider.add_span_processor(BatchSpanProcessor(exporter, max_queue_size=512))
    return provider


@contextmanager
def telemetry_context(database, run_id=None, correlation_id=None, provider=None):
    previous = _scope.get()
    token = _scope.set(
        (
            database,
            identifier(run_id),
            identifier(correlation_id) or (previous[2] if previous else None),
            provider or (previous[3] if previous else tracer_provider()),
        )
    )
    try:
        yield
    finally:
        _scope.reset(token)


def traceparent():
    carrier: dict[str, str] = {}
    TraceContextTextMapPropagator().inject(carrier)
    return carrier.get("traceparent")


def parent_context(value):
    if isinstance(value, str) and re.fullmatch(r"00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}", value):
        return TraceContextTextMapPropagator().extract({"traceparent": value})
    return None


def insert_event(connection, *, run_id=None, **values):
    scope = _scope.get()
    span = trace.get_current_span().get_span_context()
    event = safe_event(
        {
            **values,
            "run_id": run_id or (scope[1] if scope else None),
            "correlation_id": scope[2] if scope else None,
            "trace_id": format(span.trace_id, "032x") if span.is_valid else None,
            "span_id": format(span.span_id, "016x") if span.is_valid else None,
        }
    )
    event["duration_ms"] = event["duration_ms"] or 0
    event["attempt"] = event["attempt"] or 0
    connection.execute(
        """INSERT INTO telemetry_events
        (run_id, created_at, kind, component, outcome, duration_ms, attempt,
         status_code, correlation_id, trace_id, span_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            event["run_id"],
            time.time(),
            event["kind"],
            event["component"],
            event["outcome"],
            event["duration_ms"],
            event["attempt"],
            event["status_code"],
            event["correlation_id"],
            event["trace_id"],
            event["span_id"],
        ),
    )
    return event


def record_event(kind, component, outcome="ok", **values):
    scope = _scope.get()
    if scope is None:
        return
    try:
        with scope[0].transaction() as connection:
            event = insert_event(
                connection, kind=kind, component=component, outcome=outcome, **values
            )
        logging.getLogger("financial_ai.telemetry").info("telemetry", extra={"safe_event": event})
    except Exception:
        # No exception text: database errors may contain connection secrets.
        logging.getLogger("financial_ai.telemetry").warning("telemetry_unavailable")


@contextmanager
def observe(kind, component, *, attempt=0, parent=None):
    scope = _scope.get()
    fields = {"outcome": "ok", "attempt": attempt}
    if scope is None:
        yield fields
        return
    safe = safe_event({"kind": kind, "component": component})
    tracer = scope[3].get_tracer("financial_ai")
    with tracer.start_as_current_span(
        f"{safe['kind']}.{safe['component']}",
        context=parent_context(parent),
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        start = time.perf_counter()
        try:
            yield fields
        except BaseException:
            fields["outcome"] = "error"
            raise
        finally:
            values = safe_event(
                {
                    **safe,
                    **fields,
                    "duration_ms": (time.perf_counter() - start) * 1000,
                    "run_id": scope[1],
                    "correlation_id": scope[2],
                }
            )
            span.set_attributes({k: v for k, v in values.items() if v is not None})
            span.set_status(StatusCode.ERROR if values["outcome"] == "error" else StatusCode.OK)
            record_event(kind, component, **fields, duration_ms=values["duration_ms"])


class TelemetryStore:
    def __init__(self, database):
        self.database = database

    def audit(self, run_id, after=0, limit=100):
        with closing(self.database.connect()) as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM telemetry_events WHERE run_id=? AND id>? ORDER BY id LIMIT ?",
                    (str(run_id), after, limit),
                ).fetchall()
            ]

    def metrics(self, minutes=60):
        with closing(self.database.connect()) as connection:
            return [
                dict(row)
                for row in connection.execute(
                    """SELECT kind, component, outcome,
                COUNT(*) AS count, AVG(duration_ms) AS mean_ms, MAX(duration_ms) AS max_ms,
                SUM(duration_ms) AS total_ms FROM telemetry_events WHERE created_at>=?
                GROUP BY kind, component, outcome ORDER BY total_ms DESC""",
                    (time.time() - minutes * 60,),
                ).fetchall()
            ]

    def cleanup(self, days=7):
        with self.database.transaction() as connection:
            connection.execute(
                """DELETE FROM telemetry_events WHERE id IN
                (SELECT id FROM telemetry_events WHERE created_at<? AND kind NOT IN ('run','job')
                 ORDER BY id LIMIT 1000)""",
                (time.time() - max(1, days) * 86400,),
            )
