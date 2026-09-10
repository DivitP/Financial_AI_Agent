# Offline RAG evaluation gate

Run `make rag-eval`. CI runs this named gate in addition to the full pytest suite;
any failed metric or adversarial/freshness assertion fails the job. Output includes
the fixture version, retrieval mode and measured scores. No keys, model downloads,
live requests or optional vector dependencies are needed.

The versioned fixture `tests/fixtures/rag/benchmark.json` contains six synthetic
documents and six relevance-labelled questions. Each document is indexed into the
target run, a different run of the same ticker, and another ticker. Dates and IDs
are fixed. Tests exercise real SQLite FTS5, ResearchIndex fusion/filtering and
ResearchQA validation. Hybrid mode injects a deliberately noisy, unfiltered vector
ranking to test fusion and defence against leakage, rather than a trained embedder.

Thresholds:

| Metric | Gate | Definition |
|---|---:|---|
| Recall@3 | ≥ 0.90 | Mean fraction of labelled relevant chunks in the top three |
| MRR | ≥ 0.80 | Mean reciprocal rank of the first relevant chunk within the top three |
| Citation precision | 1.00 | Fraction of emitted claims citing a relevant chunk with matching evidence ID and URL |
| Unsupported-claim rate | 0.00 | Fraction of emitted claims lacking a valid citation or an exact source quote |
| Answer rate | 1.00 | Fraction of answerable questions producing an answer (prevents abstention gaming) |
| Isolation | 1.00 | Queries with no foreign ticker/run results |
| Freshness | 1.00 | No observations from after the evaluation cutoff |
| Adversarial rejection | 1.00 | Rejection of uncited, foreign-source, invented and malformed outputs |

Additional assertions check that equally relevant fresh text outranks stale text,
and that later retrieval dates cannot bypass the as-of cutoff. Negative controls
verify metric arithmetic, duplicate handling, missing-score failures and each
threshold's ability to fail. Security metrics are strict, even on a small dataset.

The fixture model selects relevant excerpts only if retrieval actually provides
them. It is intentionally scripted: these scores measure pipeline regressions,
not a live model's reasoning, semantic relevance judgement, prompt-injection
resistance or embedding quality. Adversarial questions are paired with hostile
model responses to exercise the validator. Expand labelled documents and queries
as representative real-world examples become available; changing thresholds or
labels should receive explicit review, not be used to conceal a regression.
