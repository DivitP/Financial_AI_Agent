# Optional Kronos environment

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
