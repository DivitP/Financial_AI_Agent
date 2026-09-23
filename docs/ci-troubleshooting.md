# CI validation

Run `make check` before pushing. This runs Ruff lint and formatting, mypy,
offline Python tests, TypeScript checks, frontend unit tests and the web build.
CI additionally installs locked dependencies and runs the RAG evaluation gate.
Do not treat a local pass as a verified GitHub runner pass.

The comparison change required explicit types for its nested metric-row
dictionary; otherwise mypy stopped the quality job before tests ran.

Run 44's separate secret-scan failure was an EncoderFallbackException in
GitHub.Runner.Common.HostTraceListener during checkout startup. The job metadata
shows Gitleaks had not started. It was not a secret finding, and changing the
Python code cannot fix that runner exception. Retry on a fresh hosted runner;
if it recurs, retain the complete annotation and report it to GitHub.

The workflow now uses Node-24-compatible action versions, including Gitleaks v3.
The frontend Node version is separate from action runtimes. Secret scanning
retains full-history checkout and fail-on-findings behavior. It uses GitHub's
automatically supplied token; no personal token is needed. PR comments are
disabled to keep the workflow's read-only permission boundary.

Sources: [Gitleaks migration instructions](https://github.com/gitleaks/gitleaks-action),
[setup-uv v7 runtime](https://github.com/astral-sh/setup-uv/blob/v7/action.yml).
