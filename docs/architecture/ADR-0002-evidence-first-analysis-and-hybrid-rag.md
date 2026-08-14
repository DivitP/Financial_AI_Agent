# ADR-0002: Make evidence and validation first-class analysis inputs

- Status: accepted
- Date: 2026-08-14

## Decision

Every statement shown in a research report is either:

1. an attributed fact linked to one or more `Evidence` records;
2. a clearly labeled model inference linked to its inputs, model version, and
   prompt/template version; or
3. an explicitly labeled unavailable/unknown result.

An evidence record stores source/provider identity, canonical URL or filing
identifier, retrieval time, publication time when known, content hash, excerpt
or structured fields, license/terms classification, and a locator that lets the
reader verify the claim. Citations are displayed beside claims, not only in a
report appendix. Conflicting sources remain visible rather than being silently
merged.

## Hybrid RAG

Question answering retrieves from two paths and then applies an evidence gate:

```text
question -> structured run/evidence filters ----\
                                             rank -> citation gate -> answer
question -> vector retrieval over permitted text -/
```

Structured filtering is authoritative for ticker, date, provider, filing type,
and run. Vector retrieval supplies semantic recall over permitted evidence
chunks. Generated answers must cite retrieved evidence; an answer with no
sufficient evidence says so. The vector index contains no secrets and is
rebuildable from permitted persisted evidence.

## Forecasting policy

Technical signals and Kronos outputs are research inputs, not investment
recommendations. They must show horizon, training/data cutoff, assumptions,
and uncertainty. No forecast confidence is displayed without preregistered
out-of-sample validation, baseline comparison, and versioned evaluation results.
Provider failures or missing data lower coverage; they must not be converted
into fabricated confidence.

## Consequences

- Reports are auditable at claim level.
- RAG cannot treat an uncited model assertion as research evidence.
- Backtesting/evaluation becomes a release gate for forecasting features.
