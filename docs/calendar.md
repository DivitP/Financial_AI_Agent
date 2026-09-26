# Watchlist catalyst calendar

Open **Calendar** for a source-linked agenda. Filter all watchlists or one list
and a local-date range. GET `/api/v1/calendar?start=YYYY-MM-DD&end=YYYY-MM-DD&watchlist_id=UUID`
defaults to today (UTC) through 90 days ahead. Maximum range: 366 days; maximum
200 distinct tickers and 1000 returned events. Narrow the selection if exceeded.

The service reads only the newest terminal research run for each uniquely
identified watchlist ticker. It never calls providers, queues research, connects
accounts or modifies saved runs. Stale schedules are possible; evidence retrieval
times and links are displayed. An empty calendar is not proof of no events.

Supported saved snapshot shapes (also accepted inside a `data` wrapper):

- `earnings.upcoming` (or a single earnings object).
- `guidance.events[]`.
- `dividends.events[]` (use titles to distinguish ex-dividend and payment dates).
- `macro.releases[]`.
- `decision.catalysts[]`.

Each event requires `scheduled_at` or `due_at`, plus explicit event-level
`evidence_id` or `evidence_ids` resolving to exact document URLs in that run.
Uncited events are omitted with coverage warnings. No events are inferred from
undated financial statements, guidance numbers or macro series values.

Offset-aware timestamps preserve their offset, including daylight-saving
ambiguity. Date-only values remain dates with unknown timezone, never midnight
UTC. Naive timestamps and invalid dates are omitted. Filters and agenda ordering
use source-local calendar dates, not the browser timezone; same-day rows across
zones are not an absolute-time sequence.

Optional `date_confidence` is a saved source status: confirmed, estimated or
tentative; absent/unrecognized values display unknown. It is not a calculated
probability, source-tier inference, or forecast confidence. Release sessions
remain explicit or unknown. Similar events with conflicting dates stay separate.
Exact duplicate source/date/title/status events are merged with all ticker and
run citations preserved. Repeated watchlist membership does not duplicate events.

No new API keys or dependencies are required. Run `make check` for offline
event-category, timezone, evidence, filtering, deduplication and UI tests.
