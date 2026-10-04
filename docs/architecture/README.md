# Architecture: current assembly and target records

The [README diagram](../../README.md#architecture) shows the replacement assembly.
The explicit `ResearchPipeline` connects bounded source collection, relational
evidence, deterministic analysis, extractive reports and FTS indexing. The local
worker polls durable SQLite jobs; the scaled worker consumes Redis deliveries
with Postgres repositories. The API provides saved views and SSE, and React uses
same-origin API requests. Compose selects a synthetic handler by default.

| Boundary | Responsibility and dependency direction |
| --- | --- |
| `frontend/web` | Rendering and interaction → API; no provider credentials or direct provider calls |
| `api` | Validation, errors and transport → workflows/repositories; not source collection logic |
| `workflow` | Job execution and explicit assembly → providers, analysis, reporting, retrieval, storage |
| `providers`, `data` | Source adapters and bounded HTTP → normalized domain data; no UI imports |
| `domain` | Typed research contracts; independent of UI/provider SDK execution |
| `analysis`, `agents` | Calculations/evidence interpretations → domain; model output is not a source |
| `reporting` | Cited structured findings → versioned report persistence |
| `retrieval` | Source-aware indexing, isolation and retrieval → relational evidence; optional vector projection |
| `llm`, `prompts` | Model-neutral inference and structured-output contracts; optional, not mandatory collection dependencies |
| `kronos` | Optional local forecast preparation/inference; no authority to promote unvalidated results |
| `storage` | Migrations, repositories and artifacts; relational evidence is authoritative |

This table describes intended ownership, not a claim that every historical
import satisfies it. Configuration still lives in root `settings.py`; legacy
compatibility modules remain. The replacement pipeline does not import legacy
Flask/main/agents, but full repository retirement and installed-only packaging
validation remain separate migration gates.

Optional Chroma/embeddings, advanced analyst nodes and the Kronos workflow are
implemented modules, not proof of complete live wiring. The initial collector
does not supply full documents, ETF holdings or complete Kronos input calendars.
See [replacement limitations](../replacement-workflow.md) before changing claims.

These ADRs retain the target contract; they are not release sign-off:

1. [ADR-0001](ADR-0001-target-architecture.md) defines packages, direction,
   persistence, FastAPI/React, and migration.
2. [ADR-0002](ADR-0002-evidence-first-analysis-and-hybrid-rag.md) defines
   evidence, citations, hybrid retrieval, and forecasting validation.
3. [ADR-0003](ADR-0003-provider-boundaries-and-migration.md) defines adapters,
   OpenBB licensing, and side-by-side Flask retirement.
