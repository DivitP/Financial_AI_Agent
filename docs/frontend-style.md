# Frontend formatting and workspace style

Prettier 3.6.2 is a pinned development-only dependency. It formats TypeScript,
TSX, CSS, browser tests and frontend config files; it adds no browser runtime code.
Its lockfile is committed alongside the configuration. Generated builds, packages
and reports are excluded. From the root:

```bash
npm --prefix frontend/web run format
npm --prefix frontend/web run format:check
make frontend-lint frontend-test frontend-build
```

Frontend lint (and therefore `make check` and CI) checks formatting before types.
The initial formatting-only pass preserved existing tests (39 passing) and the
production build before design changes were applied. No routes, requests, data
calculations or copy were rewritten for formatting.

`frontend/web/src/tokens.css` owns spacing, type sizes, surfaces, borders, status
colors and chart colors. Use those variables instead of one-off colors. The
workspace uses a light neutral background, white surfaces, small corner radii,
system fonts and blue controls. Avoid decorative gradients, remote fonts and
large marketing headings inside the workspace. Only `.landing h1` uses display
type; workspace page titles stay compact. Status labels retain text, not color
alone. Focus outlines, 44px controls and reduced-motion behavior remain intact.

Financial data uses tabular numerals; `.numeric` marks right-aligned value cells.
Do not right-align prose, evidence links or row labels. Historical and forecast
charts share surface and palette tokens; forecast bands remain differentiated
by tone and strokes. Numeric formatting, values and forecasts are unchanged.

`workspace-style.spec.ts` captures synthetic landing/workspace fixtures at 1280px
and 390px, checks overflow, heading hierarchy and numeric alignment. Existing
accessibility and browser suites remain required. Screenshots are ignored local
artifacts, not real market data or committed golden baselines. Review desktop and
mobile captures manually after changes; passing a screenshot test is not visual
sign-off or a claim of full screen-reader validation.

Visual review (2026-11-10): inspected synthetic landing and workspace captures
at 1280px and 390px. Checked navigation wrapping, form spacing, compact workspace
headings, visible status labels and the historical chart. Mobile evidence buttons
were changed to one column to prevent split labels; the chat action has its own
row. Existing browser axe checks cover contrast, keyboard flows and 320px reflow.
This is fixture review, not live-provider or real-model validation.
