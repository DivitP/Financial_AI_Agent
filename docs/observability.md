# Research observability

Telemetry runs locally without provider keys or a hosted monitoring subscription.
The base dependency `opentelemetry-sdk` supplies nested, content-free spans; the
optional `observability` extra supplies OTLP export. SQLite and Postgres use the
same version-13 event schema. No financial-data requests are made by these endpoints.

## Investigating a slow run

With the API running, open:

- `/api/v1/research-runs/<run-uuid>/audit?after=0&limit=100`
- `/api/v1/observability/metrics?minutes=60`

Audit events are ordered by durable integer ID. Use the last ID as `after` to
page forward (maximum 500 events). Each event contains its run ID, component,
outcome, duration in milliseconds, attempt, HTTP status when applicable,
correlation ID when available, and trace/span IDs.

Compare `node` durations first, then the nested `provider` and `model` spans.
For example, a slow `filings` node with a long `sec` provider span attributes the
delay to the SEC request. HTTP attempts are recorded individually, including
429/5xx failures; cache metrics distinguish hits, misses, and deduplicated waits.
Groq/Ollama chat and Kronos inference are timed separately. Local job steps,
parallel collection lanes and graph attempts are instrumented. Unknown custom
provider/node names become `other`; extend the reviewed allowlist when adding
new components. Do not add tickers, prompts, URLs or model names as metric labels.

Metrics return count, mean, maximum and total milliseconds grouped by fixed
kind/component/outcome labels, over 1–1440 minutes. They aggregate persisted
events across processes, not sampled trace data. They are **not** latency
percentiles. Nested/concurrent durations must not be summed to estimate run
wall time. HTTP duration includes the response lifetime (including SSE client
connection time); a workflow span measures execution separately. An abruptly
killed operation has no final timing event; persisted job/checkpoint state and
subsequent recovery events distinguish unfinished work. Cache hits have no
provider request span because no request occurred.

Run-status and job-event audit inserts share the state-change transaction:
rollback removes both. These durable events are retained indefinitely. Timing
inserts are best effort; storage failures emit only `telemetry_unavailable` and
do not discard research results. Diagnostic retention defaults to seven days
(`TELEMETRY_RETENTION_DAYS`, 1–90). Startup deletes at most 1,000 expired
diagnostic rows; long-lived deployments should periodically call
`TelemetryStore(database).cleanup(days)` until their backlog is cleared.
Audit history is operational history, not a tamper-proof regulatory audit trail.

## Optional OpenTelemetry collector

```bash
uv sync --locked --all-groups --extra observability
```

Set `TELEMETRY_EXPORT_ENABLED=true` only when an OpenTelemetry collector is
listening on **127.0.0.1:4318**. The fixed local OTLP/HTTP endpoint is
`http://127.0.0.1:4318/v1/traces`; a collector may route spans to a self-hosted
backend such as Jaeger. The bounded batch queue holds 512 spans. Export is off
by default; audit and metrics work without a collector. A missing optional
exporter package produces an actionable startup error. Export failures do not
fail research. Model weights and financial document contents are never sent.

Trace parents are persisted with queued jobs, so a separate/restarted worker
continues the enqueue trace. Retries are distinct spans in the same trace.
Only traceparent is propagated—not baggage, arbitrary request headers, or
tracestate. External HTTP trace headers are not accepted. Correlation IDs are
UUIDs and trace IDs are fixed-length hexadecimal identifiers.

The SDK is configured explicitly rather than using automatic HTTP/LLM
instrumentation, which could capture URLs or prompts. See the official
[Python instrumentation guide](https://opentelemetry.io/docs/languages/python/instrumentation/).

## Logging and security

Application JSON logs use an allowlisted schema. Raw messages, exception text,
stack traces, document text, prompts, provider URLs, API keys, request bodies,
arbitrary extras and logger names are excluded. Exceptions set the span error
status without recording exception events or descriptions. Resource attributes
are fixed, and the exporter does not inherit endpoint/header/proxy credentials.
This policy covers `financial_ai` logs, not arbitrary third-party loggers or
reverse-proxy access logs; keep third-party HTTP wire/debug logging disabled.

These endpoints follow the application's existing host/security boundary;
they do not add authentication. Keep the application private or place it behind
an authenticated proxy before exposing run history and operational metadata.

## Verification

```bash
uv run pytest tests/test_observability.py tests/test_storage.py --no-cov
make check
```

Fixtures exercise deterministic slow-provider attribution, parent/child spans,
cache/retry/model metrics, restart continuity, audit rollback and pagination,
concurrent run isolation, retention, storage failure and secret exclusion.
No live provider or collector is needed.
