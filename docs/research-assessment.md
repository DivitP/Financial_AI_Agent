# Live research assessment in the Flask interface

The Flask compatibility interface now leads with a cited research assessment,
followed by market/profile records, headlines, and historical technical charts.
This capability is not yet integrated into the replacement React dashboard.
It is research and education, not personalized allocation advice or trade execution.

## Run and configure

Preserve your existing `.env`. Set `SEC_USER_AGENT` to an application name and a
real contact email; the SEC receives that contact in request headers. Keep it
local and outside Git. SEC public data requires no API key. FMP is optional and
requires its existing `ENABLE_FMP`/`FMP_API_KEY` configuration. Groq is used only
for optional follow-up Q&A, not the deterministic assessment calculations.

```bash
uv run python frontend/app.py
```

Open the printed loopback address, normally http://localhost:8501. Expand
**Valuation assumptions** to edit the horizon, base annual earnings growth,
terminal P/E, and target annual issuer equity-value growth. Regenerate to apply
changes. Defaults (3 years, 10% earnings growth, 25x exit P/E, 10% target equity
growth) are illustrative inputs, not calibrated forecasts or recommendations.
The exact assumptions and normalized history are retained in ignored local
`legacy_evidence/assessment` artifacts alongside raw source snapshots.

## Financial collection and issuer identity

1. With a configured contact, SEC submissions verify that the requested ticker
   belongs to the resolved CIK. A provider CIK hint is checked against official
   submissions; otherwise the official ticker mapping is used. GOOG/GOOGL can
   resolve to the same consolidated issuer without substituting their quotes.
2. Company facts provide up to four annual periods and the latest cumulative
   interim period with its prior-year comparison. Every fact retains its unit,
   fiscal start/end, filing date, accession, concept, exact source URL, and local
   content-addressed evidence ID.
3. If SEC coverage is unavailable/incomplete, the collector checks up to four
   annual FMP periods and then Yahoo's annual financial time series. A whole
   dataset is selected; financial periods are not assembled from a mixture of
   providers. FMP entitlement errors remain recorded as such.

SEC normalization currently supports consolidated US-GAAP USD facts. Annual
durations must be 330–380 days. Instant balances must have no duration start.
Metrics within a period must use the same accession and matching duration, so a
three-month revenue cannot be combined with nine-month operating cash flow.
Conflicting duplicate SEC values are excluded. Later-filed comparative values
may reflect amendments/reclassifications; this is latest-available presentation,
not a point-in-time backtest dataset. Yahoo lacks filing dates and restatement
history; those gaps are explicitly retained.

## Interpretation and calculation policy

The business trajectory describes signs of changes in comparable revenue,
operating margin and free cash flow. At least two dimensions must be available:
positive and negative changes together produce **Mixed**, positive-only
**Improving**, negative-only **Weakening**, and all-zero **Stable**. Otherwise it
is **Insufficient evidence**. This is a transparent descriptive rule, not a
statistical quality score or an investment recommendation.

The newest comparable year-to-date windows take precedence over annual windows.
Year ends must be 330–400 days apart and known duration lengths within eight
days; unmatched periods are not given year-over-year growth rates. Growth from
nonpositive bases is described in amounts instead of misleading percentages.

- Operating margin = operating income / revenue.
- FCF = operating cash flow − absolute capital expenditure. This is a defined
  calculation, not a claim to reproduce every issuer's non-GAAP FCF definition.
- Cash conversion = operating cash flow / positive net income.
- Capex intensity = absolute capex / revenue.
- Stock-compensation burden = reported stock-based compensation / revenue.
- Diluted-share changes use comparable periods; SEC comparisons must use the
  same accession to avoid mixing split-adjusted presentations.

Supporting evidence, opposing evidence, and explanatory observations cite all
inputs. Net income above operating income is flagged for examination of
nonoperating/tax items without inventing their cause. Negative FCF and rising
capex intensity are surfaced even if earnings grow. Cash/noncurrent debt are
shown without incorrectly calling their difference total net cash.

## Valuation, scenarios and expectations hurdle

When source periods align, trailing twelve months are calculated as:

```text
TTM flow = last full fiscal-year flow + current YTD flow − prior matching YTD flow
```

Both YTD durations must match, prior YTD must start with the fiscal year, and
current YTD must start immediately after it. Only additive flows use this bridge;
share averages, EPS and balance-sheet instants are not added. All three source
observations are preserved in valuation citations. Otherwise the baseline is
explicitly annual-only; it is never mislabeled TTM.

