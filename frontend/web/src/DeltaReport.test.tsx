import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { App } from "./App";

function show(payload: unknown) {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => payload });
  vi.stubGlobal("fetch", fetchMock);
  render(<MemoryRouter initialEntries={["/runs/new/changes"]}><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><App /></QueryClientProvider></MemoryRouter>);
  return fetchMock;
}

it("renders old and new exact evidence links without requesting live research", async () => {
  const fetchMock = show({ current_run_id: "new", previous_run_id: "old", basis: {}, limitations: ["Saved data only"], unchanged: [], changes: [{
    lane: "guidance", old: { low: 10, unit: "USD" }, new: { low: 12, unit: "USD" },
    old_evidence: [{ id: "old-evidence", exact_url: "https://example.com/old", provider: "sec", retrieved_at: "2025-01-01" }],
    new_evidence: [{ id: "new-evidence", exact_url: "https://example.com/new", provider: "sec", retrieved_at: "2026-01-01" }],
  }] });
  expect(await screen.findByRole("link", { name: "old-evidence" })).toHaveAttribute("href", "https://example.com/old");
  expect(screen.getByRole("link", { name: "new-evidence" })).toHaveAttribute("href", "https://example.com/new");
  expect(screen.getByRole("link", { name: "Open previous saved run" })).toHaveAttribute("href", "/history/old");
  expect(fetchMock.mock.calls.every(([path]) => path === "/api/v1/research-runs/new/delta")).toBe(true);
});

it("does not label missing comparisons as no change", async () => {
  show({ current_run_id: "new", previous_run_id: null, basis: {}, limitations: ["No earlier run"], unchanged: [], changes: [] });
  expect(await screen.findByText("No earlier run")).toBeInTheDocument();
  expect(screen.getByText(/This does not mean nothing changed/)).toBeInTheDocument();
});
