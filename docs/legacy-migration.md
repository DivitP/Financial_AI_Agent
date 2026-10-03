# Archive and classify legacy research

Stop the legacy Flask app and all writers first. Do not open the old application
to migrate: importing `main.py` initializes legacy provider dependencies.
The standalone utility uses only SQLite and the standard library; no keys or
internet are needed. It never deletes, renames or modifies the source database.

From the repository root, with the base package installed:

```bash
# Safe default: consistent SQLite backup plus a classification manifest.
uv run python -m financial_ai.storage.legacy_migration chroma_db/vectorstore.db
# Optional: also import legacy documents into a separate quarantine database.
uv run python -m financial_ai.storage.legacy_migration chroma_db/vectorstore.db --mode import
```

Supply the actual old SQLite path if different. `--destination` defaults to
ignored `data/runtime/legacy/`; it is a directory, never the new application DB.
The importer recognizes the legacy `documents(id, content, metadata)` table.
Other SQLite formats (including Chroma internal databases) can be archived but
not interpreted as reports. Non-SQLite files/directories are rejected. Modern
schema-migrated databases cannot be imported through this legacy adapter.

Each content-addressed bundle contains `source.sqlite3` and `manifest.json`.
Import mode additionally creates `legacy.sqlite3` with only `legacy_records`.
Every imported row has classification **legacy_unverified**, original ID/text,
unparsed original metadata, and a stable content hash. Manifest timestamps mean
archive time, not original reporting dates. No citation or financial confidence
is inferred, even if old metadata includes URLs or “sources.”

The quarantine is deliberately disconnected from current reports, relational
evidence, FTS/Chroma retrieval and Q&A. HTML, embedded instructions, charts/base64
and malformed metadata remain opaque untrusted content: never render them as
HTML or auto-index them. Fresh evidence collection and normal verification are
required before any factual claim can enter a new verified report.

Repeat runs reuse an integrity-checked bundle for the same snapshot and mode;
changed source content creates a new bundle without overwriting earlier records.
Backup uses SQLite's transactional backup API (including committed WAL content),
then integrity checking. Imports read that backup, not a changing source. Bundles
publish only after successful import; failed staging is discarded, source intact.
Tampered bundles cause failure, not repair/overwrite. Preserve them for inspection.
Default budgets are 256 MiB and 60 seconds for backup; archive larger sources only
after reviewing resources (the Python API accepts `max_bytes`).

New bundle directories/files use private permissions on POSIX. Archives can still
contain historical secrets or restricted data: encrypt backups, restrict access,
and never commit/share them unreviewed. Stop writers for a coordinated backup of
external artifacts; this utility handles a single SQLite database, not referenced
filesystem files. For recovery, copy a verified `source.sqlite3` into a new isolated
location; never restore it over the current evidence database. There is no automatic
promotion, deletion of the old DB, or destructive rollback.

Run `uv run pytest tests/test_legacy_migration.py --no-cov` for offline repeatability,
source/new-evidence preservation, changed-record, tampering and failure checks.
