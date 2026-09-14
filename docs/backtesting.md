# Point-in-time walk-forward evaluation

`financial_ai.analysis.backtest.walk_forward(dataset, config, strategy)` is an
offline, single-instrument, long-only research simulator. It has no provider,
LLM, model-weight, or API-key dependency. It does not establish calibrated
forecast confidence, recommend trades, or place orders.

## Inputs and callback

Build a typed `Dataset` containing symbol/provider/currency/timezone,
`TradingSession` entries (exchange-local open/close and calendar publication time),
raw `Price` vintages (open/close, actual availability time and unique evidence ID),
and `Action` records. Confirm complete corporate-action coverage explicitly.
Session times must be aware, ordered and nonoverlapping. Supply actual holidays
and early closes; the engine never invents weekdays or fills missing bars.

`available_at` means the data was actually usable by the simulated strategy,
including publication and ingestion latency, not the historical period label.
Keep original and revised prices separately. The latest eligible vintage is
selected for each training session; the latest version in today's database is
not automatically eligible. Full-session data cannot be available before close.
Adjusted history is rejected because today's adjustments can leak future actions.
The strategy receives raw prices and known actions and is responsible for any
as-of adjustment used in fitting; never interpret a raw split jump as a return.

```python
from financial_ai.analysis.backtest import Decision, WalkForwardConfig, walk_forward

def baseline(view):
    # Illustrative allocation rule, not a trading recommendation.
    return Decision(allocation=1, evidence_ids=(view.prices[-1].evidence_id,))

config = WalkForwardConfig(
    mode="rolling", train_sessions=60, horizon=5,
    fee_bps=5, slippage_bps=10, initial_cash=10000,
    strategy_version="constant-long-v1",
)
result = walk_forward(dataset, config, baseline)
```

Each callback receives an immutable `Snapshot`: cutoff, as-of training prices,
known corporate actions, and future session times only. It never receives future
prices or evaluation labels. Fit preprocessing and model parameters only on this
snapshot, independently for each fold. Return a validated allocation in [0, 1]
and citations limited to the snapshot's evidence. Out-of-window or future
citations fail with `LeakageError`. A trained/pretrained strategy must specify
`strategy_kind="trained_model"` and an auditable `model_training_cutoff`; later
cutoffs are rejected. Do not substitute a weight download date for a training
cutoff. Kronos is not automatically wired into this engine.

## Fold and execution rules

- Rolling windows keep `train_sessions`; expanding windows keep all prior sessions.
- A decision uses the last training close plus `decision_delay_seconds` and must
  precede the next session's open. Unknown calendar vintages fail explicitly.
- Folds advance by `horizon`, avoiding overlapping test portfolios. Training may
  use prior completed test sessions, as it would in live walk-forward refitting.
- Allocate a fraction of available cash at the next open, hold through the test
  window, and liquidate at its final close. Remain flat overnight between folds.
  Unused incomplete tail sessions are reported, not silently extrapolated.
- Fractional shares are allowed, without leverage or shorts. Fees are charged on
  each executed notional. Slippage increases the buy price and decreases the sell
  price; the allocation budget includes the entry fee.
- Outcome fills use the first published raw-price vintage, isolated from the
  callback. Their evidence IDs are recorded separately from training evidence.

## Corporate actions and accounting

Splits multiply held shares by new/old ratio at session open. Dividends create a
cash receivable on the ex-date for shares held overnight. Entry on the ex-date
gets no entitlement. Same-session split/dividend records mean split first and
dividend per post-split share. Ambiguous duplicate actions and unsupported types
are rejected rather than guessed. Supply dividends in the dataset currency and
their actual payment dates (`payable_session`, which may be a nontrading date).

Receivables count toward equity but are not spendable. Payments through a fold's
exit date are credited at exit and available for the next fold. There is no
intrahorizon reinvestment. Results record cash, receivables, fees, slippage,
dividend accruals/payments and net fractional returns. `0.39` means 39%.

## Scope and limitations

This is an in-process research boundary, not a security sandbox: a Python callback
can close over external data. Use trusted callbacks with no external I/O, reset
state between evaluations, and record strategy/model versions. Claimed timestamps,
historical universes, calendars and action completeness require trustworthy data;
the engine cannot discover fabricated metadata or survivorship bias. Revised or
late-discovered corporate actions need a curated vintage ledger, not today's
auto-adjusted series. Emergency calendar changes unknown at a cutoff fail closed.

Fixed-bps costs do not simulate order books, impact, capacity, taxes, settlement
delays, delistings, mergers, options, or FX. Research NAV credits dividend payments
at fold exit as described above. This module is not yet an API/UI backtest service
or a persisted model-validation registry. Do not infer out-of-sample forecast
accuracy from simulated trading P&L alone.