Valuation compares provider-reported issuer market capitalization with the same
baseline's reported net income, revenue and calculated FCF. Nonpositive
earnings/FCF multiples are withheld; a negative FCF yield remains visible. Market
and reporting currencies must match. No scenarios are emitted for absent/stale
quotes (over seven days), future quotes, financial baselines over 550 days old,
or nonpositive baseline earnings. Market-cap observation time can remain unknown
even when the quote is dated; the report labels that limitation.

For starting reported earnings `E`, horizon `n`, assumed earnings growth `g`,
exit P/E `m`, and starting market cap `M`:

```text
Terminal issuer equity value = E × (1 + g)^n × m
Change versus snapshot cap   = terminal value / M − 1
Annualized equity change    = (terminal value / M)^(1/n) − 1
Required earnings growth    = [M × (1 + target growth)^n / (m × E)]^(1/n) − 1
```

Bear/base/bull illustrations vary growth by −10/0/+10 percentage points and
exit P/E by −5/0/+5 turns around the user's base assumptions. The sensitivity
grid varies these independently. These are neither probabilities nor share-price
targets. They exclude dividends, share-count changes, financing changes,
normalization of exceptional earnings and class-specific economic rights.
Peer-relative or historical cheapness is not asserted without comparable data.

The generic corporate assessment is withheld for identified financial,
real-estate and fund profiles; those require specialist analysis. Sector/asset
classification can itself be missing. Full segment analysis, verified management
guidance, peer/historical valuations and a verified future earnings calendar
remain integration gaps. Headlines are discovery only and do not establish
business causality. Recent SEC filing links and metric-specific monitoring
conditions guide further research without inventing event dates.

## Verification

```bash
uv run pytest tests/test_research_assessment.py tests/test_legacy_live_research.py tests/test_frontend.py tests/test_main.py --no-cov
make check
```

Fixtures cover accounting alignment, TTM lineage, valuation formula goldens,
negative/zero denominators, missing/stale/currency-mismatched observations,
issuer/share-class verification, fallback boundaries, safe rendering and input
validation. Automated tests use no network or keys. Manual live checks and visual
review are separate and never establish investment accuracy or forecast validity.

Provider contracts: [SEC APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces),
[SEC access policy](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data),
[FMP documentation](https://site.financialmodelingprep.com/developer/docs).

## Reading sources and scoped follow-ups (Flask compatibility UI)

New reports fetch up to three discovered article destinations and one original
SEC filing from verified issuer submissions. The reader extracts semantic body
paragraphs, not RSS titles. It retains the downloaded HTML as a local evidence
artifact and indexes body passages with stable IDs. Publisher JSON-LD or section
metadata labels reporting, analysis, opinion or sponsored content; absent labels
remain unclassified. An issuer filing is labelled separately. These labels do
not independently verify the contents.

`ARTICLE_ALLOWED_HOSTS` controls explicit reviewed HTTPS destinations. Each
redirect must pass the host, public-address and publisher robots checks; SEC
filing redirects cannot change the verified filing path. Collection is bounded
by response size, timeout, redirect and concurrency limits. The reader does not
execute JavaScript, log in, bypass paywalls or treat consent pages as articles.
Disallowed, blocked, gated, unrelated, quarantined and insufficient bodies are
shown as **Not read** and never indexed as article evidence. A robots permission
is an access control check, not a grant of content reuse rights. Review each
publisher's terms before adding hosts. Only short excerpts are displayed.

Each report receives an immutable UUID snapshot in the local
`report_evidence.sqlite3`. Follow-ups require both that ID and its ticker.
Filtering happens in SQL before passage ranking; there is no fallback to old
mixed indexes, another company or a more recent report of the same company.
Older pages must be regenerated to obtain source bodies and a report ID.
Background technical charts do not modify the finalized evidence snapshot.

The optional model selects up to three exact excerpts. The server verifies each
ID, quote substring and cumulative source quote budget, then constructs citation
links from saved metadata. Only used sources are displayed, with source labels,
publication dates when supplied and passage IDs. Invented prose, URLs, quotes or
extra response fields fail verification. Article excerpts are capped at 24 words
per URL per answer; filings and financial data at 120. This extractive answer
format demonstrates provenance; it does not prove a publisher claim is true or
that an excerpt answers every aspect of a question. Unsupported questions are
explicitly marked. Published author views do not establish public sentiment.

Test the offline reader, cross-report isolation and citation failures with:

```bash
uv run pytest tests/test_article_reading.py tests/test_document_security.py tests/test_legacy_live_research.py tests/test_frontend.py --no-cov
```
