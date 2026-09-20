# Persistent watchlists

Open **Watchlists** in the web navigation. Create multiple named lists, add
symbols, and save per-list ticker notes and tags. Use Edit to load saved notes
before changing them. Saving an existing symbol replaces its notes/tags only in
that list. Rename lists or remove tickers/lists (the UI asks for confirmation).
Removal deletes those notes/tags, not research runs; there is no undo.

Watchlists are local SQLite metadata, not a subscription or background refresh.
All CRUD and summary endpoints use stored data only: no provider requests, LLMs,
job scheduling, polling, or live ticker resolution. Adding an unsupported symbol
does not claim it is a valid security. Start research separately when needed.

Each ticker shows the newest saved run by request time, including failed or
pending runs, without quietly substituting a previous successful run. The link
opens saved history. Retrieval ages are per lane, using explicit timezone-aware
retrieval timestamps (the oldest available provenance timestamp when multiple
are present). “Recent” means at most 24 hours since retrieval; it is **not**
real-time market freshness, period completeness, or confidence. Missing, invalid,
and future timestamps are unknown. Failed lanes retain their failure status.
Database write time is never used as a proxy for source freshness.

Upcoming earnings are extracted from the latest run's saved earnings snapshot,
including the scheduled timestamp, release session, evidence IDs and source URL
when available. Past or timezone-ambiguous dates are excluded. Missing evidence
is labelled; absent events mean incomplete saved coverage, not “no events”.
These are saved estimates, not a live exchange calendar. No paid API is needed.

API (`/api/v1/watchlists`):

- GET / POST: list or create lists (`{"name":"Long term"}`).
- GET / PATCH / DELETE `/{id}`: inspect, rename, or delete a list.
- PUT `/{id}/items`: idempotently save `ticker`, `notes`, and `tags`.
- DELETE `/{id}/items/{ticker}`: remove a ticker from that list.

Names: 80 characters; symbols: existing 15-character validation; notes: 2,000
characters; tags: up to 20 strings of 1–40 characters, trimmed, lowercased and
deduplicated. Migration 10 adds watchlist tables; downgrade deletes watchlists
and notes but preserves research data. Back up first. Existing local access
boundaries apply: this does not add multi-user authentication.

Run `make check` for offline API, persistence, freshness, and UI tests.
