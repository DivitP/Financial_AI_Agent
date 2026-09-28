import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { SettingsConsole } from "./SettingsConsole";

it("shows unknowns, quota warnings and safe read-only refresh", async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({
    notice: "No provider probes", providers: [{ provider: "fmp", enabled: true, selection: "configured flag", credential_configured: true, free_tier_status: "unverified account plan", last_successful_request: null, recorded_requests: 1, quota_warnings: ["Rate-limit responses recorded"], rate_limit_responses_24h: 1 }],
    models: [{ provider: "groq", enabled: false, identifier: "configured (identifier hidden)", dependencies_installed: false, availability: "not probed" }],
    cache: { state: "unobserved" }, feature_flags: { enable_groq: false }, configured_defaults: { cache_ttl_seconds: 900 },
  }) });
  vi.stubGlobal("fetch", fetchMock);
  render(<MemoryRouter><QueryClientProvider client={new QueryClient()}><SettingsConsole /></QueryClientProvider></MemoryRouter>);
  expect(await screen.findByText("unverified account plan")).toBeInTheDocument();
  expect(screen.getByText("Rate-limit responses recorded")).toBeInTheDocument();
  expect(screen.getByText("unobserved")).toBeInTheDocument();
  expect(screen.getByText("not probed")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Refresh local status" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  expect(fetchMock.mock.calls.every(([path, options]) => path === "/api/v1/settings/health" && !options.method)).toBe(true);
});
