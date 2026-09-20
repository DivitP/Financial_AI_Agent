import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { request } from "./api";

interface List { id: string; name: string }
interface Item { ticker: string; notes: string; tags: string[]; latest_run: { id: string; status: string; requested_at: string } | null;
  freshness: { lane: string; state: string; status: string; retrieved_at: string | null }[];
  upcoming_events: { kind: string; scheduled_at: string; release_session: string; source_url: string | null; evidence_ids: string[]; retrieved_at: string | null }[] }
interface Detail extends List { items: Item[] }
const base = "/api/v1/watchlists";
const write = (path: string, method: string, body?: unknown) => request(path, { method, ...(body ? { body: JSON.stringify(body) } : {}) });

export function WatchlistsPage() {
  const client = useQueryClient(); const [selected, setSelected] = useState(""); const [name, setName] = useState("");
  const lists = useQuery({ queryKey: ["watchlists"], queryFn: () => request<List[]>(base), staleTime: 60_000 });
  const create = useMutation({ mutationFn: () => request<List>(base, { method: "POST", body: JSON.stringify({ name }) }), onSuccess: list => { setName(""); setSelected(list.id); client.invalidateQueries({ queryKey: ["watchlists"] }); } });
  return <div className="app-shell"><nav aria-label="Primary navigation"><Link to="/">New research</Link><Link to="/history">Saved research</Link><Link to="/watchlists">Watchlists</Link></nav><main>
    <h1>Watchlists</h1><p>Saved data only. Adding or opening tickers does not start research or contact providers.</p>
    <form onSubmit={e => { e.preventDefault(); create.mutate(); }}><label>New watchlist name<input value={name} onChange={e => setName(e.target.value)} required maxLength={80} /></label><button disabled={!name.trim() || create.isPending}>Create watchlist</button></form>
    {create.error && <p role="alert">{create.error.message}</p>}{lists.error && <p role="alert">{lists.error.message}</p>}{lists.isLoading && <p role="status">Loading watchlists…</p>}
    {lists.data?.length === 0 && <p>No watchlists yet.</p>}
    <label>Choose watchlist<select value={selected} onChange={e => setSelected(e.target.value)}><option value="">Select a watchlist</option>{lists.data?.map(list => <option key={list.id} value={list.id}>{list.name}</option>)}</select></label>
    {selected && <WatchlistDetail key={selected} id={selected} onDeleted={() => setSelected("")} />}
  </main><footer>Research and education, not investment advice.</footer></div>;
}

function WatchlistDetail({ id, onDeleted }: { id: string; onDeleted: () => void }) {
  const client = useQueryClient(); const [name, setName] = useState<string | null>(null); const [ticker, setTicker] = useState("");
  const [notes, setNotes] = useState(""); const [tags, setTags] = useState("");
  const detail = useQuery({ queryKey: ["watchlists", id], queryFn: () => request<Detail>(base + "/" + id), staleTime: 60_000 });
  const change = useMutation({ mutationFn: ({ path = "", method, body }: { path?: string; method: string; body?: unknown }) => write(base + "/" + id + path, method, body), onSuccess: (_, args) => { client.invalidateQueries({ queryKey: ["watchlists"] }); if (args.method === "DELETE" && !args.path) onDeleted(); } });
  if (detail.error) return <p role="alert">{detail.error.message}</p>;
  if (!detail.data) return <p role="status">Loading saved data…</p>;
  return <section><h2>{detail.data.name}</h2>
    <form onSubmit={e => { e.preventDefault(); change.mutate({ method: "PATCH", body: { name: name ?? detail.data.name } }); }}><label>Watchlist name<input required maxLength={80} value={name ?? detail.data.name} onChange={e => setName(e.target.value)} /></label><button disabled={change.isPending}>Rename watchlist</button></form>
    <button className="secondary" disabled={change.isPending} onClick={() => { if (window.confirm("Delete this watchlist and its notes? Research runs will be kept.")) change.mutate({ method: "DELETE" }); }}>Delete watchlist</button>
    <form className="card" onSubmit={e => { e.preventDefault(); change.mutate({ path: "/items", method: "PUT", body: { ticker, notes, tags: tags.split(",").map(t => t.trim()).filter(Boolean) } }); }}>
      <h3>Add or edit ticker</h3><label>Ticker<input required maxLength={15} pattern="[A-Za-z0-9][A-Za-z0-9._-]{0,14}" value={ticker} onChange={e => setTicker(e.target.value.toUpperCase())} /></label>
      <label>Ticker notes<textarea maxLength={2000} value={notes} onChange={e => setNotes(e.target.value)} /></label>
      <label>Tags (comma-separated, up to 20)<input value={tags} maxLength={819} onChange={e => setTags(e.target.value)} /></label><p>Saving an existing ticker replaces its notes and tags in this list only.</p>
      <button disabled={change.isPending || !ticker}>Save ticker</button></form>
    {change.error && <p role="alert">{change.error.message}</p>}
    <p>“Recent” means retrieved within 24 hours, not real-time or complete. Failed lanes remain flagged. Upcoming dates are saved estimates, not a live calendar.</p>
    {detail.data.items.length === 0 && <p>This watchlist has no tickers.</p>}
    {detail.data.items.map(item => <article className="card" key={item.ticker}><h3>{item.ticker}</h3><p>{item.notes || "No notes"}</p><p>Tags: {item.tags.join(", ") || "None"}</p>
      <button onClick={() => { setTicker(item.ticker); setNotes(item.notes); setTags(item.tags.join(", ")); }}>Edit {item.ticker}</button>
      <button disabled={change.isPending} onClick={() => { if (window.confirm("Remove " + item.ticker + " and its notes from this list?")) change.mutate({ path: "/items/" + encodeURIComponent(item.ticker), method: "DELETE" }); }}>Remove {item.ticker}</button>
      {item.latest_run ? <p>Latest research: {item.latest_run.status} · {item.latest_run.requested_at} · <Link to={`/history/${item.latest_run.id}`}>Open saved {item.ticker} research</Link></p> : <p>No saved research. Symbol has not been resolved.</p>}
      <h4>Data freshness</h4>{item.freshness.length ? <ul>{item.freshness.map(f => <li key={f.lane}>{f.lane}: {f.status}, {f.state} · retrieved {f.retrieved_at ?? "unknown"}</li>)}</ul> : <p>Freshness unknown — no saved observations.</p>}
      <h4>Upcoming events</h4>{item.upcoming_events.length ? <ul>{item.upcoming_events.map((event, i) => <li key={i}>{event.kind}: {event.scheduled_at} · {event.release_session} · retrieved {event.retrieved_at ?? "unknown"} · {event.evidence_ids.length ? "Evidence: " + event.evidence_ids.join(", ") : "Evidence unavailable"}
        {event.source_url && /^https?:\/\//i.test(event.source_url) && <> · <a href={event.source_url} target="_blank" rel="noreferrer">Saved source</a></>}</li>)}</ul> : <p>No upcoming events in saved data; coverage may be incomplete.</p>}
    </article>)}
  </section>;
}
