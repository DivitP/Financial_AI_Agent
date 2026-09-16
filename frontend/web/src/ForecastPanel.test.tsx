import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import axe from "axe-core";
import { ForecastPanel, ForecastPage } from "./ForecastPanel";
import { ForecastResponse } from "./api";

const fixture: ForecastResponse = {
  status: "completed", quality: "experimental",
  forecast: { model_version: "pinned-model-v1", as_of: "2026-09-09T16:00:00-04:00", device: "cpu", currency: "USD", timezone: "America/New_York", provider: "fixture", adjustment_policy: "split_adjusted_as_of",
    historical_candles: [{ session: "2026-09-09", open: "100", high: "105", low: "98", close: "102" }],
    candles: [{ session: "2026-09-10", open: "102", high: "110", low: "90", close: "103" }],
    summary: { sample_count: 8, bands: [{ session: "2026-09-10", close_percentiles: { "5": "90", "25": "98", "50": "103", "75": "107", "95": "110" } }] }, warnings: ["Unvalidated output."] },
  validation: { id: "eval1", status: "experimental", created_at: "2026-09-10", reasons: ["threshold_failed:mase"], limitations: ["No calibrated confidence."],
    models: { kronos: { metrics: { mae: 2, rmse: 3, mase: null, terminal_direction_accuracy: .6, interval_coverage: .9 }, turnover: 2, drawdown: .12, windows: [{ as_of: "2026-01-01", sessions: ["2026-01-02", "2026-01-05"] }] } } },
};
afterEach(() => vi.unstubAllGlobals());

it("shows uncertain bands, provenance, scenarios, metrics and accessible values", async () => {
  const { container } = render(<ForecastPanel data={fixture} />);
  expect(screen.getByRole("img")).toHaveAccessibleName(/not a guaranteed price target/);
  expect(screen.getByText("pinned-model-v1")).toBeInTheDocument();
  expect(screen.getByText("90%")).toBeInTheDocument();
  expect(screen.getByText("12%")).toBeInTheDocument();
  expect(screen.getByText(/Experimental research/)).toBeInTheDocument();
  fireEvent.click(screen.getByText("Accessible chart values"));
  expect(screen.getByText(/O 100 H 105 L 98 C 102/)).toBeInTheDocument();
  fireEvent.click(screen.getByText("Backtest windows by model"));
  expect(screen.getByText(/2026-01-02 → 2026-01-05/)).toBeInTheDocument();
  const result = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  expect(result.violations).toEqual([]);
});

it("withholds a lone point or malformed bands and does not invent validation", () => {
  render(<ForecastPanel data={{ ...fixture, validation: null, forecast: { ...fixture.forecast!, summary: { sample_count: 1, bands: [] } } }} />);
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  expect(screen.getByText(/single forecast line is not shown/)).toBeInTheDocument();
  expect(screen.getByText(/No completed baseline comparison/)).toBeInTheDocument();
});

it("makes experimental fetching opt-in and supports explicit retry", async () => {
  const fetcher = vi.fn().mockImplementation(async (url: string) => ({ ok: true, json: async () => url.includes("=true") ? fixture : { status: "completed", quality: "experimental", forecast: null } }));
  vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { unmount } = render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/runs/r1/forecast"]}><Routes><Route path="/runs/:runId/forecast" element={<ForecastPage />} /></Routes></MemoryRouter></QueryClientProvider>);
  expect(await screen.findByText(/No visible forecast/)).toBeInTheDocument();
  expect(fetcher.mock.calls[0][0]).toContain("include_experimental=false");
  fireEvent.click(screen.getByRole("checkbox"));
  expect(await screen.findByText("pinned-model-v1")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Run or retry forecast" }));
  await screen.findByText("Forecast status: completed");
  unmount(); client.clear();
});

it("keeps failures visible without showing a price target", () => {
  render(<ForecastPanel data={{ status: "failed", quality: "experimental", warning: "Local inference unavailable" }} />);
  expect(screen.getByText("Local inference unavailable")).toBeInTheDocument();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
});
