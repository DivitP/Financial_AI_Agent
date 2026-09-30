import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

const payload = '<img src=x onerror="window.xssExecuted=true"><script>window.xssExecuted=true</script>';

test("research evidence stays text and CSP blocks inline execution", async ({ page }) => {
  const run = { id: "xss-run", ticker: "AAPL", status: "completed", correlation_id: "fixture" };
  await page.route("**/api/v1/research-runs/xss-run/qa", route => route.fulfill({ json: [] }));
  await page.route("**/api/v1/research-runs/xss-run/reports/latest", route => route.fulfill({ status: 404, json: { error: { message: "No report" } } }));
  await page.route("**/api/v1/research-runs", route => route.fulfill({ json: run, status: 202 }));
  await page.route("**/api/v1/research-runs/xss-run", route => route.fulfill({ json: run }));
  await page.route("**/api/v1/research-runs/xss-run/snapshot", route => route.fulfill({ json: [
    { lane: "instrument", status: "completed", payload: { name: payload, url: "javascript:window.xssExecuted=true" }, error_message: null },
  ] }));
  await page.route("**/api/v1/research-runs/xss-run/events", route => route.fulfill({ contentType: "text/event-stream", body: "event: completed\ndata: {}\n\n" }));
  const response = await page.goto("/");
  expect(response?.headers()["content-security-policy"]).toContain("object-src 'none'");
  await page.getByLabel(/ticker or etf/i).fill("AAPL");
  await page.getByRole("button", { name: /start research/i }).click();
  await expect(page.getByText(payload, { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /instrument/i }).click();
  await expect(page.locator('a[href^="javascript:"]')).toHaveCount(0);
  await expect(page.locator('img[src="x"]')).toHaveCount(0);
  await page.evaluate(() => {
    const script = document.createElement("script");
    script.textContent = "window.xssExecuted=true";
    document.body.append(script);
  });
  expect(await page.evaluate(() => Reflect.get(window, "xssExecuted"))).toBeUndefined();
});

test("legacy answers create text nodes, not executable HTML", async ({ page }) => {
  const script = readFileSync(new URL("../../static/legacy.js", import.meta.url), "utf8");
  await page.route("**/legacy-fixture", route => route.fulfill({ contentType: "text/html", body:
    '<body><form id="askForm"><input id="tickerHidden" value="AAPL"><input id="questionInput" value="question"><button>Ask</button></form><div id="answerContainer"></div><script src="/legacy-test.js"></script></body>' }));
  await page.route("**/legacy-test.js", route => route.fulfill({ contentType: "text/javascript", body: script }));
  await page.route("**/api/ask", route => route.fulfill({ json: { answer: payload, sources: ["javascript:window.xssExecuted=true", "https://example.com/filing"] } }));
  await page.goto("/legacy-fixture");
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page.locator("#answerContainer")).toContainText(payload);
  await expect(page.locator("#answerContainer img, #answerContainer script")).toHaveCount(0);
  await expect(page.getByRole("link")).toHaveAttribute("href", "https://example.com/filing");
  expect(await page.evaluate(() => Reflect.get(window, "xssExecuted"))).toBeUndefined();
});
