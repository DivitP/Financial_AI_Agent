# Hypothetical portfolio context

Open **Portfolio context**. Enter 1–10 distinct tickers with percentage weights
totaling 100, then a candidate ticker with a weight strictly between 0 and 100.
Existing weights are reduced proportionally; an existing candidate ticker is
merged into its existing allocation. No shorting, cash, leverage, optimization,
brokerage connection, or trade execution is supported. Inputs are not persisted.

POST `/api/v1/portfolio-context` accepts:

```json
{"holdings":[{"ticker":"AAPL","weight":100}],"candidate":{"ticker":"MSFT","weight":20}}
```

Concentration is calculated from hypothetical weights (largest weight and HHI).
ETF constituent overlap is not modeled. Sector weights use saved instrument
sector or ETF fractional `sector_exposure`; unknown weight remains explicit.
Saved `factors` snapshots can supply `model` and `loadings`. Factor results
are partial weighted loadings grouped by model, with covered weight, never
assumed complete. They are not estimated from insufficient data.

Reads use the latest terminal run for each unique saved instrument and only
run-scoped cited snapshots. No providers, jobs, or language models are invoked.
The source panel retains evidence URLs, retrieval times, and run links. These
are saved observations, not fresh quotes or personal financial advice.

The accepted `ohlcv` snapshot has `currency`, `timezone`, `interval: "1d"`,
`adjustment_policy: "split" | "split_and_dividend"`, and `bars` containing
ISO-date `session` and positive `close`. All series must share metadata,
have at least 21 common prices, at most 2521 prices each, and matching session
grids throughout the overlap. Unknown formats/metadata produce unavailable
risk, not guessed dates, FX conversions, forward fills, or dropped holdings.

Both portfolios use identical overlapping sessions. Simple returns feed Pearson
correlations, sample daily volatility, and compounded-wealth maximum drawdown,
starting at wealth 1. Constant weights imply daily rebalancing; fees, taxes,
and slippage are omitted. Constant series have undefined (null) correlations.
Volatility and drawdown are fractions; no annualization or forecast confidence
is reported. Split-only prices exclude dividend return. Historical correlation
does not predict future diversification.

Tests: `make check` includes known-path risk calculations, missing/incompatible
prices, partial exposures, request validation, and network/job isolation.
