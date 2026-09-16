# Optional Kronos environment

## Daily candle preparation

`financial_ai.kronos.preprocessing.prepare_candles` takes typed daily `Candle`
records, `Session` calendar entries, and `CorporateAction` records. It returns
adjusted candles, exchange-local historical/future close timestamps, provenance,
adjustment policy, missing dates, applied action IDs and truncation metadata.
It imports no PyTorch and does not run predictions.

Supply the complete exchange schedule from the earliest input candle through the
requested horizon. A generic weekday calendar is insufficient: holidays must be
absent and early closes must carry their actual close time. The caller is responsible
for calendar completeness and confirmed action coverage. This function cannot detect
an omitted holiday or unreported split in an incorrectly labelled provider response.
The current OpenBB single-date calendar metadata is not a complete schedule; collect
one before using this preprocessing boundary. Naive daily provider dates must be
mapped to exchange-local session labels by the caller, not interpreted as UTC closes.

For raw candles, a split ratio means new shares divided by old shares. Earlier OHLC
is divided by this ratio and volume multiplied by it. Split-adjusted input is not
split-adjusted again; its volume must already use the corresponding share basis.
Dividends require explicit provider historical-price factors unless input is already
total-return adjusted. Other action types fail closed. Adjusted inputs must be
anchored at this as-of cutoff, with no adjustments from later events. Known actions
inside the forecast horizon block preparation pending an inverse-adjustment layer.

Missing completed sessions fail by default, including a missing latest candle.
`missing_policy="contiguous_suffix"` retains only the uninterrupted suffix after
the final gap, requires at least two observations and records a warning. There is
no fill-forward or zero-volume holiday insertion. The final context is capped by
the manifest's 512-session limit. Future dates come only from the supplied schedule.

Optional `amount` means observed traded currency turnover. It is retained only
with full coverage and no newly applied adjustment; otherwise the entire amount
column is omitted. No close-times-volume approximation is generated. Prices and
volumes must be finite, positive/nonnegative and internally consistent.

Offline fixtures cover split/dividend continuity, holiday exclusion, incomplete
sessions, context truncation, future actions, and amount handling.

Base install: `uv sync --locked --all-groups` (no Kronos extra).
Opt-in runtime: `uv sync --locked --extra kronos`.
The extra includes PyTorch, einops, tqdm, Hugging Face Hub and safetensors;
existing accelerate/transformers entries are retained for compatibility. These are
runtime dependencies, not model weights. No paid API or key is required.

Upstream has no Python packaging metadata at the reviewed commit. Do not install
the unrelated PyPI `kronos` package. The manifest pins the official source checkout
separately. To prepare it manually:

```bash
git clone https://github.com/shiyu-coder/Kronos.git data/runtime/kronos/source
git -C data/runtime/kronos/source checkout --detach 67b630e67f6a18c9e9be918d9b4337c960db1e9a
```

The packaged `financial_ai/kronos/manifest.json` pins both Kronos-small and its
base tokenizer. Revisions and LFS SHA-256 hashes were read from official Hugging
Face metadata; configuration hashes are explicitly Git blob SHA-1, not SHA-256.
Source and model cards declare MIT: preserve upstream copyright/license notices.
Input market-data rights are separate. No forecast confidence is established by
these pins or upstream benchmark claims.

`load_manifest()` works with the installed package and imports no torch or hub
library. Local artifact layout is
`KRONOS_CACHE_DIR/{model|tokenizer}/{revision}/{model.safetensors|config.json}`.
`ArtifactPin.verify(cache_root)` checks size, weight SHA-256 and configuration blob
hash without loading a model. Missing or altered files fail verification.

`ENABLE_KRONOS=false`, CPU device and downloads disabled are the defaults. The
download flag is reserved for an explicit future acquisition command: setting it
does not download anything. Startup and tests never fetch weights. Source checkout
and inference loading remain separate from base API startup. Only the
small/base-tokenizer pairing is reviewed.

## Local inference

For optional research orchestration and HTTP endpoints, see
[the forecast workflow/API](kronos-workflow.md).

After preparing the pinned local assets above, use the provider with the output
of `prepare_candles`:

