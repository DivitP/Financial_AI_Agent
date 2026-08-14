# Free-provider, data-rights, and model policy

Status: approved for development; release distribution requires the review
checklist below. This is an engineering policy, not legal advice. Provider terms
and quotas change, so adapters must link the retrieval date and must be reviewed
before a production launch.

## Non-negotiable rules

- No product feature may require a paid provider to produce a useful research
  result. A provider failure returns coverage gaps and citations, not invented
  facts.
- Store and redistribute only data that the source terms permit. Cache duration,
  display, export, and vector indexing follow the strictest applicable terms.
- Show human-readable source attribution for facts and links for primary
  sources. Preserve source/provider metadata in every evidence record.
- API keys belong in local/managed secrets, never reports, logs, vectors,
  fixtures, or Git.

## Approved providers and fallbacks

| Provider | Intended free use | Quota / operational rule | Attribution and redistribution | Fallback |
| --- | --- | --- | --- | --- |
| [SEC EDGAR](https://www.sec.gov/about/developer-resources) | Primary US filings, XBRL facts, issuer metadata | Identify the application with a descriptive `User-Agent`; maximum 10 requests/sec across all machines | Cite filing accession/URL and filing date. Keep only permitted filing extracts and provenance. | Show filing unavailable; do not substitute an analyst summary as a filing. |
| [yfinance](https://github.com/ranaroussi/yfinance) | Local research bars, quotes, and basic company data | Treat as best-effort and cache conservatively; it is not an official Yahoo API | yfinance code is Apache-2.0, but Yahoo data use is stated as personal/research use; do not redistribute raw Yahoo-derived data or promise commercial rights. | SEC for fundamentals; FMP or OpenBB configured provider; coverage gap for unsupported data. |
| [FMP](https://site.financialmodelingprep.com/pricing-plans) | Optional free fundamentals/quotes where the account permits | Free Basic currently advertises 250 calls/day and 500 MB/30 days; adapter must enforce a lower configurable budget | FMP says display or redistribution requires a Data Display and Licensing Agreement. Do not expose raw FMP data in exports or vector stores by default. | yfinance/SEC/OpenBB provider or an explicit unavailable result. |
| [GDELT](https://www.gdeltproject.org/) | News/event discovery and sentiment candidate generation | Poll incrementally, deduplicate, and obey endpoint availability; do not use it as an article-content license | Cite the originating publisher URL. Treat GDELT metadata as discovery data; do not redistribute source articles or assume a CAMEO/data license applies to all feeds. | SEC issuer releases, permitted web/RSS sources, or no sentiment conclusion. |
| [OpenBB](https://docs.openbb.co/odp/python/faqs/license) | Optional normalized access to open/public provider extensions | Install only needed extensions; configure every underlying provider separately | OpenBB ODP is AGPL-3.0. Its code license does not grant rights to third-party data. Preserve extension/provider attribution and terms. | Direct SEC/yfinance/GDELT adapters. |
| [Groq](https://console.groq.com/docs/rate-limits) | Optional hosted inference for extraction and report synthesis | Read account-specific limits at runtime. Current free limits are model-specific (e.g. the docs list 30 RPM and 1,000 RPD for `llama-3.3-70b-versatile`); retry 429 responses with backoff. | Do not send secrets or unnecessarily retainable raw content. Model output is not a source and must cite evidence. | Local LLM or deterministic templates/extraction; research collection still runs. |
| Local LLM | Private, offline extraction/synthesis | Operator supplies hardware and model weights; set bounded context and timeouts | Record model name/version/license and any model-card restrictions. Do not claim source attribution for generated text. | Deterministic report templates and structured evidence display. |
| [Kronos](https://huggingface.co/NeoQuasar/Kronos-base) | Optional local OHLCV representation, volatility, and forecast research | Download on demand; never block a basic report on model availability. Run only after data-quality gates. | Kronos model card states MIT. Preserve model/version notice; rights to input market data remain governed by its source. Show validation metadata and uncertainty. | Classical technical indicators and “forecast unavailable”; never fabricate a model prediction. |

## License decision and AGPL review

This repository is **AGPL-3.0-or-later**. The choice is compatible with direct
use of the AGPL-licensed OpenBB ODP and requires corresponding-source access
when a modified version of this application is provided over a network.

Before finalizing a release that includes OpenBB, a maintainer must record:

1. exact OpenBB package/extensions and their licenses;
2. whether the deployment modifies, bundles, or only communicates with OpenBB;
3. the source-offer URL and complete AGPL notices for network users;
4. every underlying data provider and any separate display/redistribution deal;
5. legal review of the intended deployment and distribution model.

FMP is intentionally optional because its terms restrict third-party access and
redistribution. Groq is optional because the free tier is quota-limited and may
change. The required baseline is SEC filings plus locally permitted market/news
sources; gaps are surfaced to the user instead of filled by a paid fallback.

## Release checklist

- Confirm provider quotas and terms on the release date.
- Run all adapters with no paid keys and verify research completes with explicit
  coverage gaps where data is unavailable.
- Confirm report/export and vector-storage policies for every source.
- Verify citation links, timestamps, and evidence locators.
- Complete the AGPL review above before enabling OpenBB in a network deployment.
