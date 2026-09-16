# Optional research forecast lane

Enable `ENABLE_KRONOS=true` only after preparing local pinned weights/source.
Research requests also need explicit opt-in:

```json
{"ticker":"AAPL","include_kronos":true,"forecast_horizon":5}
```

`forecast_horizon` counts exchange sessions, accepts 1–128, and defaults to 5.
`InitialResearchWorkflow` runs the optional node after collection snapshots are
persisted and before marking the run complete. It can also accept an injected
`kronos_node` for offline testing. Successful research lanes are retained even
when the optional node fails. No forecast is a prerequisite for a report or LLM
analysis; experimental forecasts are not silently added to report evidence.

The repository currently exposes collection through this workflow abstraction,
not a production live-provider scheduler. Merely creating a research run does not
start collection. Run your configured collection worker as before. The existing
generic job runner's placeholder collect/analyze/report steps are not live data
collectors; this feature does not invent missing market inputs.

## Required collector contract

The completed `ohlcv` snapshot must contain a `kronos_input` object with:

- `candles`: daily `Candle` records with session, OHLCV and optional amount.
- `sessions`: complete exchange schedule, including future horizon, as `Session`
  records (`day`, timezone-aware `closes_at`).
- `actions`: `CorporateAction` records with exact effective/known dates and factors.
- `as_of`, `timezone`, `currency`, `provider`, `calendar_source`, `input_policy`
  (`raw`, `split_adjusted`, or `total_return_adjusted`), `actions_complete`.

These fields match the existing `prepare_candles` boundary. The node never infers
a calendar from weekdays, fabricates action coverage, or invents OHLCV. Current
OpenBB single-date calendar metadata is insufficient; without a full collector
payload the lane returns `skipped` with an actionable warning. Preparation errors
also skip without retry; report data stays usable.

## API

- `GET /api/v1/research-runs/{id}/forecast`: typed lane status and metadata. No
  inference is triggered. Returns `pending` if no lane output exists.
- `POST /api/v1/research-runs/{id}/forecast`: execute/retry only this optional
  lane from stored snapshots; does not change the broader run's completion state.
- Add `?include_experimental=true` to explicitly retrieve experimental paths and
  summaries. Otherwise only currently eligible promoted output is returned.

Responses distinguish `disabled`, `pending`, `skipped`, `completed`, `failed`,
and `cancelled`. They include quality, warning, scoped cache key, model audit ID
on success, and typed forecast data when visible. Generic snapshot responses use
the same quality filter; they cannot expose experimental paths by accident.
OpenAPI documents request/response fields. Promotion is rechecked on reads, so a
new failed validation, changed policy, or expired validation removes normal
visibility. Explicit experimental reads retain the research-only label.

## Execution, caching and progress

`KRONOS_TIMEOUT_SECONDS` bounds each real inference subprocess (default 120,
maximum 600). `KRONOS_MAX_RETRIES` allows 0–3 retries (default 1), with short
exponential delays. Each attempt is audited by `KronosQuality`, and checkpoints
record the cache key, attempt and terminal state. Model errors are sanitized.
No new credentials, paid services, or automatic weight downloads are required.

Preparation, execution, retry and terminal events are persisted as `progress`
events with `lane="kronos"`, status, attempt, lane-local percentage, retry state
and warning. Existing SSE endpoints and Last-Event-ID replay expose them. The
percentage is lane-local, not a claim that the entire research run is complete.

Kronos runs in a worker thread so local subprocess inference does not block the
async event loop. The subprocess owns its hard timeout and memory cleanup.
Cancellation is checked before attempts and after inference; it prevents output
publication and subsequent retries but does not immediately kill an already
running subprocess. That subprocess remains bounded by its configured timeout.

Cache identity includes symbol, full prepared input/calendar/action provenance,
horizon, model/tokenizer/source manifest and inference configuration. The provider
cache now receives the instrument identity, preventing cross-ticker cache reuse.
Repeated execution uses its TTL cache, but always records a new audit entry and
reevaluates promotion; old checkpoint quality is never blindly reused. Concurrent
duplicate requests can still perform duplicate inference on a cache miss; this
is not a distributed queue or deduplication lock.

Set `KRONOS_POLICY_PATH` to a local JSON `PromotionPolicy` file to use an audited
promotion policy. Omission means experimental-only behavior, not auto-promotion.
See [quality/persistence](kronos-quality.md) for policy setup and limitations.

Offline verification:

```bash
uv run pytest tests/test_kronos_workflow.py
make check
```

Fixtures cover successful inference, retry exhaustion without broader run failure,
safe errors, saved failure audits, cache hits/ticker isolation, SSE progress,
experimental visibility, cancellation, invalid horizons, and missing inputs.
They do not load real weights or verify accelerator performance.

## Forecast web view

Select **Include optional Kronos research** when starting research, then open
**Forecast research and model card** from the run dashboard. The route is
`/runs/{run_id}/forecast`. Forecast execution remains explicit; polling only reads
saved output. **Show experimental research forecasts** is unchecked by default.
The run/retry button uses existing collector snapshots, not live data fabrication.

The responsive SVG chart shows up to the last 60 prepared historical candles,
a forecast boundary, 5–95% and 25–75% sampled bands and a dashed median. The
median is labelled as a sample statistic, never a guaranteed target. Missing,
single-sample or invalid bands suppress the chart rather than showing a standalone
prediction line. An expandable data table supplies accessible chart values.
Lower/median/upper terminal scenarios are percentile outcomes, not assigned
bull/base/bear probabilities.

The model card records version, cutoff, provider, currency, timezone, adjustment
basis, device, path count and warnings. New workflow snapshots retain the prepared
historical candles; older saved forecasts may not have them. The API adds a
read-only summary of the latest matching evaluation, including baseline metrics,
test-window dates, failure reasons and limitations. No evaluation record means
the UI says validation is unavailable. It never generates placeholder metrics.
Coverage/direction/drawdown fractions are formatted as percentages (0.9 = 90%);
undefined metrics remain unavailable. Validation results do not remove uncertainty.

Verification additionally includes component accessibility checks and
`npm --prefix frontend/web run test:e2e -- forecast.spec.ts` for desktop/mobile
rendering and explicit experimental opt-in. The browser test uses offline API
fixtures and does not demonstrate real model accuracy.
