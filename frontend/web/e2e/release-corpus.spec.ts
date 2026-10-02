import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

const corpus: { cases: { ticker: string; asset_type: string }[] } = JSON.parse(
  readFileSync(new URL("../../../tests/fixtures/system/corpus.json", import.meta.url), "utf8")
);

for (const fixture of corpus.cases) {
  test(`release corpus ${fixture.ticker}: desktop/mobile evidence review`, async ({ page }) => {
    const exact = `https://example.test/${fixture.ticker}/filing#risk`;
    await page.route("**/api/**", route => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith("/events")) return route.fulfill({ contentType: "text/event-stream", body: "event: completed\ndata: {}\n\n" });
      if (path.endsWith("/reports/latest")) return route.fulfill({ status: 404, json: { error: { message: "Fixture report unavailable" } } });
      if (path.endsWith("/qa")) return route.fulfill({ json: [] });
      if (path.endsWith("/snapshot")) return route.fulfill({ json: [
        { lane: "instrument", status: "completed", payload: { name: `${fixture.ticker} synthetic fixture`, asset_type: fixture.asset_type, url: exact } },
        { lane: "quote", status: "completed", payload: { price: 100, currency: "USD", retrieved_at: "2026-09-30T20:00:00Z", provider: "fixture" } },
        ...["ohlcv", "filings", "statements"].map(lane => ({ lane, status: "completed", payload: { provider: "fixture", limitations: ["Display fixture has no observations in this lane"] } })),
      ] });
      return route.fulfill({ json: { id: "corpus", ticker: fixture.ticker, asset_type: fixture.asset_type, status: "completed" } });
    });
    await page.goto("/");
    await page.getByLabel(/ticker or etf/i).fill(fixture.ticker);
    await page.getByRole("button", { name: /start research/i }).click();
    await expect(page.getByRole("heading", { name: fixture.ticker, exact: true })).toBeVisible();
    await expect(page.getByText(`${fixture.ticker} synthetic fixture`, { exact: true })).toBeVisible();
    if (fixture.asset_type === "etf") {
      await expect(page.getByRole("heading", { name: "Fund identity" })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Earnings and expectations" })).toHaveCount(0);
    }
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 900 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      const screenshot = test.info().outputPath(`${fixture.ticker}-${width}.png`);
      await page.screenshot({ path: screenshot, fullPage: true, animations: "disabled" });
      await test.info().attach(`${fixture.ticker}-${width}.png`, { path: screenshot, contentType: "image/png" });
    }
    await page.getByRole("button", { name: "instrument completed" }).click();
    await expect(page.getByRole("dialog").getByRole("link")).toHaveAttribute("href", exact);
  });
}
