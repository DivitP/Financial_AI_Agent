import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { request } from "./api";

interface CalendarResult { notice: string; limitations: string[]; events: { id: string; title: string; kind: string; scheduled_at: string; timezone: string; precision: string; date_confidence: string; confidence_basis: string; release_session: string; tickers: string[];
  sources: { ticker: string; run_id: string; evidence: { id: string; exact_url: string; provider: string; retrieved_at: string }[] }[] }[] }
export function CalendarPage() {
  const [filters, setFilters] = useState({ start: new Date().toISOString().slice(0, 10), end: "", watchlist_id: "" });
  const [applied, setApplied] = useState(filters);
  const lists = useQuery({ queryKey: ["watchlists"], queryFn: () => request<{ id: string; name: string }[]>("/api/v1/watchlists") });
  const query = new URLSearchParams(Object.entries(applied).filter(([, value]) => value)).toString();
  const result = useQuery({ queryKey: ["calendar", query], queryFn: () => request<CalendarResult>("/api/v1/calendar?" + query), retry: false });
  return <div className="app-shell"><nav aria-label="Primary navigation"><Link to="/">New research</Link><Link to="/watchlists">Watchlists</Link><Link to="/history">Saved research</Link></nav><main>
    <h1>Catalyst and earnings calendar</h1><p>Saved watchlist events only. No provider requests or automatic research refresh.</p>
    <form onSubmit={e => { e.preventDefault(); setApplied({ ...filters }); }}><div className="form-grid"><label>Watchlist<select value={filters.watchlist_id} onChange={e => setFilters({ ...filters, watchlist_id: e.target.value })}><option value="">All watchlists</option>{lists.data?.map(list => <option key={list.id} value={list.id}>{list.name}</option>)}</select></label><label>Start date<input type="date" required value={filters.start} onChange={e => setFilters({ ...filters, start: e.target.value })} /></label><label>End date (default 90 days)<input type="date" value={filters.end} onChange={e => setFilters({ ...filters, end: e.target.value })} /></label></div><button>Apply filters</button></form>
    {lists.error && <p role="alert">{lists.error.message}</p>}{result.error && <p role="alert">{result.error.message}</p>}{result.isLoading && <p role="status">Loading saved calendar…</p>}
    {result.data && <><p>{result.data.notice}</p>{!result.data.events.length && <p>No cited events in this range. Saved coverage may be incomplete.</p>}
      {result.data.events.map(event => <article className="card" key={event.id}><h2>{event.title}</h2><p>{event.kind} · {event.tickers.join(", ")}</p><p><time dateTime={event.scheduled_at}>{event.scheduled_at}</time> · Timezone: {event.timezone} · Precision: {event.precision}</p><p>Date confidence: {event.date_confidence} · {event.confidence_basis}</p><p>Release session: {event.release_session}</p>
        {event.sources.map((source, i) => <div key={i}><Link to={`/history/${source.run_id}`}>{source.ticker} saved run</Link><ul>{source.evidence.map(e => <li key={e.id}><a href={e.exact_url} target="_blank" rel="noreferrer">{e.provider}: {e.id}</a> · retrieved {e.retrieved_at}</li>)}</ul></div>)}
      </article>)}<details><summary>Coverage limitations ({result.data.limitations.length})</summary><ul>{result.data.limitations.map((text, i) => <li key={i}>{text}</li>)}</ul></details></>}
  </main></div>;
}
