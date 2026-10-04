# Reproducible screenshots and review

Screenshots are generated from the actual React production build using synthetic
fixtures, not live financial data or design mockups. They demonstrate layout,
not completeness of live collection, forecast accuracy or financial correctness.

From the repository root after dependency installation:

```bash
npm --prefix frontend/web exec -- playwright install chromium
make release-eval
```

Open the newly printed `data/runtime/release/<timestamp-id>/quality.md`. Browser
attachments are inside its `browser-artifacts/` tree. The
[corpus browser test](../frontend/web/e2e/release-corpus.spec.ts) captures AAPL,
JPM, XOM, TSLA, SPY and QQQ at 1280px and 390px widths (900px viewport height,
full-page capture). Names follow `<ticker>-<width>.png` inside each test directory.
Failure screenshots/traces may also exist; do not confuse these with approved captures.

| Capture to review | Required caption if shared | What to check |
| --- | --- | --- |
| AAPL-1280.png | Stock workspace — synthetic fixture, not live data | Navigation, progress, company identity, missing-lane warnings |
| AAPL-390.png | Mobile stock workspace — synthetic fixture | No horizontal overflow, readable controls and source labels |
| SPY-1280.png / SPY-390.png | ETF workspace — synthetic fixture, incomplete holdings coverage | Fund identity and absence of corporate earnings sections |

The corpus intentionally returns no saved report and only minimal observations.
These captures must not be captioned as a complete report, live chart, working
forecast or Q&A answer. Other browser flows exercise those components separately;
new marketing screenshots require a representative, reviewed fixture and caption.

Record revision, capture date, viewport, fixture name, reviewer and outcome in
the release issue. Inspect for clipping, contrast, readable warnings and evidence
usability; follow the manual flows in [accessibility QA](accessibility-qa.md).
Automated screenshots are not visual-diff baselines or screen-reader sign-off.

Keep generated images in ignored runtime directories, as required by the release
artifact policy. Review for secrets and source rights before attaching selected
captures to a release. No historical or live-data screenshot is bundled with this
README rewrite; screenshots must be regenerated for the candidate build.
