import { expect, test } from "@playwright/test";

test("plain workspace hierarchy and chart remain readable on desktop and mobile", async ({
  page,
}) => {
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/events"))
      return route.fulfill({
        contentType: "text/event-stream",
        body: "event: completed\ndata: {}\n\n",
      });
    if (path.endsWith("/reports/latest"))
      return route.fulfill({
        status: 404,
        json: { error: { message: "Synthetic layout fixture" } },
      });
    if (path.endsWith("/qa")) return route.fulfill({ json: [] });
    if (path.endsWith("/snapshot"))
      return route.fulfill({
        json: [
          {
            lane: "instrument",
            status: "completed",
            payload: { name: "Synthetic AAPL Company", exchange: "SYNTHETIC", synthetic: true },
          },
          {
            lane: "quote",
            status: "completed",
            payload: {
              price: 159,
              currency: "USD",
              provider: "synthetic-v1",
              retrieved_at: "2025-12-31T21:00:00Z",
              synthetic: true,
            },
          },
          {
            lane: "ohlcv",
            status: "completed",
            payload: {
              currency: "USD",
              adjustment_policy: "synthetic, unadjusted",
              synthetic: true,
              candles: Array.from({ length: 30 }, (_, i) => ({
                timestamp: `2025-12-${String(i + 1).padStart(2, "0")}T21:00:00Z`,
                close: 130 + i,
              })),
            },
          },
          ...["filings", "statements"].map((lane) => ({
            lane,
            status: "completed",
            payload: { synthetic: true, limitations: ["Invented sample data only"] },
          })),
        ],
      });
    return route.fulfill({
      json: { id: "layout", ticker: "AAPL", asset_type: "equity", status: "completed" },
    });
  });
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    const landingSize = await page
      .locator("h1")
      .evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    await page.screenshot({ path: test.info().outputPath(`landing-${width}.png`), fullPage: true });
    await page.getByLabel(/ticker or etf/i).fill("AAPL");
    await page.getByRole("button", { name: /start research/i }).click();
    await expect(page.getByRole("heading", { name: "AAPL", exact: true })).toBeVisible();
    expect(
      await page.locator("h1").evaluate((el) => parseFloat(getComputedStyle(el).fontSize)),
    ).toBeLessThan(landingSize);
    await expect(page.locator(".history-chart")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({
      path: test.info().outputPath(`workspace-${width}.png`),
      fullPage: true,
    });
    await page.getByText("Show chart values", { exact: true }).click();
    await expect(page.locator("td.numeric").first()).toHaveCSS("text-align", "right");
    await expect(page.locator("td.numeric").first()).toHaveCSS(
      "font-variant-numeric",
      "lining-nums tabular-nums",
    );
  }
});
