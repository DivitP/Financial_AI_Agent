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
and inference loading remain separate from base API startup; this change does not
implement predictions. Only the small/base-tokenizer pairing is reviewed.

References: [official source and installation](https://github.com/shiyu-coder/Kronos),
[model card](https://huggingface.co/NeoQuasar/Kronos-small),
[tokenizer card](https://huggingface.co/NeoQuasar/Kronos-Tokenizer-base).
