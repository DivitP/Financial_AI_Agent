import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { App } from "./App";

const fetchMock = vi.fn();
function renderPage(route: string) {
  return render(<MemoryRouter initialEntries={[route]}><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><App /></QueryClientProvider></MemoryRouter>);
}
const run = { id: "old", ticker: "AAPL", name: "Original thesis", archived: false, status: "completed", requested_at: "2025-01-01", report_count: 2 };
beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal("fetch", fetchMock); vi.stubGlobal("EventSource", vi.fn(() => { throw new Error("History must not stream live data"); })); });

it("filters saved runs and links to the saved-only view", async () => {
  fetchMock.mockResolvedValue({ ok: true, json: async () => [run] });
  renderPage("/history");
  expect(await screen.findByRole("link", { name: "Original thesis" })).toHaveAttribute("href", "/history/old");
  fireEvent.change(screen.getByLabelText("Search ticker or name"), { target: { value: "AAPL" } });
  fireEvent.change(screen.getByLabelText("Archive filter"), { target: { value: "archived" } });
  await waitFor(() => expect(fetchMock.mock.calls.some(([path]) => path.includes("q=AAPL&archive=archived"))).toBe(true));
});

it("reopens pinned versions, names and archives without calling live endpoints", async () => {
  fetchMock.mockImplementation((path: string, init?: RequestInit) => {
    const version = path.includes("version=2") ? 2 : 1;
    return Promise.resolve({ ok: true, json: async () => ({
      run: { ...run, ...(init?.body ? JSON.parse(String(init.body)) : {}) },
      notice: "Saved history only. No current data was fetched.",
      versions: [{ version: 1, as_of: "2025-01-01" }, { version: 2, as_of: "2026-01-01" }],
      report: { id: "r", version, as_of: version === 1 ? "2025-01-01" : "2026-01-01", decision_brief: ["Saved brief"], sections: [{ title: "Sources", findings: [{ summary: "Saved finding", evidence_ids: ["e1"] }] }], evidence_links: { e1: "https://www.sec.gov/Archives/original" }, model_configuration: {} },
      snapshots: [],
    }) });
  });
  renderPage("/history/old?version=1");
  expect(await screen.findByText("Original as-of: 2025-01-01")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Export PDF" })).toHaveAttribute("href", "/api/v1/research-runs/old/export?version=1&format=pdf");
  expect(screen.getByRole("link", { name: "e1" })).toHaveAttribute("href", "https://www.sec.gov/Archives/original");
  fireEvent.change(screen.getByLabelText("Saved report version"), { target: { value: "2" } });
  expect(await screen.findByText("Original as-of: 2026-01-01")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Export JSON" })).toHaveAttribute("href", "/api/v1/research-runs/old/export?version=2&format=json");
  fireEvent.change(screen.getByLabelText("Run name"), { target: { value: "My thesis" } });
  fireEvent.click(screen.getByRole("button", { name: "Save name" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/v1/research-runs/old/history", expect.objectContaining({ method: "PATCH", body: '{"name":"My thesis"}' })));
  await waitFor(() => expect(screen.getByRole("button", { name: "Archive run" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Archive run" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/v1/research-runs/old/history", expect.objectContaining({ method: "PATCH", body: '{"archived":true}' })));
  expect(fetchMock.mock.calls.every(([path]) => path.startsWith("/api/v1/research-runs/old/history"))).toBe(true);
});
