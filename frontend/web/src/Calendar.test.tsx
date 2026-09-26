import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { CalendarPage } from "./Calendar";

it("shows exact sources, timezone and unknown date confidence without live calls", async () => {
  const fetchMock = vi.fn().mockImplementation((path: string) => Promise.resolve({ ok: true, json: async () => path === "/api/v1/watchlists" ? [{ id: "list", name: "Saved list" }] : {
    notice: "Saved dates only", limitations: [], events: [{ id: "event", title: "Earnings", kind: "earnings", scheduled_at: "2026-11-02", timezone: "unknown (date only)", precision: "date", date_confidence: "unknown", confidence_basis: "Saved status", release_session: "unknown", tickers: ["AAPL"], sources: [{ ticker: "AAPL", run_id: "run", evidence: [{ id: "e1", exact_url: "https://example.com/events/original", provider: "fixture", retrieved_at: "2026-01-01" }] }] }],
  } }));
  vi.stubGlobal("fetch", fetchMock);
  render(<MemoryRouter><QueryClientProvider client={new QueryClient()}><CalendarPage /></QueryClientProvider></MemoryRouter>);
  expect(await screen.findByText(/Date confidence: unknown/)).toBeInTheDocument();
  expect(screen.getByText(/Timezone: unknown/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "fixture: e1" })).toHaveAttribute("href", "https://example.com/events/original");
  fireEvent.change(screen.getByLabelText("Watchlist"), { target: { value: "list" } });
  fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
  await waitFor(() => expect(fetchMock.mock.calls.some(([path]) => path.includes("watchlist_id=list"))).toBe(true));
  expect(fetchMock.mock.calls.every(([path]) => path === "/api/v1/watchlists" || path.startsWith("/api/v1/calendar?"))).toBe(true);
});
