import { Navigation } from "./Accessibility";
import { safeExternalUrl } from "./security";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { request } from "./api";

interface Citation { id: string; exact_url: string; provider: string; retrieved_at: string }
interface Cell { normalized_value: number | null; normalized_unit: string | null; evidence: Citation[]; [key: string]: unknown }
interface Result { notice: string; columns: { ticker: string; asset_type?: string; currency?: string; run_id: string | null; as_of?: string | null; limitations: string[]; sections: Record<string, { data: unknown; evidence: Citation[]; comparison: string }> }[];
  metrics: { metric: string; comparable: boolean; reasons: string[]; cells: Record<string, Cell> }[] }
function Sources({ citations }: { citations: Citation[] }) {
  return citations.length ? <ul>{citations.map(c => <li key={c.id}><a href={safeExternalUrl(c.exact_url)} target="_blank" rel="noopener noreferrer">{c.id}</a> · {c.provider} · {c.retrieved_at}</li>)}</ul> : <p>Unverified: exact evidence unavailable.</p>;
}
export function ComparisonPage() {
  const [symbols, setSymbols] = useState("");
  const tickers = symbols.split(",").map(s => s.trim().toUpperCase());
  const valid = tickers.length >= 2 && tickers.length <= 5 && new Set(tickers).size === tickers.length && tickers.every(t => /^[A-Z0-9][A-Z0-9._-]{0,14}$/.test(t));
  const compare = useMutation({ mutationFn: () => request<Result>("/api/v1/comparisons", { method: "POST", body: JSON.stringify({ tickers }) }) });
  const result = compare.data;
  return <div className="app-shell"><Navigation /><main id="main-content" tabIndex={-1}>
    <h1>Compare saved research</h1><form onSubmit={e => { e.preventDefault(); if (valid) compare.mutate(); }}><label>Tickers (2–5, comma-separated)<input value={symbols} maxLength={83} onChange={e => setSymbols(e.target.value)} placeholder="AAPL, MSFT" /></label><button disabled={!valid || compare.isPending}>Compare</button></form>
    <p>Uses saved runs only. No new research or provider requests. Unknown metadata is not inferred.</p>
    {compare.isPending && <p role="status">Comparing saved data…</p>}{compare.error && <p role="alert">{compare.error.message}</p>}
    {result && <><p>{result.notice}</p><div className="form-grid">{result.columns.map(column => <section className="card" key={column.ticker}><h2>{column.ticker}</h2><p>{column.asset_type ?? "Unknown asset type"} · {column.currency ?? "Unknown currency"} · as of {column.as_of ?? "unknown"}</p>{column.run_id && <Link to={`/history/${column.run_id}`}>Open saved {column.ticker} run</Link>}<ul>{column.limitations.map((text, i) => <li key={i}>{text}</li>)}</ul>
      {["decision", "quality"].map(lane => <section key={lane}><h3>{lane === "decision" ? "Scenarios and risks" : "Data quality"}</h3>{column.sections[lane] ? <><p>{column.sections[lane].comparison}</p><Sources citations={column.sections[lane].evidence} /><pre>{JSON.stringify(column.sections[lane].data, null, 2)}</pre></> : <p>Unavailable in saved data.</p>}</section>)}
    </section>)}</div><h2>Normalized metrics and valuation</h2>
      {!result.metrics.length && <p>No structured metrics available for comparison.</p>}
      {result.metrics.map(row => <section className="card" key={row.metric}><h3>{row.metric}</h3><p>{row.comparable ? "Comparable on recorded metadata" : "Incomparable"}</p><ul>{row.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul><div className="table-scroll" tabIndex={0} role="region" aria-label={row.metric + " comparison table"}><table><caption>{row.metric} by ticker</caption><thead><tr>{result.columns.map(c => <th scope="col" key={c.ticker}>{c.ticker}</th>)}</tr></thead><tbody><tr>{result.columns.map(c => { const cell = row.cells[c.ticker]; return <td key={c.ticker}>{cell ? <><p>{cell.normalized_value ?? "Unavailable"} {cell.normalized_unit ?? ""}</p><Sources citations={cell.evidence} /><details><summary>Original value, units and fiscal metadata</summary><pre>{JSON.stringify(cell, null, 2)}</pre></details></> : "Unavailable / not applicable"}</td>; })}</tr></tbody></table></div><details><summary>Read values by ticker</summary>{result.columns.map(c => { const cell = row.cells[c.ticker]; return <section key={c.ticker}><h4>{c.ticker}</h4><p>{cell ? (cell.normalized_value ?? "Unavailable") + " " + (cell.normalized_unit ?? "") : "Unavailable / not applicable"}</p>{cell && <Sources citations={cell.evidence} />}</section>; })}</details></section>)}
    </>}
  </main></div>;
}
