# Accessibility and responsive QA

Scope: the React research client, including research, history, watchlists,
calendar, comparisons, portfolio context, settings, changes, chat, and forecasts.
This is a tested accessibility baseline, **not a WCAG conformance certification**
or a claim that every browser/assistive-technology combination was tested.
The legacy Flask interface is not covered by this React QA pass.

## Implemented behavior

- Consistent primary navigation, active-page links, and a first-tab skip link.
  Each page has one focusable main landmark. Client-side navigation focuses
  that landmark and updates the document title; polling does not steal focus.
- Native modal evidence dialog: initial focus, forward/reverse focus wrapping,
  Escape/Close dismissal, inert background, scroll containment, and return to
  the opening control.
- Labeled ticker errors and polite progress/answer announcements. Suggested
  chat questions and watchlist editing move focus to the relevant input.
  Citation details support keyboard toggling, exact-link focus, and Escape.
- Visible focus rings for links, fields, buttons, summaries and scroll regions;
  explicit placeholder colors; navigation/control touch targets; reduced-motion
  overrides. Text status labels supplement colors.
- Wrapping mobile navigation and cards. Charts/tables intentionally retain
  readable minimum widths inside labeled, keyboard-scrollable regions; the
  page itself does not require horizontal scrolling at 320 CSS pixels.
- Forecast narrative descriptions and exact-value tables, baseline metrics
  as a stacked list, and comparisons as per-ticker text with source links.
  Chart bands have contrasting outlines as well as different fills. Forecasts
  remain explicitly uncertain—not guaranteed targets or calibrated intervals.

Design references: [WAI modal dialog pattern](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/)
and [WCAG reflow guidance](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html).
Charts/data tables may need two-dimensional layout; their surrounding content
and text alternatives still reflow.

## Repeatable automated checks

```bash
make check
cd frontend/web
npm ci
npx playwright install chromium
npm run test:a11y
npm run test:e2e
```

`make frontend-a11y` is the equivalent root-level accessibility command. CI
installs Chromium and runs it after the normal frontend checks. No new npm
dependencies, financial credentials, providers or model calls are required.
Browser tests intercept `/api/**` with offline fixtures. Test output and
screenshots live in ignored `frontend/web/test-results/`, not source control.

The accessibility suite runs axe with WCAG A/AA and best-practice checks,
**including color contrast in a real browser**. JSDOM-only tests cannot measure
contrast. Browser fixtures cover all 11 routes at 320px with reduced motion,
desktop keyboard navigation, ticker validation, modal focus/return, citation
disclosures, chart descriptions/value tables, and horizontally scrollable
comparison tables. Automated checks cannot assess actual spoken output,
all reading-order nuances, or every possible provider payload.

## QA record — 2026-10-01

Completed interactive manual flow (native Chrome, local frontend):

1. Open a new research page; press Tab. The skip link receives focus.
2. Press Enter, then Tab. Focus reaches the labeled ticker input rather than
   stepping through navigation.
3. Type `bad ticker!`. The visible validation message and input appear in the
   native accessibility tree, and Start research remains disabled.

Completed visual review: 320px screenshots of the form and forecast page.
The review identified over-compressed table headings; these were corrected
with readable minimum widths, local scrolling and stacked alternatives.
Charts retain their text summary and exact-value alternative at narrow widths.

Completed browser-driven checks (automated, **not described as manual**):
forward/reverse modal tab containment and Escape focus restoration; citation
keyboard navigation; all-route reflow; reduced-motion CSS; contrast scans;
chart/table keyboard access and non-chart alternatives. Fixtures intentionally
avoid live financial data and do not verify production-provider content.

### Assistive-technology sign-off still required

The following require a human tester with VoiceOver/Safari and NVDA/Firefox
or Chrome. They were **not completed** in this environment; native accessibility
tree inspection and axe are not substitutes for listening to a screen reader.

- Navigate by landmarks/headings; confirm route title/main changes announce
  once and polling does not interrupt reading.
- Read ticker help/errors, pending/failed/cancelled run statuses, and streamed
  answer completion; confirm announcements are neither missing nor repetitive.
- Open evidence, navigate its structured content, close with Escape, and
  confirm spoken focus returns to the trigger.
- Open a citation using keyboard/touch exploration, read its excerpt, and
  reach the exact source. Confirm dismissal leaves a predictable focus position.
- Read chart summaries, table headers/row relationships and stacked metric
  alternatives without depending on color or visual chart interpretation.
- Check 200% text enlargement, real browser 400% zoom, OS high contrast,
  and a touch device in both orientations. The 320px browser test exercises
  reflow but is not an assertion that these separate manual checks passed.

Record tester, browser/AT version, date, route, result and any remaining issue
before claiming full manual accessibility sign-off.
