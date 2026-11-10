# Saved research mode and complete demo

The default `financial_ai.workflow.demo:handler` delegates to the synthetic
handler and shared `ResearchPipeline`. An AAPL demo produces source snapshots,
fundamental metrics (including the fixture's 39% gross margin), technical
conditions, 60-point chart history, an artifact-backed PNG, indexed source text,
and an immutable evidence-linked report. No LLM or provider request is required.
ETFs skip corporate statements. Unsupported symbols fail without live fallback.

The dashboard draws price history from saved observations. A PNG is also saved
through the artifact store before report creation and captured in the report's
chart manifest, so reopening/exporting uses original data rather than regenerating
from a current provider. Exports can include this PNG. Chart values and titles
identify synthetic data; no prediction or trade instruction is implied.

## Persistence contract

`model_config_json.research_mode` is the canonical per-report-version persisted
field. It uses the existing versioned JSON metadata rather than a schema migration.
Report responses and exports additionally expose a top-level `research_mode`.
History list rows use the latest saved report's mode; reopening a specific version
uses that version's mode, as does its export. Report-version immutability already
rejects changes to model metadata, including mode.

- `synthetic`: all source evidence is explicitly synthetic.
- `live`: this pipeline's evidence is entirely from its supported Yahoo/SEC/RSS
  adapters, with no synthetic tier. This is provenance, not a quality certification.
- `unknown`: mode was not recorded, is invalid, or the pipeline cannot establish
  a uniform supported origin (including mixed/other providers).

Older saved records are not rewritten. Missing mode is returned as `unknown` with
a warning, never inferred from current settings, current snapshots, a ticker,
or whether the report sounds plausible. Custom report producers must explicitly
record valid mode metadata if known; otherwise they remain unknown. No automatic
historical reclassification is performed.

Markdown and PDF display the mode and a warning near the top; JSON retains it
alongside the original model configuration. React reports and saved history show
the same distinction. Old report responses without the field render an explicit
unknown-mode message. Export claims, citations, dates and saved chart references
are unchanged by these labels.

## Verification

`uv run pytest tests/test_demo_provenance.py tests/test_local_compose.py --no-cov`
covers the real demo pipeline, persisted index/chart/report, process restart,
version-specific modes, old unknown records, and JSON/Markdown/PDF output.
Demo tests block outbound socket connections. `make check` covers UI labels,
existing report/history/export contracts and the unchanged coverage floors.
Container smoke now checks actual chart/report output, but a local fixture pass
does not claim Docker/Postgres/Redis were started or validated on this machine.
