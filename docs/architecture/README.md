# Target architecture records

These ADRs define the future implementation contract. They are intentionally
more specific than the current Flask code so new packages can be added without
reintroducing provider/UI/storage coupling.

1. [ADR-0001](ADR-0001-target-architecture.md) defines packages, direction,
   persistence, FastAPI/React, and migration.
2. [ADR-0002](ADR-0002-evidence-first-analysis-and-hybrid-rag.md) defines
   evidence, citations, hybrid retrieval, and forecasting validation.
3. [ADR-0003](ADR-0003-provider-boundaries-and-migration.md) defines adapters,
   OpenBB licensing, and side-by-side Flask retirement.
