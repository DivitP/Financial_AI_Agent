# Browser security

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
