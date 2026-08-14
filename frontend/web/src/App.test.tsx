import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import axe from "axe-core";
import { App } from "./App";

const fetchMock = vi.fn();
class FakeEventSource { static instances: FakeEventSource[] = []; onmessage: ((event: MessageEvent<string>) => void) | null = null; onerror: (() => void) | null = null; close = vi.fn(); addEventListener = vi.fn(); constructor(_: string) { FakeEventSource.instances.push(this); } }

function renderApp(route = "/") { const query = new QueryClient({ defaultOptions: { queries: { retry: false } } }); return render(<MemoryRouter initialEntries={[route]}><QueryClientProvider client={query}><App /></QueryClientProvider></MemoryRouter>); }

describe("research workspace", () => {
  beforeEach(() => { vi.stubGlobal("fetch", fetchMock); vi.stubGlobal("EventSource", FakeEventSource); fetchMock.mockReset(); FakeEventSource.instances = []; });
  it("validates a ticker before starting research", () => { renderApp(); const input = screen.getByLabelText(/ticker or etf/i); fireEvent.change(input, { target: { value: "bad ticker!" } }); expect(screen.getByRole("alert")).toHaveTextContent(/valid ticker/i); expect(screen.getByRole("button", { name: /start research/i })).toBeDisabled(); });
  it("has no detectable form accessibility violations", async () => { renderApp(); const results = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } }); expect(results.violations).toEqual([]); });
  it("starts a research run from the form", async () => { fetchMock.mockResolvedValue({ ok: true, json: async () => ({ id: "new-run", ticker: "AAPL", status: "pending", correlation_id: "correlation" }) }); renderApp(); fireEvent.change(screen.getByLabelText(/ticker or etf/i), { target: { value: "aapl" } }); fireEvent.click(screen.getByRole("button", { name: /start research/i })); await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/v1/research-runs", expect.objectContaining({ method: "POST" }))); });
  it("renders a completed evidence-first snapshot without an LLM", async () => { fetchMock.mockImplementation((path: string) => Promise.resolve({ ok: true, json: async () => path.endsWith("/snapshot") ? [{ lane: "instrument", status: "completed", payload: { name: "Apple Inc.", exchange: "NASDAQ", url: "https://example.com/aapl" }, error_message: null }, { lane: "quote", status: "completed", payload: { price: 200, retrieved_at: "2026-01-01" }, error_message: null }] : { id: "test", ticker: "AAPL", status: "completed", correlation_id: "correlation" } })); renderApp("/runs/test"); await waitFor(() => expect(screen.getByRole("heading", { name: "AAPL" })).toBeInTheDocument()); expect(screen.getByText("Apple Inc.")).toBeInTheDocument(); fireEvent.click(screen.getByRole("button", { name: /instrument/i })); expect(screen.getByRole("dialog")).toHaveTextContent("https://example.com/aapl"); });
  it.each(["failed", "cancelled"])("offers retry for a %s run", async (status) => { fetchMock.mockResolvedValue({ ok: true, json: async () => ({ id: "test", ticker: "AAPL", status, correlation_id: "correlation" }) }); renderApp("/runs/test"); expect(await screen.findByRole("button", { name: /retry research/i })).toBeInTheDocument(); });
  it("shows a reconnecting state when the progress stream disconnects", async () => { fetchMock.mockResolvedValue({ ok: true, json: async () => ({ id: "test", ticker: "AAPL", status: "running", correlation_id: "correlation" }) }); renderApp("/runs/test"); await screen.findByRole("heading", { name: "AAPL" }); FakeEventSource.instances[0].onerror?.(); expect(await screen.findByText(/reconnecting to progress/i)).toBeInTheDocument(); });
});
