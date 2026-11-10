# Deterministic synthetic research

This opt-in collector implements the existing `collect(lane, run)` interface and
uses the replacement pipeline for storage, analysis, reports and retrieval. It
does not use a network, API keys, LLM, wall clock or random generator. The default
Compose demo now delegates to this same pipeline; live collection is never a fallback.

Set these in local `.env` for both API and worker, then run the API, React client
and `uv run python -m financial_ai.workflow.local_worker` as documented in the README:

```dotenv
WORKER_HANDLER_FACTORY=financial_ai.workflow.synthetic:handler
ENABLE_LIVE_RESEARCH=false
ENABLE_GROQ=false
ENABLE_FMP=false
ENABLE_LOCAL_LLM=false
ENABLE_KRONOS=false
SYNTHETIC_EVIDENCE_ORIGIN=http://localhost:8000
```

The origin must point to your browser-reachable API (or same-origin `/api` proxy).
It is administrator configuration, never derived from Host/Forwarded headers;
it accepts only HTTP(S) origins without credentials, paths, queries or fragments.
It does not authorize outbound fetching. Keep local deployments loopback-only.
For Compose, these values must be passed explicitly to both API and worker;
the host `.env` is not automatically forwarded to containers.

Submit AAPL, MSFT, NVDA, SPY or QQQ. These are **labels for invented organizations**,
not representations of the issuers/funds bearing those tickers. Other symbols
are rejected without a live lookup. The fixture's fixed as-of/retrieval time is
2025-12-31 21:00 UTC, not the actual time a job runs. Stale labels are intentional.
The collector returns fresh objects with deterministic contents on every call.
Job IDs, execution timestamps and report generation timestamps are not deterministic.

The `synthetic-v1` dataset contains fictional identity, 60 OHLCV observations,
a quote equal to the final close, invented annual USD facts with 39% gross
margin, and sample source/news metadata. Its weekday schedule is not an actual
exchange calendar and must not be used for backtests or Kronos inputs. No real
corporate actions, holidays, earnings announcements or news are claimed.
ETF corporate statement lanes remain not applicable; holdings/fees are not supplied.
`SYNTHETIC-ANNUAL` is an invented record type, never a real SEC form/accession.

## Inspecting evidence

Each source has a stable UUID derived from dataset version, ticker and lane.
Exact links use `GET /api/v1/synthetic-evidence/{record_id}`. The response is
readable plain-text JSON with an explicit invented-data warning, units, dates,
full payload and provenance. It cannot execute embedded HTML. The catalog
contains only public bundled samples: it never queries user evidence, opens a
filesystem path, follows a URL or downloads a document. Unknown UUIDs return 404;
malformed IDs return safe JSON 422; mutation methods are not supported.

Persisted run evidence has its own run-specific ID, with `source_tier=synthetic`
and an exact link to the stable catalog record. Synthetic data is not classified
as official or reputable real-world evidence. Reports and derived findings keep
the synthetic label; the dashboard displays an invented-data banner. Raw payloads
remain in local artifacts, not Git. Sample source destinations never use sec.gov
or a publisher's domain to imply support for invented figures.

Preserve `synthetic-v1` record contents when adding future datasets: introduce a
new version and retain old lookups, rather than silently changing old citations.
Keep the configured origin stable for saved reports. This preview has no URL
migration service if an operator changes the origin.

Verification: `uv run pytest tests/test_synthetic_research.py --no-cov` blocks
socket/DNS access and covers reproducibility, metadata, coherence, unsupported
symbols, report persistence, exact lookup, invalid IDs, host checks and text-only
rendering. `make check` additionally exercises the UI notice and coverage gates.
