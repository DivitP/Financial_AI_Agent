# Local request and research budgets

The API and workers share SQLite quota tables (migration 11). Limits are local
safety ceilings, not verified remaining balances for Groq/FMP or another account.
They require the same database path across processes; separate installations do
not share limits.

| Setting | Default | Scope |
| --- | ---: | --- |
| API_REQUESTS_PER_MINUTE | 120 | All API clients combined, fixed minute |
| API_CONCURRENCY | 16 | Requests including open SSE streams |
| MAX_PENDING_JOBS | 20 | Durable pending job queue |
| MAX_RUNNING_JOBS | 2 | Running jobs; separately, active research workflows |
| RUN_CALL_BUDGET | 60 | Per run, lane/node attempts plus HTTP/SDK calls |
| RUN_ARTICLE_BUDGET | 20 | Per run, collected articles and article download attempts |
| RUN_MODEL_BUDGET | 8 | Per run, chat/forecast attempts, including malformed-output retries |
| PROVIDER_RATE_LIMIT_PER_MINUTE | 30 | Per provider, fixed minute |
| PROVIDER_CONCURRENCY | 2 | Per provider/model |
| MAX_RETRY_DELAY_SECONDS | 10 | Largest automatic HTTP retry wait |

Per-run usage survives process restarts and explicit job retries. Cached HTTP
responses and completed graph checkpoints spend no new call budget. Attempted
work is conservatively charged even if it subsequently fails; article batches
that exceed the remaining allowance are rejected rather than silently truncated.
Standalone provider work has minute-scoped budgets instead of a research run.
SDK-internal traffic cannot be counted individually; the OpenBB boundary counts
each quote/profile/history invocation. Legacy third-party agent/SDK internals
are not a fully metered execution engine; run research through the new workflows.

Exhaustion returns safe JSON with HTTP 429, stable code quota_exceeded, and
Retry-After. No automatic React Query retry occurs for that code. Chat displays
the quota message. Failed research lanes/checkpoints and optional forecast warnings
retain the reason while successful lanes remain persisted. Permanent run budgets
do not replenish just because the minute window or Retry-After has elapsed:
review configuration before explicitly retrying that run.

429 HTTP retries are finite. Excessive Retry-After values stop immediately and
establish a persisted provider cooldown; repeated calls cannot bypass it.
Malformed Retry-After values use bounded exponential backoff. Groq SDK automatic
retries are disabled; model-provider 429s establish a 60-second cooldown.
Cancellation and health routes remain usable under API saturation.

Concurrency leases expire after ten minutes to recover after crashes. API and
async research operations are bounded to nine minutes, chat to two minutes;
provider downloads retain their own timeout. Blocking external SDK behavior is
still subject to its own transport timeouts. Completed/cancelled/running jobs are
not accidentally re-executed by repeated run requests. Job attempts are capped.
Use one local worker owner for recovery: do not call recover while another worker
is actively processing jobs. Retained per-run counters are intentional audit
state; short-lived rate counters and expired leases are cleaned automatically.

Run make check and uv run pytest tests/test_quotas.py --no-cov.
Tests use isolated databases, injected transports and no API keys/network.
