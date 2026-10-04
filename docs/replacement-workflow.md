# Replacement workflow integration status

The replacement now has a shared `ResearchPipeline` worker factory for local and
Redis execution. It does not import `main`, `agents` or Flask. This is a bounded
initial integration, not a claim that all previous research functionality has
achieved parity. Legacy deletion remains gated on the checks below.

## Running the replacement explicitly

Keep LLMs disabled for deterministic reports. In `.env` configure:

```dotenv
ENABLE_LIVE_RESEARCH=true
SEC_USER_AGENT=YourApplication your-actual-contact-email
RESEARCH_NEWS_FEEDS=["https://your-reviewed-publisher/feed.xml"]
DOCUMENT_ALLOWED_HOSTS=["www.sec.gov","data.sec.gov","api.gdeltproject.org","your-reviewed-publisher"]
WORKER_HANDLER_FACTORY=financial_ai.workflow.pipeline:handler
```

Replace the contact and feed placeholders; don't use a fake SEC identity. Feed
hosts must explicitly pass the existing download allowlist. No paid key is
required for this collector. Startup rejects live mode without a contact address.
Run the API/UI as documented in deployment.md, plus a third terminal:

```bash
uv run python -m financial_ai.workflow.local_worker
```

Only one local worker may own a SQLite queue. `--once` processes at most one
pending job; `--recover` requeues interrupted work and must only be used after
the previous owner stopped. For Postgres/Redis, use the existing Redis worker
with this same trusted factory. Compose remains an explicit offline demo by
default; a reviewed environment override is required to enable this factory.
The API job-run endpoint refuses an unconfigured local collector instead of
returning a false successful no-op.

## What is wired and tested offline

- Free Yahoo chart endpoint: identity, quote and adjusted-close history behind
  bounded shared HTTP. This is an explicit direct adapter, not an undocumented
  OpenBB fallback. Availability/usage terms still require live verification.
- SEC filing metadata and normalized company facts; annual USD duration/instant
  mapping avoids quarterly and mixed-currency arithmetic. Missing values remain
  unavailable. Full filing bodies are not yet collected by this factory.
- One configured RSS feed with strict ticker-headline matching. Only source
  headlines are summarized; this does not establish sentiment or materiality.
- Relational evidence, raw filesystem artifacts, citation-linked extractive
  reports, deterministic financial/technical calculations, and a bounded SVG
  history chart (no base64). Chart series are not put into the text index.
- Source-text indexing into the same isolated FTS index used by the API's Q&A.
  Q&A uses the existing citation-enforcing optional Groq/local-model interface;
  fixture model tests verify source links. Live LLM quality is not validated.
- Failed coverage retains usable evidence and a partial report, and marks the
  job/run failed. The dashboard now exposes that partial report. Retry reuses
  successful source lanes. Cancellation is checked between requests and steps.

Run `uv run pytest tests/test_replacement_pipeline.py tests/test_live_collector.py --no-cov`
for fixture collection → durable worker → analysis → report → retrieval/Q&A,
partial failure/retry, and conservative financial mapping checks.

## Remaining retirement gates

Do not delete Flask/legacy storage on the strength of these initial tests alone.
Live SEC/Yahoo/feed validation needs a real configured SEC contact and approved
publisher feed. ETF holdings/fees, broader company-news relevance, full document
collection, synthesis beyond extractive headlines/facts, valuation/analyst coverage
and optional forecast integration still need end-to-end coverage in this factory.
ETF corporate statement lanes are labelled not-applicable, not company data.
No unvalidated BUY/SELL forecast behavior will be preserved as a parity requirement.

After those gates pass, archive old data with the legacy migration utility, remove
the legacy entrypoints/compatibility modules and their dependencies, replace
characterization tests with the verified replacement tests, and enforce a static
import boundary. No automatic legacy database conversion or deletion occurs here.
