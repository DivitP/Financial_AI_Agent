# ADR-0001: Adopt a modular FastAPI and React target architecture

- Status: accepted
- Date: 2026-08-14
- Decision owners: Financial AI Agent maintainers

## Context

The current Flask application mixes HTTP routes, orchestration, storage,
external-provider calls, and rendered HTML in one module. This makes research
runs hard to persist, test, resume, and evolve. The replacement must support
long-running research, evidence-backed answers, local and hosted models, and a
modern browser client without breaking the current Flask workflow during the
migration.

## Decision

The target is a React + TypeScript single-page application served separately
from a FastAPI backend. FastAPI owns the public HTTP contract, authentication
boundary, validation, and streaming/status APIs. React owns navigation,
rendering, accessibility, client state, and chart presentation; it never calls
data providers directly.

The backend is organized as the following packages. Arrows show the only
allowed dependency direction.

```text
web (React) -> api (FastAPI routes/schemas) -> application (use cases)
                                        -> domain (entities/policies)
application -> ports (provider, repository, model interfaces)
infrastructure (adapters) -> ports + domain
workers -> application
legacy Flask adapter -> application (temporary only)
```

| Planned package | Responsibility | May depend on |
| --- | --- | --- |
| `frontend/` | React UI, research-run navigation, charts, evidence display | API schemas/client only |
| `backend/api/` | FastAPI routes, request validation, auth, SSE/WebSocket status | `application`, `domain` |
| `backend/application/` | Start/resume research, assemble reports, answer questions | `domain`, `ports` |
| `backend/domain/` | Tickers, evidence, citations, claims, research-run states, quality policy | standard library only |
| `backend/ports/` | Typed contracts for market/news/filing/model/repository services | `domain` |
| `backend/infrastructure/` | OpenBB, SEC, FMP, yfinance, GDELT, Groq, local-model, SQL/vector adapters | `ports`, `domain` |
| `backend/workers/` | Durable asynchronous job execution and retries | `application` |
| `backend/evals/` | Golden evidence sets, provider contract tests, forecast validation | `application`, `domain`, test adapters |
| `legacy/` | Transitional Flask compatibility routes only | `application` |

No route, React component, or agent may import an infrastructure provider
directly. No infrastructure adapter may import API or frontend code. The domain
must remain independent of FastAPI, React, LangChain, OpenBB, and databases.

## Persistent research runs

A `ResearchRun` is created before any external request. It has an immutable
identifier, ticker/instrument, requested scope, provider configuration version,
status, timestamps, evidence IDs, report version, and error/retry history.
Raw provider payloads are retained only where terms permit; normalized evidence
and provenance are persisted independently. A worker resumes a run idempotently
and the API exposes status plus an append-only event stream.

Initial persistence is SQL (SQLite for local development; PostgreSQL in hosted
deployments). Large permitted artifacts use object storage. The vector index is
a derived, rebuildable store and never the sole system of record.

## Migration

Keep Flask available while FastAPI endpoints are introduced side-by-side. New
use cases first live in `backend/application/`; Flask routes call those use
cases through a compatibility adapter. Route-by-route parity tests determine
when a Flask endpoint can be retired. React consumes FastAPI only; it is not
embedded into the Flask HTML string.

## Consequences

- Long-running analysis is observable and reproducible by run id.
- UI and API can evolve independently.
- Provider replacement does not alter analysis policy or public contracts.
- The migration adds temporary duplication, which is removed only after
  documented parity and regression coverage.
