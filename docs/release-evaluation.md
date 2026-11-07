# Release candidate evaluation

Use the [release checklist](release-checklist.md) for human sign-off and
[screenshot guide](screenshots.md) for capture labels and visual review.
Passing this command is an engineering gate, not approval of live research.

After `uv sync --locked --all-groups`, `npm --prefix frontend/web ci`, and
`cd frontend/web && npx playwright install chromium`, run from the repository root:

```bash
make release-eval
```

Each invocation creates a unique ignored `data/runtime/release/<timestamp-id>/`
directory. Open `quality.md` for a summary or `quality.json` for structured results.
The report records revision, dirty-worktree flag, platform, corpus hash, stage
durations, test counts, exclusions and links to logs. Full pytest JUnit and
Playwright JSON include individual test outcomes. Logs and screenshots are local
artifacts: review for sensitive information before sharing; never commit them.

## Mandatory automated thresholds

- [Replacement coverage](coverage.md): at least 87% lines and 69% branches;
  legacy and shared-settings coverage reported separately, without blending totals.

- Ruff, formatting, mypy, frontend types, unit tests and production build: zero failures.
- Full Python suite: zero failures and all 12 corpus evaluations present. Only
  the six real-service deployment tests may skip when services are unconfigured.
  Configure `TEST_POSTGRES_URL` and `TEST_REDIS_URL` to include that profile;
  a local-only pass is not approval of the scaled deployment.
- Financial goldens: exact expected displays and unavailable-denominator outcomes;
  ETF concentration uses exact Decimal arithmetic. All corpus cases must pass.
- Citation checks: missing links rejected, exact links retained. Full report,
  verifier, Q&A and RAG tests also run, including existing retrieval thresholds,
  unsupported-claim negative controls and ticker/run isolation tests.
- Prompt checks: fixture responses match the versioned schema and token budget;
  malformed responses are rejected after bounded retries. This tests contracts,
  not the quality of a live Groq/local model.
- Browser: at least 15 tests, zero failures, flakes or skips. Runs use a freshly
  built production bundle on reserved port 4179, refusing an existing server.
  Existing research, security, accessibility, forecast and performance flows run
  alongside six corpus flows. Performance budgets remain those in performance.md.
- Missing commands/results, malformed reports and timeouts fail closed. Later
  stages still run; browser evaluation is blocked if the frontend build fails.
  The command exits nonzero whenever a mandatory stage fails.

## Corpus and visual review

`tests/fixtures/system/corpus.json` contains versioned, hand-calculated synthetic
USD cases using AAPL, JPM, XOM, TSLA, SPY and QQQ labels. Values are deliberately
not real issuer data. Coverage includes missing fields, losses, zero denominators,
percentage/unit conversion, and diversified/concentrated holdings. Expand the
corpus and reviewed goldens when adding new asset types or calculation contracts.

Browser fixtures exercise each symbol at desktop/mobile widths, check horizontal
overflow and exact evidence links, and attach screenshots to `browser-artifacts`.
Failure traces/screenshots are also retained. Review these for clipping, readable
labels, visual hierarchy and evidence usability before signing off. Screenshot
capture is not pixel-diff approval: reports always mark manual review required.
There are no unreviewed auto-generated image baselines.

This report is an offline engineering gate, not a guarantee of financial accuracy
with live data. Live provider quality, live LLM answer quality, real model-weight
Kronos benchmarks, and human screen-reader/visual sign-off remain separate.
The existing normal CI suite automatically includes corpus and gate-negative
tests; use the one-command evaluation locally for release artifacts.
