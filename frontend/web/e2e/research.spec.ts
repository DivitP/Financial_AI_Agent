import { expect, test } from "@playwright/test";

const run = { id: "fixture-run", ticker: "AAPL", status: "completed", correlation_id: "fixture" };
const snapshots = [
  { lane: "instrument", status: "completed", payload: { name: "Apple Inc.", exchange: "NASDAQ", url: "https://example.test/AAPL" }, error_message: null },
  { lane: "quote", status: "completed", payload: { price: 200, retrieved_at: "2026-08-14T12:00:00Z" }, error_message: null },
  { lane: "ohlcv", status: "completed", payload: { provider: "fixture-market" }, error_message: null },
  { lane: "filings", status: "completed", payload: { url: "https://example.test/filings/AAPL" }, error_message: null },
  { lane: "statements", status: "completed", payload: { provider: "fixture-sec" }, error_message: null },
];

test("fixture-backed research completes from form to evidence", async ({ page }) => {
  await page.route("**/api/v1/research-runs", async (route) => {
    if (route.request().method() === "POST") await route.fulfill({ json: run, status: 202 });
    else await route.continue();
  });
  await page.route("**/api/v1/research-runs/fixture-run", (route) => route.fulfill({ json: run }));
  await page.route("**/api/v1/research-runs/fixture-run/snapshot", (route) => route.fulfill({ json: snapshots }));
  await page.route("**/api/v1/research-runs/fixture-run/events", (route) => route.fulfill({ contentType: "text/event-stream", body: "event: completed\ndata: {}\n\n" }));

  await page.goto("/");
  await page.getByLabel(/ticker or etf/i).fill("AAPL");
  await page.getByRole("button", { name: /start research/i }).click();
  await expect(page.getByRole("heading", { name: "AAPL" })).toBeVisible();
  await expect(page.getByText("Apple Inc.")).toBeVisible();
  await page.getByRole("button", { name: /instrument/i }).click();
  await expect(page.getByRole("dialog")).toContainText("https://example.test/AAPL");
});
