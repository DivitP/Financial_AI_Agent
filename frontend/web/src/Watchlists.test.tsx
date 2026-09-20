import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { App } from "./App";

const fetchMock = vi.fn();
beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal("fetch", fetchMock); });

it("creates lists and edits ticker notes without starting research", async () => {
  const lists: { id: string; name: string }[] = [];
  const items: Record<string, unknown>[] = [];
  fetchMock.mockImplementation((path: string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    if (init?.method === "POST") lists.push({ id: "one", name: body.name });
    if (init?.method === "PUT") { items.splice(0, items.length, { ...body, latest_run: null, freshness: [], upcoming_events: [] }); }
    return Promise.resolve({ ok: true, json: async () => path === "/api/v1/watchlists" ? init?.method === "POST" ? lists[0] : [...lists] : { ...lists[0], items: [...items] } });
  });
  render(<MemoryRouter initialEntries={["/watchlists"]}><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><App /></QueryClientProvider></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("New watchlist name"), { target: { value: "Long term" } });
  fireEvent.click(screen.getByRole("button", { name: "Create watchlist" }));
  await screen.findByRole("heading", { name: "Long term" });
  fireEvent.change(screen.getByLabelText("Ticker"), { target: { value: "aapl" } });
  fireEvent.change(screen.getByLabelText("Ticker notes"), { target: { value: "My thesis" } });
  fireEvent.change(screen.getByLabelText(/Tags \(comma/), { target: { value: "growth, quality" } });
  fireEvent.click(screen.getByRole("button", { name: "Save ticker" }));
  expect(await screen.findByText("My thesis")).toBeInTheDocument();
  expect(screen.getByText("No saved research. Symbol has not been resolved.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Edit AAPL" }));
  expect(screen.getByLabelText("Ticker notes")).toHaveValue("My thesis");
  await waitFor(() => expect(fetchMock.mock.calls.every(([path]) => path.startsWith("/api/v1/watchlists"))).toBe(true));
});

it("renders stored failure, stale data and event limitations", async () => {
  fetchMock.mockImplementation((path: string) => Promise.resolve({ ok: true, json: async () => path === "/api/v1/watchlists" ? [{ id: "one", name: "Saved" }] : {
    id: "one", name: "Saved", items: [{ ticker: "AAPL", notes: "", tags: [], latest_run: { id: "run", status: "failed", requested_at: "2026-01-01" }, freshness: [{ lane: "quote", status: "completed", state: "stale", retrieved_at: "2025-01-01" }], upcoming_events: [{ kind: "earnings", scheduled_at: "2026-10-01", release_session: "unknown", retrieved_at: null, evidence_ids: [], source_url: null }] }],
  } }));
  render(<MemoryRouter initialEntries={["/watchlists"]}><QueryClientProvider client={new QueryClient()}><App /></QueryClientProvider></MemoryRouter>);
  await screen.findByRole("option", { name: "Saved" });
  fireEvent.change(screen.getByLabelText("Choose watchlist"), { target: { value: "one" } });
  expect(await screen.findByText(/Latest research: failed/)).toBeInTheDocument();
  expect(screen.getByText(/quote: completed, stale/)).toBeInTheDocument();
  expect(screen.getByText(/Evidence unavailable/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Open saved AAPL research" })).toHaveAttribute("href", "/history/run");
});
