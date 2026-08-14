import { FormEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Navigate, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { ApiFailure, researchApi, ResearchRequest, ResearchSnapshot, subscribeToRun } from "./api";

const tickerPattern = /^[A-Za-z0-9][A-Za-z0-9._-]{0,14}$/;

export function App() {
  return <Routes><Route path="/" element={<ResearchForm />} /><Route path="/runs/:runId" element={<ResearchDashboard />} /><Route path="*" element={<Navigate to="/" replace />} /></Routes>;
}

function ResearchForm() {
  const navigate = useNavigate();
  const [form, setForm] = useState<ResearchRequest>({ ticker: "", investment_horizon: "medium", risk_lens: "balanced", thesis: "" });
  const mutation = useMutation({ mutationFn: researchApi.create, onSuccess: (run) => navigate(`/runs/${run.id}`) });
  const valid = tickerPattern.test(form.ticker.trim());
  function submit(event: FormEvent) { event.preventDefault(); if (valid) mutation.mutate({ ...form, ticker: form.ticker.trim().toUpperCase() }); }
  return <Shell><main className="landing"><p className="eyebrow">Evidence-first research</p><h1>Start with the facts.</h1><p className="lede">Build a source-grounded investment research snapshot. This is research and education, not personalized investment advice.</p><form className="research-form" onSubmit={submit} noValidate>
    <label htmlFor="ticker">Ticker or ETF symbol</label><input id="ticker" value={form.ticker} onChange={(e) => setForm({ ...form, ticker: e.target.value })} aria-describedby="ticker-help ticker-error" autoCapitalize="characters" placeholder="AAPL" required />
    <small id="ticker-help">Letters, numbers, periods, underscores, or hyphens; up to 15 characters.</small>{form.ticker && !valid && <p id="ticker-error" className="field-error" role="alert">Enter a valid ticker symbol.</p>}
    <div className="form-grid"><label>Investment horizon<select value={form.investment_horizon} onChange={(e) => setForm({ ...form, investment_horizon: e.target.value })}><option value="short">Short term</option><option value="medium">Medium term</option><option value="long">Long term</option></select></label><label>Risk lens<select value={form.risk_lens} onChange={(e) => setForm({ ...form, risk_lens: e.target.value })}><option value="balanced">Balanced</option><option value="conservative">Conservative</option><option value="growth">Growth</option></select></label></div>
    <label htmlFor="thesis">Optional thesis</label><textarea id="thesis" value={form.thesis} onChange={(e) => setForm({ ...form, thesis: e.target.value })} maxLength={500} placeholder="What are you looking to validate?" />
    {mutation.error && <ErrorNotice error={mutation.error as ApiFailure} />}<button type="submit" disabled={!valid || mutation.isPending}>{mutation.isPending ? "Starting research…" : "Start research"}</button>
  </form></main></Shell>;
}

function ResearchDashboard() {
  const { runId = "" } = useParams(); const client = useQueryClient(); const [streamState, setStreamState] = useState("Connecting to progress updates…");
  const run = useQuery({ queryKey: ["run", runId], queryFn: () => researchApi.get(runId), refetchInterval: (query) => active(query.state.data?.status) ? 2_000 : false });
  const snapshots = useQuery({ queryKey: ["snapshots", runId], queryFn: () => researchApi.snapshots(runId), refetchInterval: () => active(run.data?.status) ? 2_000 : false });
  const cancel = useMutation({ mutationFn: () => researchApi.cancel(runId), onSuccess: () => client.invalidateQueries({ queryKey: ["run", runId] }) });
  const retry = useMutation({ mutationFn: () => researchApi.retry(runId), onSuccess: () => { client.invalidateQueries({ queryKey: ["run", runId] }); client.invalidateQueries({ queryKey: ["snapshots", runId] }); } });
  useEffect(() => { if (!runId) return; const source = subscribeToRun(runId, () => { setStreamState("Live progress connected"); client.invalidateQueries({ queryKey: ["run", runId] }); client.invalidateQueries({ queryKey: ["snapshots", runId] }); }, () => setStreamState("Reconnecting to progress updates…")); return () => source.close(); }, [client, runId]);
  if (run.isLoading) return <Shell><Loading /></Shell>; if (run.error || !run.data) return <Shell><ErrorNotice error={run.error as ApiFailure} /></Shell>;
  return <Shell><main><Link to="/" className="back-link">← New research</Link><header className="run-header"><div><p className="eyebrow">Research run</p><h1>{run.data.ticker}</h1><p className="muted">{streamState}</p></div><Status status={run.data.status} /></header>
    <Progress snapshots={snapshots.data ?? []} status={run.data.status} />
    <div className="actions">{active(run.data.status) && <button className="secondary" onClick={() => cancel.mutate()} disabled={cancel.isPending}>Cancel run</button>}{["failed", "cancelled"].includes(run.data.status) && <button onClick={() => retry.mutate()} disabled={retry.isPending}>Retry research</button>}</div>
    {run.data.status === "completed" && <Overview snapshots={snapshots.data ?? []} ticker={run.data.ticker} />}{snapshots.error && <ErrorNotice error={snapshots.error as ApiFailure} />}
  </main></Shell>;
}

function Progress({ snapshots, status }: { snapshots: ResearchSnapshot[]; status: string }) { const lanes = ["instrument", "quote", "ohlcv", "filings", "statements"]; return <section aria-labelledby="progress-heading" className="card"><h2 id="progress-heading">Collection progress</h2><ol className="lanes">{lanes.map((lane) => { const item = snapshots.find((snapshot) => snapshot.lane === lane); return <li key={lane}><span>{lane}</span><Status status={item?.status ?? (status === "cancelled" ? "cancelled" : "pending")} />{item?.error_message && <span className="field-error">{item.error_message}</span>}</li>; })}</ol></section>; }

function Overview({ snapshots, ticker }: { snapshots: ResearchSnapshot[]; ticker: string }) { const [evidence, setEvidence] = useState<ResearchSnapshot | null>(null); const quote = snapshots.find((item) => item.lane === "quote")?.payload; const identity = snapshots.find((item) => item.lane === "instrument")?.payload; return <><section className="dashboard-grid" aria-label="Research overview"><InfoCard title="Company identity" value={stringValue(identity, "name") ?? ticker} detail={stringValue(identity, "exchange") ?? "Identity source pending"} /><InfoCard title="Quote" value={stringValue(quote, "price") ?? "Unavailable"} detail={freshness(quote)} /><InfoCard title="Financial trends" value={summary(snapshots, "statements")} detail="Reported figures retain filing periods and units." /><InfoCard title="Latest filings" value={summary(snapshots, "filings")} detail="Source links are retained with the evidence." /></section><section className="card"><h2>Evidence</h2><p className="muted">Open a collection result to inspect its exact source links and payload. No language model is required for this view.</p><div className="evidence-list">{snapshots.map((item) => <button className="evidence-button" key={item.lane} onClick={() => setEvidence(item)}>{item.lane}<Status status={item.status} /></button>)}</div></section>{evidence && <EvidenceDrawer snapshot={evidence} onClose={() => setEvidence(null)} />}</>; }

function InfoCard({ title, value, detail }: { title: string; value: string; detail: string }) { return <section className="card"><h2>{title}</h2><p className="metric">{value}</p><p className="muted">{detail}</p></section>; }

function EvidenceDrawer({ snapshot, onClose }: { snapshot: ResearchSnapshot; onClose: () => void }) { const urls = collectUrls(snapshot.payload); return <aside className="drawer" aria-label={`${snapshot.lane} evidence`} aria-modal="true" role="dialog"><button className="secondary close" onClick={onClose}>Close</button><h2>{snapshot.lane} evidence</h2><pre>{JSON.stringify(snapshot.payload, null, 2)}</pre><h3>Exact links</h3>{urls.length ? <ul>{urls.map((url) => <li key={url}><a href={url} target="_blank" rel="noreferrer">{url}</a></li>)}</ul> : <p>No source URLs are available for this lane yet.</p>}</aside>; }

function Shell({ children }: { children: React.ReactNode }) { return <div className="app-shell"><nav aria-label="Primary navigation"><Link to="/" className="brand">Financial AI <span>Research</span></Link><a href="/docs">API docs</a></nav>{children}<footer>Evidence-first research. Not investment advice.</footer></div>; }
function Status({ status }: { status: string }) { return <span className={`status status-${status}`}>{status}</span>; }
function Loading() { return <p className="loading" role="status">Loading research run…</p>; }
function ErrorNotice({ error }: { error: ApiFailure | null | undefined }) { return <section className="error" role="alert"><strong>We could not complete that request.</strong><p>{error?.message ?? "Try again in a moment."}</p>{error?.correlationId && <small>Reference: {error.correlationId}</small>}</section>; }
function active(status: string | undefined) { return status === "pending" || status === "running"; }
function stringValue(value: Record<string, unknown> | null | undefined, key: string) { const item = value?.[key]; return typeof item === "string" || typeof item === "number" ? String(item) : undefined; }
function freshness(value: Record<string, unknown> | null | undefined) { return stringValue(value, "retrieved_at") ? `Retrieved ${stringValue(value, "retrieved_at")}` : "Freshness unavailable"; }
function summary(items: ResearchSnapshot[], lane: string) { const value = items.find((item) => item.lane === lane)?.payload; return value ? "Available" : "No data"; }
function collectUrls(value: Record<string, unknown> | null): string[] { if (!value) return []; return Object.values(value).flatMap((item) => typeof item === "string" && /^https?:\/\//.test(item) ? [item] : []); }
