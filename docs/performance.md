# Performance targets and profiling

Run `make performance` after installing development and frontend dependencies
and Chromium (`cd frontend/web && npx playwright install chromium`). This uses
temporary SQLite storage and offline provider fixtures; no API keys, downloaded
models, or live financial requests are required. Run `make check` for correctness.

## Targets and measured baseline

Targets below are local-development goals, not promises about provider latency.
Baseline: macOS 15.3, Apple Silicon arm64, Python 3.12.13, Chromium, October 2026.
Browser measurements use the Vite development server; production builds are
checked separately. Record hardware, environment and fixture size when comparing.

| Operation | Target | Observed baseline |
| --- | --- | --- |
| First useful fixture dashboard | under 1 second | 282 ms (one navigation) |
| Cached 10,000-row snapshot, p95 | under 100 ms | 5.52 ms |
| Conditional unchanged snapshot, p95 | under 50 ms | 3.19 ms |
| Warm five-lane fixture research workflow, p95 | under 1 second | 23.33 ms |
| Navigation through 10,000 report findings, p95 | under 100 ms | 44.25 ms |

Python measurements use 20 samples with TestClient (no network transport).
The workflow benchmark creates fresh runs, executes the initial parallel workflow
and persists results, but excludes worker queue delay, downstream agents and LLMs.
Five cold provider requests plus 20 warm runs issue only five fixture transport
calls in total. This does not establish live-provider throughput or latency.
Cold fixture dispatch is queued within the HTTP client's two-provider-slot limit;
it does not rely on fast transport timing to avoid concurrency rejection. An
offline regression test delays transport to force overlapping requests.
The browser navigation benchmark uses 20 page changes and asserts a maximum of
25 rendered findings. CI applies deliberately looser shared-runner ceilings of
5 seconds for dashboard load and 1 second p95 for report navigation. Python
timings are printed for profiling rather than used as hardware-sensitive gates.

## Payloads and rendering

- Responses above 1,000 bytes use gzip when negotiated. SSE remains uncompressed
  so progress is not held in a compression buffer. The repetitive snapshot fixture
  shrank from 758,992 to 27,373 wire bytes; real payload ratios will differ.
- `GET /api/v1/research-runs/{id}/snapshot` accepts `lane`, `limit` (1–50,
  default 50), and `offset`. Existing clients retain the list response shape.
  These page lanes, not individual OHLCV observations. Raw financial evidence
  is never truncated by the server for display purposes.
- Snapshot bodies use a bounded process-local LRU (32 entries, 8 MiB).
  Revision metadata is checked on every read, including after another worker
  writes. `ETag` / `If-None-Match` returns 304 for unchanged non-Kronos pages.
  Kronos pages bypass this cache because promotion policy can change independently
  of their stored payload. Concurrently changed pages are returned `no-store`.
- Q&A history accepts `limit` (1–100) and `before` (oldest returned history ID).
  Pages retain chronological display order. Clients needing older conversations
  must request further pages; this is not an unbounded history endpoint.
- Secondary routes load separate JavaScript bundles. Report sections render at
  most 25 findings per page, retaining exact citation links and wording. This
  bounds DOM work, not the report JSON download. Raw saved JSON is formatted
  only when its disclosure opens. Lazy route transitions preserve keyboard focus.
- Historical candles are aggregated into at most 60 display buckets, preserving
  first open, last close and all high/low extremes across the full period. Labels
  disclose date ranges; persisted candles, calculations, forecasts and exports
  remain unchanged. This is not an analytical resampling policy.

## Providers, queries and profiling

The shared HTTP cache has a default 128-entry / 16 MiB body budget, TTL expiry
and LRU eviction. Cache keys distinguish provider, method, URL, headers (including
credentials) and body; keys and payloads are never included in health output.
Attached-client health exposes aggregate hits, misses, hit ratio, bytes, capacity, evictions and
deduplicated requests. API observability metrics include `snapshot_cache` counters.
These counters are process-local, reset on restart and are not global Redis metrics.

`fetch_many` accepts at most 50 requests, coalesces identical requests, preserves
input order and returns per-request errors without discarding successful results.
Dispatch is bounded by provider concurrency (and eight workers), and inherits
quota/tracing context. SEC multi-ticker filings share the company mapping lookup
and use this dispatcher. SEC still receives one request per unique submission URL:
this is bounded scheduling, not a fictional bulk SEC API or a quota bypass.

Migration 14 adds snapshot revisions and indexes for snapshot paging, job-by-run,
Q&A run/cursor reads and provider request timestamps. Snapshot cache hits avoid
reading and serializing large payload columns. Query-plan tests guard indexed
snapshot reads without temporary sorts. Upgrade/downgrade tests cover SQLite and
the optional real Postgres integration profile.

Remaining scope: distributed payload caches, server-side finding/observation
pagination, and live-provider/load testing are not claimed by this baseline.
Do not cache across future user authorization boundaries without extending keys
and access checks. Never trade evidence correctness or policy freshness for speed.
