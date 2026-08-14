# ADR-0003: Isolate providers and use a side-by-side migration

- Status: accepted
- Date: 2026-08-14

## Decision

Each external source and model has one adapter implementing a narrow port:

| Port | Implementations considered | Output |
| --- | --- | --- |
| `MarketDataProvider` | OpenBB, yfinance, FMP | normalized bars, quotes, fundamentals |
| `FilingProvider` | SEC EDGAR, OpenBB provider extension | filing metadata and sections |
| `NewsProvider` | GDELT, permitted OpenBB providers | article/event candidates with provenance |
| `InferenceProvider` | Groq, local LLM | bounded structured extraction/synthesis |
| `CandleModelProvider` | local Kronos | probabilistic candle/volatility research output |
| `EvidenceRepository` | SQL/object storage/vector index | evidence and retrieval operations |

Adapters normalize data to domain types, carry source terms metadata, enforce
timeouts/retries/rate limits, and return typed partial-failure results. They do
not make investment decisions, compose reports, or call other providers.

Provider selection is configuration-driven. A run records the actual providers
and versions used. The application layer chooses a fallback only when it
preserves the requested data meaning and terms classification.

## OpenBB and AGPL boundary

OpenBB is AGPL-3.0. Directly importing it into this networked application is
permitted only because this repository is AGPL-3.0-or-later. Before release,
maintainers must review the exact OpenBB version, extension licenses, modified
source availability, notices, and any commercial data-provider terms. Do not
vendor OpenBB code or copy its data-provider credentials into this project.

## Migration guardrails

The current Flask module is frozen except for safety/configuration fixes. New
features are implemented through the target ports and application use cases,
then exposed through both FastAPI and the temporary Flask adapter until parity
tests pass. No new route should couple directly to LangChain or a provider SDK.
