# Kronos promotion and audit records

Kronos remains **experimental research by default**, including direct provider
calls and cache hits. No model weights or historical validation results bundled
with this project authorize promotion. Passing a gate is scoped research
validation, not investment advice or calibrated probability confidence.

Schema migration 8 adds append-only `model_runs` records in the application SQLite
database. `ModelRunRepository` stores evaluation comparisons, policy snapshots,
dataset hashes, model/configuration identity, scope, timestamps, safe failure
categories, limitations, raw forecast paths and summaries. These are runtime
artifacts, never files to commit. Exceptions do not persist arbitrary exception
messages, which may include credentials. Writes are transactional. Repeated runs
create distinct audit entries rather than overwriting earlier failures.

## Configure and evaluate

```python
from datetime import datetime, UTC
from financial_ai.storage.database import Database
from financial_ai.storage.model_runs import ModelRunRepository
from financial_ai.kronos.quality import (
    KronosQuality, PromotionPolicy, Scope, fingerprint,
)

db = Database("data/runtime/research.sqlite3")
db.migrate_to_latest()
policy = PromotionPolicy(
    version="holdout-policy-v1",
    frozen_at=datetime(2026, 1, 1, tzinfo=UTC),  # actual preregistration time
    min_windows=30, max_mase=1, min_direction=.55,
    min_coverage=.85, max_coverage=.95, min_error_improvement=.05,
    max_drawdown=.25, max_turnover=100, valid_days=30,
)
quality = KronosQuality(ModelRunRepository(db), policy)
scope = Scope(
    symbol=dataset.symbol, currency=dataset.currency, timezone=dataset.timezone,
    adjustment_policy="total_return_adjusted_as_of",
    context=config.train_sessions, horizon=config.horizon,
    model_fingerprint=fingerprint(local_provider),
)
evaluation = quality.evaluate(
    scope, dataset, config, kronos=predict_kronos,
    training_cutoff=audited_model_training_cutoff,
)
```

`dataset`, `config`, `predict_kronos`, `local_provider`, and the audited training
cutoff come from the [comparison setup](backtesting.md). The callback must use
that exact provider/configuration and complete as-of input window. The fingerprint
binds pinned source/model/tokenizer manifests, adapter version and inference
configuration. Use the same software environment as validation; software package
versions are not currently included in the fingerprint. Changing them requires
a new policy version and revalidation. Example thresholds are conservative
configuration examples, not statistically proven universal cutoffs.

Promotion requires all of:

- Matching symbol, currency, timezone, rolling context length and horizon.
- Completed historical outcomes and a policy frozen no later than each decision.
- Point-in-time comparison checks, including model-training cutoff, to pass.
- At least the configured number of nonoverlapping evaluation windows.
- Finite, defined MASE, direction and nominal 90% interval coverage within bounds.
- MAE **and** RMSE improving by the configured fraction over **every** baseline.
- Fold-end drawdown and turnover within configured limits.

Missing metrics, comparison failures, mismatched scope or insufficient samples
remain experimental. A perfect baseline (zero error) cannot be beaten under
this gate. Full failures are recorded with a safe error type; comparisons that
abort cannot supply a complete metric table. The gate does not quietly drop failed
models/windows or optimize thresholds against the test results.

The comparison currently supports action-free datasets and rolling windows for
promotion. Raw and `total_return_adjusted_as_of` scopes must be declared separately;
on these action-free windows the caller must ensure identical price units, without
future adjustment factors. Expanding-window promotion is deferred because one
fixed inference context cannot represent all expanding training lengths.

## Persist and display inference

```python
record = quality.forecast(local_provider, prepared, symbol="AAPL")
scope = Scope.model_validate(record["scope"])
normal_results = quality.visible_forecasts(scope)
research_history = quality.visible_forecasts(scope, experimental=True)
```

Use this service, not direct provider calls, for auditable inference persistence.
It stores success, cache-hit output, warnings, configuration/input hash and failure
records. `result.research_only` and `result.quality.status` explicitly label the
output. No validation confidence number is created. Existing unvalidated warnings
are retained even when promotion passes.

Normal visibility requires both a promoted forecast and a currently passing,
unexpired latest evaluation for its exact scope and policy. A newer failed or
underperforming evaluation revokes normal visibility. Experimental history retains
all results and failures. Validation recorded after a historical forecast cutoff
cannot retroactively promote that forecast. Changing policy or scope defaults back
to experimental; expired validation must be rerun. Validity age is measured from
evaluation execution, not the age of its historical dataset: reviewers must select
a relevant holdout period and account for regime changes.

The [forecast API/workflow](kronos-workflow.md) now consumes these records and
applies the same eligibility rules. Future UI consumers must use filtered API
output or an explicitly labelled experimental research view;
they must not query the raw audit table as a promoted feed. The direct provider
always labels its output experimental and does not itself write this audit log.

This is a trusted local research service, not a tamper-proof attestation: callback
integrity, true training cutoffs, preregistration timestamps, independence from
hyperparameter tuning, data licensing and survivorship bias require external
review. Threshold passing is not a statistical significance claim or proof of
out-of-sample calibration.

Verification: `uv run pytest tests/test_kronos_quality.py tests/test_storage.py`.
Tests use synthetic gate results, not actual Kronos performance. They cover
promotion, underperformance, safe failure retention, expiry, scope/policy changes,
restart persistence, experimental-only visibility, rollback and migration reversal.
