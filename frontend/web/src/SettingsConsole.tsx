import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { request } from "./api";

interface Health { notice: string; providers: { provider: string; enabled: boolean | null; selection: string; credential_configured: boolean | null; free_tier_status: string; last_successful_request: string | null; recorded_requests: number; quota_warnings: string[]; rate_limit_responses_24h: number }[];
  models: { provider: string; enabled: boolean; identifier: string; dependencies_installed: boolean; availability: string }[];
  cache: Record<string, string | number>; feature_flags: Record<string, boolean>; configured_defaults: Record<string, number> }
export function SettingsConsole() {
  const health = useQuery({ queryKey: ["settings-health"], queryFn: () => request<Health>("/api/v1/settings/health"), retry: false, staleTime: 60_000, refetchOnWindowFocus: false });
  return <div className="app-shell"><nav aria-label="Primary navigation"><Link to="/">New research</Link><Link to="/watchlists">Watchlists</Link><Link to="/history">Saved research</Link></nav><main>
    <h1>Settings and data health</h1><p>Read-only. Credentials, model identifiers, endpoints and local paths are not exposed.</p><button disabled={health.isFetching} onClick={() => health.refetch()}>Refresh local status</button>
    {health.isLoading && <p role="status">Loading local health…</p>}{health.error && <p role="alert">{health.error.message}</p>}
    {health.data && <><p>{health.data.notice}</p><h2>Providers and free-tier status</h2>{health.data.providers.map(p => <section className="card" key={p.provider}><h3>{p.provider}</h3><p>{p.enabled === null ? "Workflow-selected" : p.enabled ? "Enabled" : "Disabled"} · {p.selection}</p>{p.credential_configured !== null && <p>Credential configured: {p.credential_configured ? "Yes (not validated)" : "No"}</p>}<p>{p.free_tier_status}</p><p>Last recorded success: {p.last_successful_request ?? "Unknown / no recorded success"}</p><p>{p.recorded_requests} recorded requests · {p.rate_limit_responses_24h} rate-limit responses in 24 hours</p><ul>{p.quota_warnings.map(w => <li key={w}>{w}</li>)}</ul></section>)}
      <h2>Model availability</h2>{health.data.models.map(m => <section className="card" key={m.provider}><h3>{m.provider}</h3><p>{m.enabled ? "Enabled" : "Disabled"} · {m.identifier}</p><p>Dependencies installed: {m.dependencies_installed ? "Yes" : "No"}</p><p>{m.availability}</p></section>)}
      <h2>Cache state</h2><dl>{Object.entries(health.data.cache).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>)}</dl>
      <h2>Feature flags</h2><ul>{Object.entries(health.data.feature_flags).map(([key, value]) => <li key={key}>{key}: {value ? "enabled" : "disabled"}</li>)}</ul>
      <h2>Configured defaults (not provider quota)</h2><ul>{Object.entries(health.data.configured_defaults).map(([key, value]) => <li key={key}>{key}: {value}</li>)}</ul>
    </>}
  </main></div>;
}
