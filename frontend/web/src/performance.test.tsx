import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { ReportSections } from "./ReportSections";
import { downsampleCandles } from "./downsample";

it("bounds report DOM and keeps each paged citation exact", () => {
  const findings = Array.from({ length: 10000 }, (_, i) => ({
    summary: `Finding ${i}`,
    evidence_ids: ["e1"],
  }));
  render(
    <ReportSections
      report={{
        id: "r",
        run_id: "run",
        version: 1,
        as_of: "2026-10-01",
        model_configuration: {},
        decision_brief: [],
        sections: [{ title: "Quality", findings }],
        evidence_links: { e1: "https://example.test/source#exact" },
      }}
    />,
  );
  expect(screen.getAllByRole("article")).toHaveLength(25);
  fireEvent.click(screen.getByRole("button", { name: "Next findings" }));
  expect(screen.getByText("Finding 25")).toBeVisible();
  expect(screen.queryByText("Finding 0")).not.toBeInTheDocument();
  expect(screen.getAllByRole("link")[0]).toHaveAttribute(
    "href",
    "https://example.test/source#exact",
  );
});

it("preserves OHLC extrema and full time extent without mutating source candles", () => {
  const candles = Array.from({ length: 1000 }, (_, i) => ({
    session: String(i),
    open: i + 1,
    high: i + 4,
    low: i,
    close: i + 2,
  }));
  const before = JSON.stringify(candles);
  const reduced = downsampleCandles(candles, 60);
  expect(reduced).toHaveLength(60);
  expect(reduced[0].open).toBe(1);
  expect(reduced.at(-1)!.close).toBe(1001);
  expect(Math.max(...reduced.map((c) => Number(c.high)))).toBe(1003);
  expect(Math.min(...reduced.map((c) => Number(c.low)))).toBe(0);
  expect(JSON.stringify(candles)).toBe(before);
  expect(() => downsampleCandles(candles, 0)).toThrow();
});
