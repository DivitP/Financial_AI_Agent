import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { PortfolioPage } from "./Portfolio";

function show() {
  render(<MemoryRouter><QueryClientProvider client={new QueryClient()}><PortfolioPage /></QueryClientProvider></MemoryRouter>);
}
it("rejects invalid totals without submitting", () => {
  const fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock); show();
  fireEvent.change(screen.getByLabelText(/Holdings/), { target: { value: "AAPL, 50" } });
  fireEvent.change(screen.getByLabelText("Candidate ticker"), { target: { value: "MSFT" } });
  fireEvent.click(screen.getByRole("button", { name: "Analyze hypothetical portfolio" }));
  expect(screen.getByRole("alert")).toHaveTextContent("totaling 100%");
  expect(fetchMock).not.toHaveBeenCalled();
});
it("shows hypothetical concentration and missing-risk limitations using only the context API", async () => {
  const exposure = { weights: { AAPL: 1 }, largest_weight: 1, hhi: 1, sector_weights: { Unknown: 1 }, factor_loadings: {}, factor_note: "Unknown exposure" };
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ before: exposure, after: exposure, historical_risk: { available: false, reason: "Missing cited prices" }, sources: {}, limitations: ["Historical, not predictive"] }) });
  vi.stubGlobal("fetch", fetchMock); show();
  fireEvent.change(screen.getByLabelText("Candidate ticker"), { target: { value: "NVDA" } });
  fireEvent.click(screen.getByRole("button", { name: "Analyze hypothetical portfolio" }));
  expect(await screen.findByText("Unavailable: Missing cited prices")).toBeInTheDocument();
  expect(screen.getByText(/No brokerage connection/)).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(fetchMock).toHaveBeenCalledWith("/api/v1/portfolio-context", expect.objectContaining({ method: "POST" }));
});
