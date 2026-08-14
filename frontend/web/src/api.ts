export type RunStatus = "pending" | "running" | "completed" | "failed" | "cancelled";
export type LaneStatus = "completed" | "failed";

export interface ResearchRun { id: string; status: RunStatus; ticker: string; correlation_id: string }
export interface ResearchSnapshot { lane: string; status: LaneStatus; payload: Record<string, unknown> | null; error_message: string | null }
export interface ResearchRequest { ticker: string; investment_horizon?: string; risk_lens?: string; thesis?: string }
export interface ApiFailure extends Error { code?: string; correlationId?: string }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
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
  create: (payload: ResearchRequest) => request<ResearchRun>("/api/v1/research-runs", { method: "POST", body: JSON.stringify(payload) }),
  get: (id: string) => request<ResearchRun>(`/api/v1/research-runs/${id}`),
  snapshots: (id: string) => request<ResearchSnapshot[]>(`/api/v1/research-runs/${id}/snapshot`),
  cancel: (id: string) => request<ResearchRun>(`/api/v1/research-runs/${id}/cancel`, { method: "POST" }),
  retry: (id: string) => request<ResearchRun>(`/api/v1/research-runs/${id}/retry`, { method: "POST" }),
};

export function subscribeToRun(id: string, onEvent: (event: MessageEvent<string>) => void, onError: () => void): EventSource {
  const source = new EventSource(`/api/v1/research-runs/${id}/events`);
  source.onmessage = onEvent;
  for (const type of ["queued", "started", "progress", "completed", "failed", "cancelled"]) {
    source.addEventListener(type, onEvent);
  }
  source.onerror = onError;
  return source;
}
