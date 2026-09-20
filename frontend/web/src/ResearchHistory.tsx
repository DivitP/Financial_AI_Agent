import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { researchApi } from "./api";

function Frame({ children }: { children: React.ReactNode }) {
  return <div className="app-shell"><nav aria-label="Primary navigation"><Link to="/">New research</Link><Link to="/history">Saved research</Link><Link to="/watchlists">Watchlists</Link></nav><main>{children}</main><footer>Saved research, not current investment advice.</footer></div>;
}

export function HistoryPage() {
  const [q, setQ] = useState(""); const [status, setStatus] = useState(""); const [archive, setArchive] = useState("active"); const [page, setPage] = useState(0);
  const filters = { q, archive, limit: "20", offset: String(page * 20), ...(status ? { status } : {}) };
  const history = useQuery({ queryKey: ["history", filters], queryFn: () => researchApi.history(filters) });
  return <Frame><h1>Saved research</h1><p>Reopen stored report versions without refreshing market data.</p>
    <div className="form-grid"><label>Search ticker or name<input maxLength={80} value={q} onChange={e => { setQ(e.target.value); setPage(0); }} /></label>
      <label>Run status<select value={status} onChange={e => { setStatus(e.target.value); setPage(0); }}><option value="">All statuses</option>{["pending", "running", "completed", "failed", "cancelled"].map(s => <option key={s}>{s}</option>)}</select></label>
      <label>Archive filter<select value={archive} onChange={e => { setArchive(e.target.value); setPage(0); }}><option value="active">Not archived</option><option value="archived">Archived</option><option value="all">All runs</option></select></label></div>
    {history.isLoading && <p role="status">Loading saved runs…</p>}{history.error && <p role="alert">{history.error.message}</p>}
    {history.data?.length === 0 && <p>No matching saved runs.</p>}
    {history.data?.map(run => <article className="card" key={run.id}><h2><Link to={`/history/${run.id}`}>{run.name || run.ticker}</Link></h2><p>{run.ticker} · {run.status} · {run.archived ? "Archived" : "Not archived"}</p><p>Requested {run.requested_at} · {run.report_count} saved report versions</p></article>)}
    <div className="actions"><button disabled={page === 0} onClick={() => setPage(page - 1)}>Previous page</button><button disabled={!history.data || history.data.length < 20} onClick={() => setPage(page + 1)}>Next page</button></div>
  </Frame>;
}

export function SavedRunPage() {
  const { runId = "" } = useParams(); const [params, setParams] = useSearchParams(); const version = params.get("version"); const client = useQueryClient();
  const saved = useQuery({ queryKey: ["saved-history", runId, version], queryFn: () => researchApi.saved(runId, version) });
  const [name, setName] = useState<string | null>(null);
  const change = useMutation({ mutationFn: (fields: { name?: string | null; archived?: boolean }) => researchApi.updateHistory(runId, fields), onSuccess: () => { client.invalidateQueries({ queryKey: ["saved-history", runId] }); client.invalidateQueries({ queryKey: ["history"] }); } });
  const data = saved.data;
  return <Frame>{saved.isLoading && <p role="status">Loading saved version…</p>}{saved.error && <p role="alert">{saved.error.message}</p>}{data && <>
    <h1>{data.run.name || data.run.ticker}</h1><p>{data.run.ticker} · Requested {data.run.requested_at}</p><p role="status">{data.notice}</p>
    <form onSubmit={e => { e.preventDefault(); change.mutate({ name: name ?? data.run.name }); }}><label>Run name<input maxLength={80} value={name ?? data.run.name ?? ""} onChange={e => setName(e.target.value)} /></label><button disabled={change.isPending}>Save name</button></form>
    <button className="secondary" disabled={change.isPending} onClick={() => change.mutate({ archived: !data.run.archived })}>{data.run.archived ? "Restore run" : "Archive run"}</button>{change.error && <p role="alert">{change.error.message}</p>}
    {data.report && <><label>Saved report version<select value={data.report.version} onChange={e => setParams({ version: e.target.value })}>{data.versions.map(v => <option key={v.version} value={v.version}>Version {v.version} · as of {v.as_of}</option>)}</select></label>
      <section className="card"><h2>Decision brief</h2><p>Original as-of: {data.report.as_of}</p><ul>{data.report.decision_brief.map((text, i) => <li key={i}>{text}</li>)}</ul>
        {data.report.sections.map((section, i) => <section key={i}><h3>{section.title}</h3>{section.findings.map((finding, j) => <article key={j}><p>{finding.summary}</p>{finding.limitations?.map((text, k) => <p key={k}>Limitation: {text}</p>)}<ul>{finding.evidence_ids.map(id => { const url = data.report!.evidence_links[id]; return <li key={id}>{/^https?:\/\//i.test(url ?? "") ? <a href={url} target="_blank" rel="noreferrer">{id}</a> : <span>{id} — source link unavailable</span>}</li>; })}</ul></article>)}</section>)}
      </section><p>Source links are the saved URLs; external pages may have changed. Forecast research is not included in this historical snapshot view.</p>
      <details><summary>Full saved report and model configuration</summary><pre>{JSON.stringify(data.report, null, 2)}</pre></details></>}
    {data.snapshots.map(snapshot => <details className="card" key={snapshot.lane}><summary>{snapshot.lane} · {snapshot.status} · saved at report creation</summary><pre>{JSON.stringify(snapshot, null, 2)}</pre></details>)}
  </>}</Frame>;
}
