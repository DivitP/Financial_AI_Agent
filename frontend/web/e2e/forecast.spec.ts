import { test, expect } from "@playwright/test";

test("forecast is opt-in, uncertain and readable on desktop and mobile", async ({ page }) => {
  const fixture = { status: "completed", quality: "experimental", forecast: {
    model_version: "fixture-kronos-small", as_of: "2026-09-09T16:00:00-04:00", device: "cpu", currency: "USD", provider: "offline fixture", timezone: "America/New_York", adjustment_policy: "split_adjusted_as_of",
    historical_candles: [3, 4, 8, 9].map((d, i) => ({ session: `2026-09-0${d}`, open: 100 + i, high: 104 + i, low: 98 + i, close: 102 + i })),
    candles: [10, 11].map(d => ({ session: `2026-09-${d}`, close: 105 })),
    summary: { sample_count: 8, bands: [10, 11].map((d, i) => ({ session: `2026-09-${d}`, close_percentiles: { "5": 97 - i * 2, "25": 101 - i, "50": 105, "75": 107 + i, "95": 111 + i * 2 } })) }, warnings: ["Unvalidated sample distribution; not investment advice."] } };
  await page.route("**/api/v1/research-runs/*/forecast?*", route => route.fulfill({ json: route.request().url().includes("=true") ? fixture : { ...fixture, forecast: null } }));
  await page.goto("/runs/fixture/forecast");
  await expect(page.getByText(/No visible forecast/)).toBeVisible();
  await page.getByRole("checkbox").check();
  await expect(page.getByRole("img", { name: /not a guaranteed price target/ })).toBeVisible();
  await expect(page.getByText("fixture-kronos-small")).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("forecast-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: test.info().outputPath("forecast-mobile.png"), fullPage: true });
});
