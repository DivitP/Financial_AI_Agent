# Version-pinned report exports

In Saved History, select a report version and choose **Export MD**, **Export JSON**
or **Export PDF**. GET `/api/v1/research-runs/{id}/export?version=1&format=json|md|pdf`
requires an explicit version. Missing reports return 404; unsupported formats
return 422. Responses download as attachments and are not cached.

The JSON bundle's `report` is exactly the stored History report representation:
claim text, limitations, numeric claims, evidence IDs/URLs, model configuration,
IDs, version, and as-of date. A SHA-256 digest covers its sorted UTF-8 JSON.
Markdown and PDF use the same content and include an exact persisted-JSON appendix,
so no structured fields are lost. No LLM, provider, refresh, or recalculation runs.
Markdown escapes source markup; PDF escapes XML and never fetches external images.
PDF includes readable source URLs; JSON/Markdown preserve arbitrary Unicode.
Unsupported PDF glyphs fail explicitly rather than being silently substituted.

Saved charts come only from the frozen `charts` lane captured when the report
was persisted, with payload `{"charts":[{"artifact_id":"charts_<sha256>", ...}]}`.
Store permitted PNGs using `FileSystemArtifactStore(database_parent / "artifacts")`,
category `charts`, suffix `.png`, and save their titles, provenance, evidence IDs,
units and as-of metadata in each reference before persisting the report.
References are preserved in the JSON/Markdown export; PDF embeds the original PNG
and its artifact ID. Charts are not regenerated or read from current snapshots.
Missing legacy captures or missing/corrupt PNGs produce visible warnings.

PNG content must match its hash, remain inside the artifact directory, and be
at most 10 MB / 20 million pixels; at most 20 charts per manifest are supported.
JSON bundles embed base64 PNGs; Markdown uses data-URI images (some Markdown
viewers disable these); PDF embeds raster images. Generated exports and images
are local runtime artifacts and must not be committed. No chart data is added
to vector indexes.

Dependencies: ReportLab renders PDFs offline using the existing Matplotlib
DejaVu font; pypdf is a dev-only extraction/validation dependency. Both are locked.
Run `uv sync --locked --all-groups --inexact` to retain optional installed extras,
then `make check`. No API keys are required for exports.
