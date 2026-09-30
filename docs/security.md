# Browser security

## Untrusted articles and filings

Production document collection uses the default `SharedHttpClient()` with
`SafeTransport`. `DOCUMENT_ALLOWED_HOSTS` is an exact lowercase hostname allowlist
(SEC and GDELT by default); approve each RSS/IR/news host explicitly in local
configuration. Search results and redirects cannot add hosts. HTTPS/443 only;
credentials, fragments, control characters and non-public DNS answers are rejected.
Every DNS answer must be public. Connections pin the checked IP while TLS verifies
the original hostname, preventing a second DNS lookup/rebinding. Redirects are
revalidated and capped at two; authentication/cookies and environment proxies are
never forwarded. Requests are GET-only, with socket timeouts, a read deadline and
streaming byte limits. Compressed/binary responses (including PDFs) are rejected;
only approved text/HTML/XML/JSON MIME types are downloaded. DNS lookup timing still
depends on the operating-system resolver. Use outbound firewall restrictions as
an additional deployment boundary.

Injected HTTP transports are trusted test/adapter code, not a configuration option
or model-controlled input. They must never be used to install an unrestricted
production downloader. Local Ollama configuration is a separate administrator-owned
endpoint, not a document URL. Fixed-provider SDKs remain separate from document
fetching; this policy does not claim to sandbox arbitrary third-party code.

Before indexing and again before Q&A, document views normalize Unicode/entities,
remove executable/hidden HTML, and quarantine known embedded instruction patterns
(including role spoofing and tool/exfiltration requests). Quarantine excludes the
document from model context; Q&A surfaces a coverage warning. Raw relational
evidence and its content hash remain intact. Prompt variables and legacy article
tools use serialized untrusted-data envelopes, never system instructions.
Existing indexes are rechecked, so reindexing is not required for protection.
New Q&A models have no tools and answers still require exact cited excerpts.

Heuristic filtering cannot prove absence of prompt injection; opaque encodings or
novel wording may evade it, and benign instructional text can be quarantined.
The trust separation, bounded read-only tools, URL policy and output verification
remain necessary. No fetched document is executed, and no links found in it are
automatically followed. BeautifulSoup is an explicit locked dependency for
non-executing HTML parsing.

Run the offline adversarial suite:
`uv run pytest tests/test_document_security.py --no-cov`.
Policy references: [OWASP SSRF prevention](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)
and [OWASP prompt-injection prevention](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html).

Both API and legacy Flask responses carry CSP, nosniff, anti-framing, no-referrer,
and restricted permissions headers. HTTPS responses also carry HSTS. Debug and the
legacy development reloader are disabled. FastAPI's explicit development
`--reload` option remains available.

React renders research as text, not HTML. The legacy Markdown renderer uses
Bleach's allowlist after Markdown conversion; no scripts, images, handlers,
styles or arbitrary attributes survive. External links require absolute HTTP(S)
URLs without credentials, whitespace, controls or backslashes. Legacy dynamic
content uses DOM text nodes, never HTML strings. Charts accept PNG base64 only.
Bleach is a locked runtime dependency specifically for this sanitization boundary.
Node's development type declarations support the Vite nonce-generation configuration.

Browser mutations require `X-Requested-With: FinancialAI`, an allowed Origin
(when supplied), and JSON (when a body content type is supplied). Cross-site
Fetch Metadata is rejected. Legacy form submissions instead require a signed
session CSRF token. Non-browser JSON clients without Origin/Fetch Metadata remain
supported. No permissive CORS headers are emitted: deploy the frontend and API on
the same origin through a reverse proxy. Cross-origin direct browser calls are
not supported, even for listed origins.

`ALLOWED_BROWSER_ORIGINS` and `ALLOWED_HOSTS` accept JSON arrays of explicit
deployment origins and hostnames; wildcards are forbidden. Local development
defaults include localhost and 127.0.0.1. Add the actual HTTPS deployment origin
and hostname before deploying. Never trust arbitrary forwarded headers.

Vite development and preview serve security headers; development scripts/styles
use a random startup nonce. Production HTML embeds a restrictive CSP meta tag.
The production web server must ALSO serve the headers in
`financial_ai.security.HEADERS` (especially frame-ancestors, which meta cannot
enforce), HTTPS/HSTS, and proxy only the intended API routes. No inline production
scripts or styles are allowed. Swagger alone has a nonce and narrowly scoped
jsDelivr script/style exception. CSP does not replace escaping and sanitization.

This is a local, unauthenticated research application. These browser protections
are NOT authentication; do not expose it to untrusted networks without an
authenticated gateway. No brokerage or trade execution is present.

## Remaining dependency work

The implementation-time npm audit reported seven existing advisories (five
moderate, one high, one critical) across React Router, Vite/esbuild and Vitest.
The critical advisory concerns the Vitest UI server; do not expose development
or test servers to untrusted networks. Rendering hardening does not patch these
dependencies. Major Vite/Vitest upgrades and a router upgrade require a separate
compatibility pass; no forced audit upgrade was applied. Re-run
`npm --prefix frontend/web audit` before deployment.

Verify with `make check` and `npm --prefix frontend/web run test:e2e`.
Security fixtures cover Markdown, unsafe links, CSRF, host checks, headers and
actual browser execution attempts. No live providers or credentials are needed.

References: [OWASP CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html),
[Bleach HTML sanitization](https://bleach.readthedocs.io/en/latest/clean.html).
