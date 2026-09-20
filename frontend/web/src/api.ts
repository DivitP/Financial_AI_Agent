export type RunStatus = "pending" | "running" | "completed" | "failed" | "cancelled";
export type LaneStatus = "completed" | "failed";

export interface ResearchRun { id: string; status: RunStatus; ticker: string; asset_type?: "equity" | "etf"; correlation_id: string }
export interface ResearchSnapshot { lane: string; status: LaneStatus; payload: Record<string, unknown> | null; error_message: string | null }
export interface ResearchReport { id: string; run_id: string; version: number; as_of: string; model_configuration: Record<string, string>; decision_brief: string[]; sections: { title: string; findings: { summary: string; evidence_ids: string[]; limitations?: string[] }[] }[]; evidence_links: Record<string, string> }
export interface ResearchRequest { ticker: string; investment_horizon?: string; risk_lens?: string; thesis?: string; include_kronos?: boolean; forecast_horizon?: number }
export interface ApiFailure extends Error { code?: string; correlationId?: string }
export interface HistoryItem { id: string; ticker: string; status: RunStatus; requested_at: string; name: string | null; archived: boolean; report_count: number }
export interface HistoryView { run: Omit<HistoryItem, "report_count">; versions: { version: number; as_of: string; created_at: string }[]; report: ResearchReport | null; snapshots: ResearchSnapshot[]; notice: string }

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { headers: { "Content-Type": "application/json", ...init?.headers }, ...init });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { error?: { code?: string; message?: string }; correlation_id?: string } | null;
    const error = new Error(body?.error?.message ?? "The research service is unavailable.") as ApiFailure;
    error.code = body?.error?.code;
    error.correlationId = body?.correlation_id;
    throw error;
  }
  return response.json() as Promise<T>;
}

export const researchApi = {
  history: (filters: Record<string, string>) => request<HistoryItem[]>(`/api/v1/research-runs?${new URLSearchParams(filters)}`),
  saved: (id: string, version: string | null) => request<HistoryView>(`/api/v1/research-runs/${id}/history${version ? `?version=${encodeURIComponent(version)}` : ""}`),
  updateHistory: (id: string, fields: { name?: string | null; archived?: boolean }) => request<HistoryView>(`/api/v1/research-runs/${id}/history`, { method: "PATCH", body: JSON.stringify(fields) }),
  forecast: (id: string, experimental: boolean, execute = false) => request<ForecastResponse>(`/api/v1/research-runs/${id}/forecast?include_experimental=${experimental}`, execute ? { method: "POST" } : undefined),
  create: (payload: ResearchRequest) => request<ResearchRun>("/api/v1/research-runs", { method: "POST", body: JSON.stringify(payload) }),
  get: (id: string) => request<ResearchRun>(`/api/v1/research-runs/${id}`),
  snapshots: async (id: string) => {
    const result = await request<unknown>(`/api/v1/research-runs/${id}/snapshot`);
    if (!Array.isArray(result)) throw new Error("The research service returned an invalid snapshot response.");
    return result as ResearchSnapshot[];
  },
  report: async (id: string) => {
    const result = await request<unknown>(`/api/v1/research-runs/${id}/reports/latest`);
    if (!result || typeof result !== "object" || !Array.isArray((result as ResearchReport).decision_brief) || !Array.isArray((result as ResearchReport).sections)) throw new Error("The research service returned an invalid report response.");
    return result as ResearchReport;
  },
  cancel: (id: string) => request<ResearchRun>(`/api/v1/research-runs/${id}/cancel`, { method: "POST" }),
  retry: (id: string) => request<ResearchRun>(`/api/v1/research-runs/${id}/retry`, { method: "POST" }),
};

export interface ForecastCandle { session: string; open: string | number; high: string | number; low: string | number; close: string | number }
export interface ForecastBand { session: string; close_percentiles: Record<string, string | number> }
export interface ForecastResponse {
  status: string; quality: string; warning?: string | null;
  forecast?: { model_version: string; device: string; as_of: string; currency?: string; timezone?: string; provider?: string; adjustment_policy?: string;
    historical_candles?: ForecastCandle[]; candles: ForecastCandle[]; warnings?: string[];
    summary?: { sample_count: number; bands: ForecastBand[]; direction_probability?: Record<string, number> } } | null;
  validation?: { id: string; status: string; created_at: string; reasons: string[]; limitations: string[];
    models: Record<string, { metrics: Record<string, number | null>; turnover: number; drawdown: number; windows: { as_of: string; sessions: string[] }[] }> } | null;
}

export function subscribeToRun(id: string, onEvent: (event: MessageEvent<string>) => void, onError: () => void): EventSource {
  const source = new EventSource(`/api/v1/research-runs/${id}/events`);
  source.onmessage = onEvent;
  for (const type of ["queued", "started", "progress", "completed", "failed", "cancelled"]) {
    source.addEventListener(type, onEvent);
  }
  source.onerror = onError;
  return source;
}
