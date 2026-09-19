# Reproducible Kronos regression suite

Run from the repository root, with the locked development environment:

```bash
uv sync --locked --all-groups
make kronos-benchmark
```

This runs the standalone pytest suite and writes a machine-readable report to
`data/runtime/benchmarks/kronos-fixture.json`. Reports, caches and weights are
ignored runtime artifacts. The committed JSON files under `benchmarks/kronos`
are authored test assets and approved fixture expectations, not downloaded data.

## Coverage and reproducibility

The nine cases use representative instrument labels: AAPL/MSFT/NVDA equities and
SPY/QQQ ETFs. **All prices, volumes and outcomes are synthetic**, not historical
observations about those instruments. Cases cover rising, quiet, volatile and
drawdown regimes, a 2:1 split, missing volume, and one/two-session contexts.
The explicit September 2026 session schedule omits the weekend and September 7;
no inferred generic business-day calendar is used.

- Missing volume must fail validation; it is never filled with zero.
- One-session history must fail; two sessions test the minimum accepted context.
- Split fixtures must retain constant adjusted prices and share-basis volumes.
- Accepted cases generate eight paths over three sessions with seed 17.
- Two distinct disposable caches force two fresh worker invocations. Raw paths
  and summaries must match exactly. A third call verifies identical cached paths.
- `golden.json` pins SHA-256 hashes of fixture paths and summaries; unexpected
  implementation drift fails CI. Review intentional changes rather than blindly
  replacing expectations to make failures disappear.
- MAE/RMSE thresholds and per-case runtime smoke budgets live in
  `thresholds.json`. MASE, direction and interval coverage are also recorded;
  zero-scale MASE remains null. These metrics use synthetic held-out prices.
- The deliberate-regression test corrupts an approved reference hash and requires
  a failure. An environment/configuration/fixture mismatch rejects comparison.

The fixture worker is a tiny seeded CPU protocol stub, **not Kronos**. It exercises
preprocessing, subprocess invocation, forecast validation, cache behavior and
metrics without PyTorch or weights. Passing it says nothing about real prediction
accuracy. No benchmark output is sent to the promotion gate.

## Optional real-weight execution

Prepare the pinned source/assets as described in [Kronos setup](kronos.md), then:

```bash
uv sync --locked --all-groups --extra kronos
uv run python -m benchmarks.kronos.run --mode local --device cpu \
  --output data/runtime/benchmarks/kronos-local-cpu.json
```

Use `--assets` and `--source` for alternate local paths. The runner never downloads
weights or needs API keys. Missing dependencies, corrupt assets, unsupported
deterministic operations or invalid model candles fail the affected cases. CPU,
MPS and CUDA use the same configuration but require separate reviewed references.
To opt into the real-weight pytest case, set `KRONOS_BENCHMARK_LOCAL=1`; optional
`KRONOS_BENCHMARK_DEVICE` selects the device. These variables do not affect normal
fast CI because the benchmark tests are outside its discovery path.

After manually reviewing a successful local report, preserve it as a reference:

```bash
uv run python -m benchmarks.kronos.run --mode local --device cpu \
  --reference data/runtime/benchmarks/kronos-local-cpu.json \
  --output data/runtime/benchmarks/kronos-local-cpu-candidate.json
```

A reference comparison requires matching OS/architecture, Python/dependency
versions, lock hash, manifest pins, inputs, thresholds, device and configuration.
It rejects any raw-path hash change and MAE/RMSE increases over 5% plus 1e-6.
Exact path equality is intentional for a deterministic regression check, not a
promise of cross-device floating-point reproducibility. Without `--reference`,
local mode applies only the absolute smoke thresholds and within-run repeated
inference check; it is not a comparison with a previously approved real model.
Local absolute limits are provisional guardrails, not performance claims.

## Hardware and timing measurements

Every report records OS, architecture, reported processor, logical CPU count,
Python and relevant package versions, device, lock hash, full model manifest,
sampling configuration and fixture hash. It records two uncached call durations,
cache-hit duration and total accepted-case duration. Uncached calls include
worker startup, integrity checks, loading and inference; they are not kernel-only
latencies. No warm-up is excluded and OS filesystem caches are not flushed.

Peak RSS uses process-lifetime `resource.getrusage` high-water marks for the
parent and terminated children, converted for macOS/Linux units. It is not a
per-case allocation measurement, sum of concurrent RSS, GPU VRAM measurement, or
portable Windows profiler. For accelerator runs, record the exact GPU model,
driver/runtime and VRAM externally alongside the report; automatic GPU hardware
telemetry is not implemented here.

Measured fixture-only smoke run on 2026-09-19:

- macOS 15.3, arm64 (`processor=arm`), 10 logical CPUs; Python 3.12.13.
- NumPy 2.5.2, pandas 2.3.3, Pydantic 2.13.4. Installed torch 2.13.0 was **not
  imported or used by the fixture worker**.
- Seven accepted cases: approximately 18–20 ms per uncached fixture call,
  0.34–0.42 ms per cache hit, and 38–40 ms total per case.
- Parent peak RSS approximately 44 MiB; child peak RSS approximately 11 MiB.
- Two expected input rejections; no unexpected failures. No real weights,
  accelerator throughput or real Kronos forecast quality were measured.

These are single-machine observations, not universal latency targets. Broad smoke
limits accommodate CI scheduling noise; rerun multiple times on matched hardware
before drawing performance conclusions.

## CI separation

Normal `pytest`/`make check` still discover only `tests/`. The standalone suite is
marked `kronos_benchmark` and lives under `benchmarks/kronos`. No inference benchmark
was added to pull-request CI. `.github/workflows/kronos-benchmark.yml` runs the
fixture regression gates weekly or through **workflow_dispatch**, with reports
uploaded even on failure (14-day retention). Real weights are neither downloaded
nor executed in hosted CI. Run local mode explicitly on provisioned hardware.

Statistical out-of-sample validation on licensed real data, broader market-regime
coverage and promotion decisions remain separate from these synthetic regression
checks. Do not label any resulting probability or band calibrated confidence.
