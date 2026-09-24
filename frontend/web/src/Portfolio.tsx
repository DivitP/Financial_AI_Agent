import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { request } from "./api";

interface Exposure { weights: Record<string, number>; largest_weight: number; hhi: number; sector_weights: Record<string, number>; factor_loadings: Record<string, { weighted_loading: number; covered_weight: number }>; factor_note: string }
interface Result { before: Exposure; after: Exposure; historical_risk: { available: boolean; reason?: string; [key: string]: unknown }; limitations: string[];
  sources: Record<string, { run_id: string | null; limitation?: string; lanes: Record<string, { retrieved_at: string | null; provider: string | null; evidence: { id: string; exact_url: string }[] }> }> }
export function PortfolioPage() {
  const [holdings, setHoldings] = useState("AAPL, 60\nMSFT, 40");
  const [ticker, setTicker] = useState(""); const [weight, setWeight] = useState("10");
  const [error, setError] = useState("");
  const analysis = useMutation({ mutationFn: (body: unknown) => request<Result>("/api/v1/portfolio-context", { method: "POST", body: JSON.stringify(body) }) });
  function submit() {
    const rows = holdings.trim().split("\n").map(line => { const [ticker, weight] = line.split(","); return { ticker: ticker.trim().toUpperCase(), weight: Number(weight) }; });
    const candidate = { ticker: ticker.trim().toUpperCase(), weight: Number(weight) };
    if (rows.length > 10 || new Set(rows.map(r => r.ticker)).size !== rows.length || Math.abs(rows.reduce((s, r) => s + r.weight, 0) - 100) > .000001 || [...rows, candidate].some(r => !/^[A-Z0-9][A-Z0-9._-]{0,14}$/.test(r.ticker) || !Number.isFinite(r.weight) || r.weight <= 0 || r.weight > 100) || candidate.weight >= 100) {
      setError("Enter 1–10 distinct holdings totaling 100%, and a candidate weight between 0% and 100%."); return;
    }
    setError(""); analysis.mutate({ holdings: rows, candidate });
  }
  return <div className="app-shell"><nav aria-label="Primary navigation"><Link to="/">New research</Link><Link to="/history">Saved research</Link><Link to="/compare">Compare</Link></nav><main>
    <h1>Hypothetical portfolio context</h1><p>Research only. No brokerage connection, order placement or trading execution. Inputs are not saved.</p>
    <form onSubmit={e => { e.preventDefault(); submit(); }}><label>Holdings (one ticker, weight percent per line)<textarea rows={5} maxLength={500} value={holdings} onChange={e => setHoldings(e.target.value)} /></label><label>Candidate ticker<input maxLength={15} value={ticker} onChange={e => setTicker(e.target.value)} /></label><label>Candidate weight percent<input type="number" min="0.01" max="99.99" step="any" value={weight} onChange={e => setWeight(e.target.value)} /></label><p>Existing holdings are reduced proportionally to fund the candidate.</p><button disabled={analysis.isPending}>Analyze hypothetical portfolio</button></form>
    {error && <p role="alert">{error}</p>}{analysis.error && <p role="alert">{analysis.error.message}</p>}{analysis.isPending && <p role="status">Analyzing saved data…</p>}
    {analysis.data && <><h2>Assumptions and limitations</h2><ul>{analysis.data.limitations.map(text => <li key={text}>{text}</li>)}</ul>
      <div className="form-grid">{(["before", "after"] as const).map(side => { const data = analysis.data![side]; return <section className="card" key={side}><h2>{side === "before" ? "Before candidate" : "With candidate"}</h2><p>Largest ticker weight: {(data.largest_weight * 100).toFixed(2)}% · HHI: {data.hhi.toFixed(4)}</p><h3>Weights and sector exposure</h3><pre>{JSON.stringify({ weights: data.weights, sectors: data.sector_weights }, null, 2)}</pre><p>Weights are fractions; 0.39 means 39%. Unknown exposure is not zero.</p><h3>Factor exposure</h3><p>{data.factor_note}</p>{Object.keys(data.factor_loadings).length ? <pre>{JSON.stringify(data.factor_loadings, null, 2)}</pre> : <p>Factor exposure unavailable.</p>}</section>; })}</div>
      <section className="card"><h2>Historical correlations and risk change</h2>{analysis.data.historical_risk.available ? <><p>Volatility and drawdown are fractions. Negative drawdown is loss from a prior peak. Null correlation means undefined.</p><pre>{JSON.stringify(analysis.data.historical_risk, null, 2)}</pre></> : <p>Unavailable: {analysis.data.historical_risk.reason}</p>}</section>
      <h2>Saved sources and freshness</h2>{Object.entries(analysis.data.sources).map(([ticker, source]) => <section key={ticker}><h3>{ticker}</h3>{source.run_id && <Link to={`/history/${source.run_id}`}>Open saved run</Link>}<p>{source.limitation}</p>{Object.entries(source.lanes).map(([lane, meta]) => <div key={lane}><p>{lane} · {meta.provider ?? "unknown provider"} · retrieved {meta.retrieved_at ?? "unknown"}</p>{meta.evidence.length ? meta.evidence.map(e => <p key={e.id}><a href={e.exact_url} target="_blank" rel="noreferrer">{e.id}</a></p>) : <p>Uncited data excluded.</p>}</div>)}</section>)}
    </>}
  </main></div>;
}