```python
from settings import Settings
from financial_ai.kronos.inference import InferenceConfig, LocalKronosProvider

settings = Settings()  # ENABLE_KRONOS=true is required to forecast
provider = LocalKronosProvider.from_settings(settings, config=InferenceConfig(
    device=settings.kronos_device, seed=0, timeout_seconds=120,
    sample_count=8, temperature=1.0, top_p=0.9, cache_ttl_seconds=3600,
))
forecast = provider.forecast(prepared)
```

Construction never imports PyTorch or loads weights. Each cache miss launches a
fresh offline worker, verifies the clean pinned source checkout and artifact
hashes, and loads the tokenizer/model from local directories. Explicit `cpu`,
`mps`, and `cuda` selection is supported; unavailable devices fail rather than
silently changing device. Seeds and strict deterministic algorithms are set;
reproducibility is limited to the same device/software environment, not promised
across hardware. Unsupported deterministic operations fail closed.

The timeout includes loading and inference. The child exits after each request;
timeouts kill and reap it, releasing its model memory. This favors bounded memory
over warm-model latency. It is not a process-pool or distributed GPU scheduler.
SQLite TTL caching under `KRONOS_CACHE_DIR/forecasts.sqlite3` keys on prepared
inputs, pinned manifest, adapter version, and configuration. Failed or malformed
forecasts are never cached. Delete this disposable cache after changing the
runtime dependency environment. Concurrent cache misses may each run inference.

Results identify model/tokenizer/source revisions, device, configuration,
timestamps, currency, units, adjustment policy and warnings. Predicted OHLCV must
be finite and internally consistent; invalid outputs are rejected, not repaired.
Missing turnover is explicitly encoded as a zero input placeholder, preventing
upstream's automatic synthetic turnover estimate; this may affect model quality
and is disclosed in warnings. It is never returned as observed turnover.
No confidence or trading recommendation is produced. The optional research lane
and forecast API wrap this provider; no forecast UI is included yet.

Offline tests exercise the worker with a fixture model/tokenizer on CPU, device
failures, cache hits/expiry, and real subprocess timeout/error handling. They do
not validate downloaded weights, real-model accuracy, or GPU performance.

## Probabilistic paths

For persisted evaluation/inference records and promotion rules, see
[the Kronos quality gate](kronos-quality.md). Direct inference remains experimental.

For point-in-time strategy evaluation, see [the walk-forward engine](backtesting.md).
It requires trustworthy data and model-training cutoffs; Kronos integration and
forecast calibration are separate from the engine itself.

`sample_count` requests 1–16 complete OHLCV paths (default 1 for compatibility).
The worker draws sequentially with upstream `sample_count=1`, avoiding its
internal averaging. Models load once per request; all draws share the original
context and horizon. Path seeds are `(seed + path_index) % 2**32` and are returned
alongside raw `paths`. The timeout bounds the entire request, not each draw.
Any invalid path fails the whole forecast; none are silently removed, repaired,
or resampled. Cache version `local-v2-paths` excludes old averaged forecasts.

`candles` now contains component-wise median OHLCV, a summary rather than an
actually sampled trajectory. `summary.bands` contains pointwise closing-price
5th/25th/50th/75th/95th percentiles, using linear interpolation at `(n-1)*q`.
These are marginal bands, not simultaneous trajectory coverage or calibrated
confidence intervals. Small sample counts produce particularly unstable tails.

Direction probabilities are terminal close frequencies above/equal/below the
last adjusted observed close. `terminal_return` stores each path's terminal
simple return (`final / reference - 1`), its mean (model-implied expected return),
and percentiles. `session_volatility` stores each path's sample standard deviation
of simple session returns, including the first forecast return from the observed
close, plus cross-path mean and percentiles. It is not annualized and is null for
a one-session horizon. Returns/volatility are decimal-string fractions: `0.39`
means 39%, not 0.39%. Direction frequencies are numeric fractions.

Fixed seeds reproduce raw paths and summaries with the same inputs, pinned model,
configuration, device and software environment. Generation timestamps are not
expected to repeat. Offline stochastic fixture tests verify fresh uncached repeat
runs, changed seeds, seed wraparound, quantiles, ties, missing volatility, and
invalid paths. No out-of-sample calibration or real-weight accuracy is claimed.

References: [official source and installation](https://github.com/shiyu-coder/Kronos),
[model card](https://huggingface.co/NeoQuasar/Kronos-small),
[tokenizer card](https://huggingface.co/NeoQuasar/Kronos-Tokenizer-base).
