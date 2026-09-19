# Saved research history

Open **Saved research** in the web navigation. Search by ticker or saved name,
filter by run status and archive state, and page through results. Open a run to
name it, archive/restore it, or select a saved report version. Archiving is only
organizational: it does not delete evidence, cancel a job, or stop collection.

History reads only SQLite. It never starts providers, an LLM, SSE, or a research
refresh. The first saved report version opens by default; version selection is
encoded in the URL. The original report as-of date, text, model configuration,
and exact citation URLs are retained. External linked pages themselves may
change; this feature does not archive the web.

Report versions are immutable. An identical write is idempotent; changing an
existing version raises an error. Save revised reports with a new version.
Each newly persisted report atomically captures its non-Kronos lane snapshots,
including source timestamps and errors. These are the values saved at report
creation, not a retroactive reconstruction of what was available on an earlier
date. History does not rescore their freshness using today's date. Forecast
research remains in the dedicated forecast view, not these snapshot displays.

Migration 9 adds naming/archive metadata and report snapshot captures. Older
reports still display their saved content and links, but show an explicit notice
that original snapshots are unavailable. Current snapshots are **never**
substituted. Runs with no report show that absence rather than live results.
Downgrading to schema 8 removes names, archive flags, and snapshot captures, but
preserves reports and evidence. Back up the database before downgrading.

API:

- `GET /api/v1/research-runs?q=&status=&archive=active|archived|all&limit=20&offset=0`
  (omit status for all statuses; maximum page size 100).
- `GET /api/v1/research-runs/{id}/history?version=1` returns stored versions,
  selected report, original snapshots, and any limitations.
- `PATCH /api/v1/research-runs/{id}/history` accepts `name` (up to 80 characters,
  null/blank clears it) and/or `archived` (boolean).

History shares the application's existing local database and access boundary;
it does not add multi-user isolation or authentication.

Verification: `make check` includes offline history API/storage and web tests.