Verification: `uv run pytest tests/test_backtest.py`. Offline fixtures exercise
rolling/expanding windows, holidays, costs, revisions, next-open execution, split
continuity, ex-date entitlement and unpaid dividends. Synthetic premature bars,
unavailable vintages/calendars, future citations and model training leakage fail
explicitly; perturbing future prices leaves the first decision unchanged.

## Matched forecast baselines and metrics

`financial_ai.analysis.forecast_evaluation.compare_forecasts` runs six baselines
and a caller-supplied Kronos forecast callback on identical walk-forward training
windows, test sessions, horizons, currency, cost settings and raw-price vintages.
It returns every forecast, outcome/evidence IDs, per-window metrics, aggregate
metrics and the corresponding trading simulation. No live requests are required.

```python
from financial_ai.analysis.forecast_evaluation import compare_forecasts, kronos_prediction

def predict_kronos(view):
    # Caller must obtain PIT OHLCV for exactly view.prices and use only its
    # as_of and forecast_sessions. Never fabricate high/low/volume from closes.
    prepared = prepare_matching_ohlcv(view)
    return kronos_prediction(local_provider.forecast(prepared))

comparison = compare_forecasts(
    dataset, config, kronos=predict_kronos,
    kronos_version="audited-model-and-adapter-version",
    kronos_training_cutoff=audited_training_cutoff,
    seed=0, samples=512,
)
```

`prepare_matching_ohlcv` and `audited_training_cutoff` are caller-supplied inputs,
not bundled functions or invented training metadata. This engine's open/close
dataset lacks the OHLCV needed for Kronos; it therefore accepts a trusted callback
and provides `kronos_prediction` to adapt the local provider's median/5th/95th
percentiles. Use at least two Kronos paths and do not silently truncate a training
window to its model context limit. Record its full version, sampling configuration
and input provenance outside the callback as part of the evaluation artifact.
Tests use a clearly identified fixture callback, not actual Kronos weights.

Baseline definitions (fit afresh only on each training window):

- Last-value: constant final observed close, no artificial interval.
- Drift: final close plus horizon times first-to-last slope.
- Linear: ordinary least-squares price against session index, extrapolated.
- Random-walk: zero-mean Gaussian price increments, sample standard deviation of
  training price differences; point forecast equals last close. Seeded simulation
  provides marginal 5th/95th percentiles.
- Volatility: zero-log-drift simulation, with EWMA squared log-return variance
  (decay 0.94, initialized to first squared return). Point forecast is the median,
  last close; intervals come from seeded paths. It is not a fitted GARCH model.
- ARIMA: fixed (1,1,0) with drift (`trend="t"`), using existing statsmodels and
  nominal 90% forecast intervals. Minimum eight observations; failed convergence
  fails the comparison, never substitutes a different baseline.

The random seed is reset for each stochastic baseline/window, giving reproducible
common random numbers. Point forecasts must be positive/finite; Gaussian intervals
may include negative values and are not clipped or claimed to respect a price
floor. Missing/malformed predictions or wrong dates fail the entire comparison.
Currently any corporate action in the supplied dataset also fails the comparison:
raw and adjusted forecasts must not be scored against incompatible targets. Supply
an action-free evaluation dataset until a shared point-in-time adjustment adapter
is implemented. Never selectively omit windows based on a model's performance.

MAE and RMSE use every horizon step in currency units. MASE divides each fold's
MAE by its training-only mean absolute one-session naive difference. Zero scales
produce null with a reason, not zero or infinity. Terminal direction accuracy
compares the sign of terminal change from the last observed close, with flat as
a distinct outcome. Interval coverage counts inclusive hits in nominal 90% bands;
models without intervals have null coverage. Coverage is observed performance,
not an assurance of calibrated confidence.

`mean_window_metrics` equally weights complete, equal-length windows; aggregated
RMSE takes the square root of the mean squared window RMSE (pooled error), not
the mean of RMSEs. If any window has undefined MASE/coverage, its aggregate is
null instead of silently excluding that window. No ranking mixes currencies or
different horizons.

For trading diagnostics only, all models use the same fixed rule: fully long if
the terminal point exceeds the last close, otherwise cash, with the existing
next-open entry/final-close liquidation and identical fees/slippage. Turnover is
the sum of both executed leg notionals divided by each fold's starting equity;
it is an equity multiple, not annualized or halved. `max_fold_end_drawdown`
measures peak-to-trough decline from initial capital at fold exits only. It does
not claim intraperiod/daily maximum drawdown. Forecast errors and trading outcomes
are kept separate; neither alone establishes forecast confidence.

Run `uv run pytest tests/test_forecast_evaluation.py` for deterministic offline
formula, seeded simulation, real ARIMA, matching-window and failure tests.
ARIMA reference: [statsmodels official API](https://www.statsmodels.org/stable/generated/statsmodels.tsa.arima.model.ARIMA.html).
