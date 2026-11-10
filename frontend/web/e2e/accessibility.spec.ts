import { expect, test, Page } from "@playwright/test";
import axe from "axe-core";

const run = { id: "a11y", ticker: "AAPL", status: "completed", correlation_id: "fixture" };
const citation = {
  url: "https://example.test/filing#risks",
  evidence_id: "e1",
  section: "Risks",
  excerpt: "Revenue is uncertain.",
  published_at: "2026-01-01",
};
const forecast = {
  status: "completed",
  quality: "experimental",
  forecast: {
    model_version: "offline",
    as_of: "2026-09-09",
    currency: "USD",
    timezone: "America/New_York",
    provider: "fixture",
    device: "cpu",
    adjustment_policy: "split_adjusted_as_of",
    historical_candles: [{ session: "2026-09-09", open: 100, high: 105, low: 98, close: 102 }],
    candles: [{ session: "2026-09-10", close: 103 }],
    summary: {
      sample_count: 8,
      bands: [
        {
          session: "2026-09-10",
          close_percentiles: { "5": 90, "25": 98, "50": 103, "75": 107, "95": 110 },
        },
      ],
    },
    warnings: [],
  },
  validation: {
    status: "experimental",
    created_at: "2026-09-10",
    reasons: [],
    limitations: [],
    models: {
      kronos: {
        metrics: {
          mae: 2,
          rmse: 3,
          mase: 1,
          terminal_direction_accuracy: 0.6,
          interval_coverage: 0.9,
        },
        turnover: 2,
        drawdown: 0.12,
        windows: [],
      },
    },
  },
};

async function fixtures(page: Page) {
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/events"))
      return route.fulfill({
        contentType: "text/event-stream",
        body: "event: completed\ndata: {}\n\n",
      });
    let json: unknown = [];
    if (path.endsWith("/a11y") || route.request().method() === "POST") json = run;
    if (path.endsWith("/snapshot"))
      json = [
        {
          lane: "instrument",
          status: "completed",
          payload: { name: "Apple Inc.", url: citation.url },
          error_message: null,
        },
      ];
    if (path.endsWith("/qa"))
      json = [
        {
          id: 1,
          question: "What are the risks?",
          answer: {
            message: "Source excerpts",
            claims: [{ text: "Revenue is uncertain.", citation }],
          },
        },
      ];
    if (path.endsWith("/reports/latest"))
      return route.fulfill({ status: 404, json: { error: { message: "Report unavailable" } } });
    if (path.endsWith("/forecast")) json = forecast;
    if (path.endsWith("/calendar"))
      json = { notice: "Fixture calendar", limitations: [], events: [] };
    if (path.endsWith("/settings/health"))
      json = {
        notice: "Offline",
        providers: [],
        models: [],
        cache: { state: "unobserved" },
        feature_flags: {},
        configured_defaults: {},
      };
    if (path.endsWith("/delta"))
      json = {
        current_run_id: "a11y",
        previous_run_id: null,
        basis: {},
        limitations: [],
        unchanged: [],
        changes: [],
      };
    if (path.endsWith("/history"))
      json = {
        run: { ticker: "AAPL", name: null },
        notice: "Saved only",
        report: null,
        versions: [],
        snapshots: [],
      };
    if (path.endsWith("/comparisons"))
      json = {
        notice: "Saved only",
        columns: ["AAPL", "MSFT"].map((ticker) => ({
          ticker,
          run_id: null,
          limitations: [],
          sections: {},
        })),
        metrics: [
          {
            metric: "Revenue",
            comparable: false,
            reasons: ["Different fiscal periods"],
            cells: {
              AAPL: { normalized_value: 100, normalized_unit: "USD", evidence: [] },
              MSFT: { normalized_value: 90, normalized_unit: "USD", evidence: [] },
            },
          },
        ],
      };
    return route.fulfill({ json });
  });
}

async function audit(page: Page) {
  await page.evaluate(axe.source);
  const violations = await page.evaluate(
    async () =>
      (
        await (window as unknown as { axe: typeof axe }).axe.run(document, {
          runOnly: {
            type: "tag",
            values: ["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa", "best-practice"],
          },
        })
      ).violations,
  );
  expect(
    violations.map((v) => ({
      id: v.id,
      nodes: v.nodes.map((n) => ({ target: n.target, summary: n.failureSummary })),
    })),
  ).toEqual([]);
}

