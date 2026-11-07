# Application coverage baseline and regression policy

Coverage includes every discoverable Python module under `src/financial_ai`,
including unimported modules (zero coverage), alongside retained legacy code and
root settings. Branch measurement is enabled. Pytest uses bare `--cov` so its
command line does not replace the source list in `pyproject.toml`.

## Reproduce and inspect

```bash
uv sync --locked --all-groups
make test
# Re-render/gate the most recent coverage data without rerunning tests:
make coverage-report
```

`make test` first runs the full offline suite, then checks coverage. `make check`
includes this gate. CI runs it on both supported Python minors and uploads split
reports per matrix entry. Release evaluation has a separate coverage stage,
blocked if its Python stage fails. No provider keys or live requests are required.

Generated `data/runtime/coverage/` contains `summary.md`, `summary.json`, and
separate `replacement`, `legacy`, and `shared-settings` JSON/text reports with
per-file missing lines and branches. `.coverage` contains the underlying execution
data. These are ignored artifacts, not source assets. Release evaluation writes
the reports under its own timestamped `coverage/` directory.

`uv run pytest` alone collects coverage but does not enforce the split gate;
use `make test` for a validated result. Focused tests overwrite `.coverage` by
default: never use a focused run as the full-suite baseline. `--no-cov` remains
available for fixture suites that intentionally do not measure coverage.
`make coverage-report` assumes the latest full run succeeded; CI always reruns
tests first rather than trusting a stale data file.

## Measured base-install baseline (2026-11-06)

macOS arm64, Python 3.12.13, locked dev dependencies, no optional vector/scale
extras or external services. The pre-gate suite had 290 passing tests and seven
skips: six Postgres/Redis integration tests and one optional Chroma integration.
Adding coverage infrastructure tests does not exercise application code.
The final suite passed 296 tests with the same seven skips on Python 3.12.13
and 3.13.14; both produced the identical counts below. Python 3.13 additionally
reported SQLite ResourceWarnings; these were not suppressed. Linux CI execution
is not claimed by this local validation record.

| Scope | Covered / executable lines | Line coverage | Covered / possible branches | Branch coverage |
| --- | --- | --- | --- | --- |
| Replacement `src/financial_ai` | 5699 / 6475 | 88.02% | 1128 / 1614 | 69.89% |
| Legacy `agents`, `frontend`, `main.py` | 409 / 1533 | 26.68% | 61 / 280 | 21.79% |
| Shared `settings.py` | 91 / 101 | 90.10% | 20 / 30 | 66.67% |

Shared settings serve both implementations and are not mislabeled legacy.
Frontend here means retained Python Flask code; React/TypeScript coverage is
not measured by coverage.py. Browser tests and Vitest results are separate checks.

## Threshold justification

Replacement code must meet **87% line coverage and 69% branch coverage**, each
compared before rounding. These floors sit 1.02 and 0.89 percentage points below
the measured baseline, respectively, allowing small platform/interpreter path
differences without setting an aspirational threshold the current suite cannot
pass. High line coverage cannot compensate for low branch coverage. Floors live
in `[tool.financial-ai.coverage]`; they are not a combined replacement/legacy total.

Legacy and shared settings are reported, not gated by these floors. Migrating or
deleting legacy code must not conceal a replacement coverage regression. Missing
groups, empty totals and line-only data fail rather than silently passing. Negative
tests deliberately lower line/branch counts and verify rejection at the boundary.

This is a modest initial regression guard, not permission to spend the remaining
margin on untested features. Review changed-line tests and per-file branch gaps;
raise floors as stable coverage improves. Any decrease requires a documented
reason, before/after measurement, and explicit review—not rebaselining to make CI
green. Avoid excluding hard-to-test production modules or adding `no cover` to
inflate the result.

## Interpretation limits

Offline fixtures exercise contracts, not live financial accuracy. Optional
services, real model weights/GPU, subprocess inference interiors and live-provider
behavior need separate validation. Unexecuted parent-package modules remain in
the denominator; spawned-process execution is not claimed unless instrumented.
This baseline is neither feature-parity approval nor a security certification.
