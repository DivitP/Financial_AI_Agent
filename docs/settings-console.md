# Provider, model and data-health console

Open **Settings**, or GET `/api/v1/settings/health`. Refresh reads local state only;
there are no probes, model downloads, provider requests, or configuration writes.
The endpoint uses an explicit allowlist, never a dump of Settings or environment.
Keys, URLs, local paths, arbitrary model names, cache keys/bodies, provider error
messages and raw artifacts are excluded. Responses use `Cache-Control: no-store`.
Only a credential-present boolean is exposed; it does not establish validity.

FMP, Groq, Ollama and Kronos use their actual enabled flags. SEC, yfinance,
OpenBB and GDELT have no global toggle and are explicitly workflow-selected.
Account plan, free-tier eligibility and remaining quotas are unverified.
Local execution is distinguished from hosted accounts, not labeled costless.
Rate-limit warnings count recorded HTTP 429s in the previous 24 hours; last
success is the latest valid completion timestamp for a recorded HTTP 2xx.
Request history may be incomplete; no warnings is not evidence of quota remaining.

Models show dependency installation and configuration separately from availability.
The console never imports heavy models or claims an unprobed endpoint is healthy.
Arbitrary model identifiers are hidden because configuration strings can contain
credentials. Optional dependency checks do not prove weights are downloaded.

Cache metrics are thread-safe counts/TTL from an explicitly attached
`app.state.provider_http_client` (`SharedHttpClient`), not a global registry.
Without one, the UI says unobserved. Counts cover that process/client only.
Database/vector/model caches are not included. Configured defaults are separate
from actual client overrides; the rate-limit setting is not a provider quota.

Correlation headers now accept UUIDs only; other values are replaced before
being echoed or logged. Pydantic startup errors hide input values. The console
does not log configuration or provider payloads. This is not a repository-wide
audit of legacy or third-party logging. Existing local access boundaries apply;
do not expose the unauthenticated app publicly.

Verification: `make check` includes sentinel-secret tests covering API bodies,
headers, captured logs, config/model strings, persisted errors, and cache data;
plus offline request-history/cache aggregation and UI refresh tests.
