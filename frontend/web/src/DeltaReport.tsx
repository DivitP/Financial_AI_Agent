import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { request } from "./api";

interface Citation { id: string; exact_url: string; provider: string; retrieved_at: string }
interface Delta { current_run_id: string; previous_run_id: string | null; basis: Record<string, unknown>; limitations: string[]; unchanged: string[];
  changes: { lane: string; old: unknown; new: unknown; old_evidence: Citation[]; new_evidence: Citation[] }[] }
function Sources({ links }: { links: Citation[] }) {
  return <ul>{links.map(link => <li key={link.id}><a href={link.exact_url} target="_blank" rel="noreferrer">{link.id}</a> · {link.provider} · retrieved {link.retrieved_at}</li>)}</ul>;
}
export function DeltaReport() {
  const { runId = "" } = useParams();
  const report = useQuery({ queryKey: ["delta", runId], queryFn: () => request<Delta>(`/api/v1/research-runs/${runId}/delta`), retry: false });
  return <div className="app-shell"><nav aria-label="Primary navigation"><Link to="/">New research</Link><Link to="/history">Saved research</Link><Link to="/watchlists">Watchlists</Link></nav><main>
    <h1>Changes since last run</h1><p>Saved-data comparison only. No providers or models are called.</p>
    {report.isLoading && <p role="status">Comparing saved research…</p>}{report.error && <p role="alert">{report.error.message}</p>}
    {report.data && <><p><Link to={`/history/${runId}`}>Open current saved run</Link>{report.data.previous_run_id && <> · <Link to={`/history/${report.data.previous_run_id}`}>Open previous saved run</Link></>}</p>
      <details><summary>Comparison dates and saved versions</summary><pre>{JSON.stringify(report.data.basis, null, 2)}</pre></details>
      <h2>Limitations</h2><ul>{report.data.limitations.map((text, i) => <li key={i}>{text}</li>)}</ul>
      {!report.data.changes.length && <p>No evidence-backed changes available. This does not mean nothing changed.</p>}
      {report.data.changes.map(change => <section className="card" key={change.lane}><h2>{change.lane === "decision" ? "Thesis risks and scenarios" : change.lane}</h2><p>Saved content changed; compare periods, units and methods before interpreting.</p><h3>Old evidence</h3><Sources links={change.old_evidence} /><pre>{JSON.stringify(change.old, null, 2)}</pre><h3>New evidence</h3><Sources links={change.new_evidence} /><pre>{JSON.stringify(change.new, null, 2)}</pre></section>)}
      {report.data.unchanged.length > 0 && <p>Unchanged saved content: {report.data.unchanged.join(", ")}</p>}
    </>}
  </main></div>;
}
