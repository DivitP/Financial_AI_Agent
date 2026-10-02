import { test, expect } from "@playwright/test";

test("fixture dashboard and 10,000-finding report have bounded rendering", async ({ page }) => {
  const report = { id: "report", run_id: "perf", version: 1, as_of: "2026-10-01", model_configuration: {}, decision_brief: ["Fixture decision brief"],
    sections: [{ title: "Quality", findings: Array.from({ length: 10000 }, (_, i) => ({ summary: `Finding ${i}`, evidence_ids: ["e1"] })) }], evidence_links: { e1: "https://example.test/exact" } };
  await page.route("**/api/**", route => {
    const url = route.request().url();
    if (url.endsWith("/events")) return route.fulfill({ contentType: "text/event-stream", body: "event: completed\ndata: {}\n\n" });
    const json = url.endsWith("/reports/latest") ? report : url.endsWith("/snapshot") ? [{ lane: "instrument", status: "completed", payload: { name: "Fixture company" } }] : url.endsWith("/qa") ? [] : { id: "perf", ticker: "AAPL", status: "completed" };
    return route.fulfill({ json });
  });
  const start = performance.now();
  await page.goto("/runs/perf");
  await expect(page.getByText("Fixture company", { exact: true })).toBeVisible();
  const dashboardMs = performance.now() - start;
  await expect(page.getByText("Finding 0", { exact: true })).toBeVisible();
  const section = page.getByRole("region", { name: "Quality", exact: true });
  await expect(section.getByRole("article")).toHaveCount(25);
  const timings: number[] = [];
  for (let i = 1; i <= 20; i++) {
    const before = performance.now();
    await page.getByRole("button", { name: "Next findings", exact: true }).click();
    await expect(page.getByText(`Finding ${i * 25}`, { exact: true })).toBeVisible();
    timings.push(performance.now() - before);
    await expect(section.getByRole("article")).toHaveCount(25);
  }
  const p95 = timings.sort((a, b) => a - b)[18];
  console.log(JSON.stringify({ dashboard_ms: dashboardMs, report_navigation_p95_ms: p95, findings: 10000, visible_findings: 25 }));
  await test.info().attach("performance.json", { body: JSON.stringify({ dashboard_ms: dashboardMs, report_navigation_p95_ms: p95 }), contentType: "application/json" });
  // Broad regression budgets tolerate shared CI scheduling; aspirational targets are documented separately.
  expect(dashboardMs).toBeLessThan(5000);
  expect(p95).toBeLessThan(1000);
});