test.beforeEach(async ({ page }) => fixtures(page));

test("keyboard skip link, route focus, validation and native evidence modal", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to main content" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("main")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Ticker or ETF symbol")).toBeFocused();
  await page.keyboard.type("bad ticker!");
  await expect(page.getByLabel("Ticker or ETF symbol")).toHaveAttribute("aria-invalid", "true");
  await audit(page);
  await page.getByLabel("Ticker or ETF symbol").fill("AAPL");
  await page.getByRole("button", { name: "Start research" }).press("Enter");
  await expect(page.getByRole("heading", { name: "AAPL", exact: true })).toBeVisible();
  await expect(page.getByRole("main")).toBeFocused();
  const trigger = page.getByRole("button", { name: "instrument completed" });
  await trigger.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "instrument evidence" });
  await expect(dialog.getByRole("button", { name: "Close" })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(dialog.getByRole("link")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(dialog.getByRole("button", { name: "Close" })).toBeFocused();
  await audit(page);
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await audit(page);
  await page.getByRole("link", { name: "Calendar", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByRole("main")).toBeFocused();
});

test("keyboard citations stay open to focus, dismiss, and expose exact links", async ({ page }) => {
  await page.goto("/runs/a11y");
  const source = page.getByRole("button", { name: "Source: Risks" });
  await source.focus();
  await page.keyboard.press("Enter");
  await expect(source).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Open exact source" })).toBeFocused();
  await audit(page);
  await page.keyboard.press("Escape");
  await expect(source).toBeFocused();
  await expect(source).toHaveAttribute("aria-expanded", "false");
  await page.getByRole("button", { name: "What are the revenue risks?" }).press("Enter");
  await expect(page.getByLabel("Research question")).toBeFocused();
});

test("all routes reflow at 320px with reduced motion and pass browser axe including contrast", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const path of [
    "/",
    "/history",
    "/history/a11y",
    "/watchlists",
    "/calendar",
    "/compare",
    "/portfolio",
    "/settings",
    "/runs/a11y",
    "/runs/a11y/changes",
    "/runs/a11y/forecast",
  ]) {
    await page.goto(path);
    await expect(page.locator("main h1")).toBeVisible();
    await expect(page.locator("main .loading")).toHaveCount(0);
    await audit(page);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
      path,
    ).toBe(true);
    expect(await page.locator("main").evaluate((el) => getComputedStyle(el).animationName)).toBe(
      "none",
    );
    await page.screenshot({
      path: test.info().outputPath(path.replaceAll("/", "_") + "-320.png"),
      fullPage: true,
    });
  }
});

test("chart description, keyboard value table and comparison table remain usable", async ({
  page,
}) => {
  await page.goto("/runs/a11y/forecast");
  await expect(page.getByRole("img")).toHaveAccessibleDescription(/Final sampled median: 103/);
  const values = page.getByText("Accessible chart values", { exact: true });
  await values.focus();
  await page.keyboard.press("Enter");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("region", { name: "Chart data", exact: true })).toBeFocused();
  await expect(page.getByRole("table", { name: /Historical OHLC/ })).toContainText(
    "O 100 H 105 L 98 C 102",
  );
  await page.getByText("Read baseline metrics as a list", { exact: true }).press("Enter");
  await expect(
    page.getByText("Read baseline metrics as a list", { exact: true }).locator(".."),
  ).toContainText("90%");
  await audit(page);
  await page.goto("/compare");
  await page.getByLabel(/Tickers/).fill("AAPL, MSFT");
  await page.getByRole("button", { name: "Compare", exact: true }).press("Enter");
  await expect(page.getByRole("table", { name: "Revenue by ticker" })).toBeVisible();
  await page.setViewportSize({ width: 320, height: 800 });
  await page.getByRole("region", { name: "Revenue comparison table" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect
    .poll(() =>
      page
        .getByRole("region", { name: "Revenue comparison table" })
        .evaluate((el) => el.scrollLeft),
    )
    .toBeGreaterThan(0);
  await page.getByText("Read values by ticker", { exact: true }).press("Enter");
  await expect(
    page.getByText("Read values by ticker", { exact: true }).locator(".."),
  ).toContainText("100 USD");
  await audit(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
