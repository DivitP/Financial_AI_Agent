# Changes since last run

Open a saved run in History, then **Changes since last run**. The comparison is
deterministic and read-only: no provider calls, LLM requests, or new jobs.

`GET /api/v1/research-runs/{run_id}/delta` selects the latest strictly earlier
terminal run of the same instrument (including exchange and asset identity).
An optional `previous_run_id` selects another earlier terminal baseline.
Pending/running comparisons and mismatched baselines return a JSON 409 error.
No baseline returns an explicit limitation, not an empty “all clear”.

The eight lanes are filings, earnings, guidance, analysts, sentiment, valuation,
technical, and decision (thesis risks and scenarios). Comparisons show changed
saved lane content side by side, not inferred direction, materiality, or causal
claims. Values retain periods, units, management/inferred distinctions, and
limitations. No arithmetic is performed across potentially incompatible units.
List order and citation/retrieval bookkeeping alone do not count as changes.

Each displayed change requires explicit evidence IDs from each payload, resolved
against the corresponding run's relational evidence with exact HTTP(S) document
URLs. Missing IDs, unknown/cross-run citations, and homepage-only citations block
the change and produce a limitation. Evidence links establish traceability, not
independent verification that the source entails every value. Missing/failed
lanes never imply that a filing, risk, or other event ceased to exist.

When a saved report exists, its earliest version's frozen snapshots and as-of
date are used, consistently with default History reopening. Legacy reports with
no frozen snapshots show a gap: live/current snapshots are not substituted.
Without a report, stored terminal-run snapshots are compared and clearly labeled;
these can change if that run is explicitly retried. The report is computed on
read, not persisted as another immutable version. Citation URLs may point to
external pages that have since changed.

Verification: `make check` covers both evidence sides across all eight lanes,
network/job isolation, invalid baselines, uncited changes, and frozen history.
