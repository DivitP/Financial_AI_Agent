import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ForecastBand, ForecastResponse, researchApi } from "./api";

const numeric = (v: unknown): number | null => {
  if ((typeof v !== "number" && typeof v !== "string") || v === "") return null;
  const n = Number(v); return Number.isFinite(n) ? n : null;
};
const number = (v: unknown) => { const n = numeric(v); return n === null ? "Unavailable" : n.toLocaleString(undefined, { maximumFractionDigits: 3 }); };
const percent = (v: unknown) => { const n = numeric(v); return n === null ? "Unavailable" : `${number(n * 100)}%`; };
function validBand(b: ForecastBand) { if (!b?.close_percentiles) return false; const values = ["5", "25", "50", "75", "95"].map(q => numeric(b.close_percentiles[q])); return values.every((v, i) => v !== null && v > 0 && (i === 0 || v >= values[i - 1]!)); }

export function ForecastPage() {
  const { runId = "" } = useParams(); const [experimental, setExperimental] = useState(false); const client = useQueryClient();
  const query = useQuery({ queryKey: ["forecast", runId, experimental], queryFn: () => researchApi.forecast(runId, experimental), retry: false, refetchInterval: 5000 });
  const execute = useMutation({ mutationFn: () => researchApi.forecast(runId, experimental, true), onSuccess: () => client.invalidateQueries({ queryKey: ["forecast", runId] }) });
  return <main className="app-shell forecast-page"><Link to={`/runs/${runId}`}>← Research overview</Link><h1>Kronos forecast research</h1>
    <p>Sampled scenarios, not guaranteed price targets or investment advice.</p>
    <label className="forecast-opt-in"><input type="checkbox" checked={experimental} onChange={e => setExperimental(e.target.checked)} /> Show experimental research forecasts</label>
    <button className="secondary" disabled={execute.isPending} onClick={() => execute.mutate()}>{execute.isPending ? "Running local forecast…" : "Run or retry forecast"}</button>
    <p className="muted">Requires forecast opt-in when creating the run, enabled local models, and complete market inputs.</p>
    {(query.error || execute.error) && <p role="alert">Forecast unavailable. Other research remains usable.</p>}
    {query.isLoading && <p role="status">Loading forecast…</p>}
    {query.data && <ForecastPanel data={query.data} />}
  </main>;
}

export function ForecastPanel({ data }: { data: ForecastResponse }) {
  const f = data.forecast;
  const bands = f?.summary?.bands ?? [];
  const usable = !!f && (f.summary?.sample_count ?? 0) >= 2 && bands.length === f.candles.length && bands.length > 0 && bands.every((b, i) => validBand(b) && b.session === f.candles[i].session);
  const validation = data.validation;
  return <>
    <section className="card" aria-labelledby="forecast-status"><h2 id="forecast-status">Forecast status: {data.status}</h2><strong>{data.quality === "promoted" ? "Scoped validation passed — uncertainty remains" : "Experimental research — not validated for decisions"}</strong>{data.warning && <p role="status">{data.warning}</p>}
      {!f && <p>No visible forecast. Enable experimental viewing to inspect unvalidated output when available.</p>}
      {f?.warnings?.length ? <ul aria-label="Forecast warnings">{f.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul> : null}
    </section>
    {f && <>
      <section className="card"><h2>Historical candles and forecast distribution</h2>
        <p>Historical OHLC candles end at the cutoff. Shaded bands show sampled 5–95 and 25–75 percentiles; the dashed median is not a price target. Bands are not calibrated confidence intervals.</p>
        {usable ? <FanChart forecast={f} bands={bands} /> : <p role="status">Distribution unavailable or invalid. A single forecast line is not shown.</p>}
        {!f.historical_candles?.length && <p>Historical candlesticks unavailable for this saved forecast.</p>}
      </section>
      <section className="card"><h2>Illustrative terminal scenarios</h2><p>Lower / middle / upper sample outcomes, not assigned bull/base/bear probabilities.</p>
        {usable ? <div className="forecast-scenarios">{[["Lower (5th percentile)", "5"], ["Middle (median)", "50"], ["Upper (95th percentile)", "95"]].map(([label, q]) => <div key={q}><h3>{label}</h3><p>{number(bands[bands.length - 1].close_percentiles[q])} {f.currency}</p></div>)}</div> : <p>Scenario distribution unavailable.</p>}
      </section>
      <section className="card"><h2>Model card</h2><dl className="model-card">{Object.entries({ "Model version": f.model_version, "Data cutoff": f.as_of, "Provider": f.provider, "Currency / price unit": f.currency, "Timezone": f.timezone, "Adjustment policy": f.adjustment_policy, "Device": f.device, "Sample paths": f.summary?.sample_count }).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value ?? "Unavailable"}</dd></div>)}</dl><p>Local model output. Historical validation does not guarantee future performance.</p></section>
    </>}
    <section className="card"><h2>Baseline comparison and backtest metrics</h2>
      <p>Same-window comparisons only. MAE/RMSE use price currency, MASE is a ratio; direction, coverage and drawdown are percentages. Turnover is an equity multiple. Drawdown is measured at fold exits.</p>
      {!validation || !Object.keys(validation.models).length ? <p>No completed baseline comparison is available. No metrics or validation windows have been invented.</p> : <>
        <p>Evaluation: {validation.status} · recorded {validation.created_at}</p>
        <div className="forecast-table" tabIndex={0} role="region" aria-label="Baseline metrics"><table><caption>Persisted out-of-sample comparison</caption><thead><tr>{["Model", "MAE", "RMSE", "MASE", "Direction", "90% band coverage", "Turnover", "Fold-end drawdown"].map(h => <th scope="col" key={h}>{h}</th>)}</tr></thead><tbody>{Object.entries(validation.models).map(([name, model]) => <tr key={name}><th scope="row">{name}</th><td>{number(model.metrics.mae)}</td><td>{number(model.metrics.rmse)}</td><td>{number(model.metrics.mase)}</td><td>{percent(model.metrics.terminal_direction_accuracy)}</td><td>{percent(model.metrics.interval_coverage)}</td><td>{number(model.turnover)}×</td><td>{percent(model.drawdown)}</td></tr>)}</tbody></table></div>
        <details><summary>Backtest windows by model</summary>{Object.entries(validation.models).map(([name, model]) => <section key={name}><h3>{name}</h3><ul>{model.windows.map((w, i) => <li key={i}>Training cutoff {w.as_of}; test {w.sessions[0]} → {w.sessions.at(-1)} ({w.sessions.length} sessions)</li>)}</ul></section>)}</details>
      </>}
      {validation && <ul aria-label="Validation limitations">{[...validation.reasons, ...validation.limitations].map((w, i) => <li key={i}>{w}</li>)}</ul>}
    </section>
  </>;
}

function FanChart({ forecast: f, bands }: { forecast: NonNullable<ForecastResponse["forecast"]>; bands: ForecastBand[] }) {
  const history = (f.historical_candles ?? []).slice(-60);
  const validHistory = history.every(c => [c.open, c.high, c.low, c.close].every(v => numeric(v) !== null && Number(v) > 0));
  if (!validHistory) return <p>Historical data is invalid; chart withheld.</p>;
  const prices = [...history.flatMap(c => [Number(c.high), Number(c.low)]), ...bands.flatMap(b => [Number(b.close_percentiles["5"]), Number(b.close_percentiles["95"])])];
  const lo = Math.min(...prices), hi = Math.max(...prices), span = hi - lo || hi * .02 || 1;
  const y = (v: number) => 250 - (v - lo + span * .1) / (span * 1.2) * 220;
  const count = history.length + bands.length, step = 660 / Math.max(count, 1), x = (i: number) => 75 + (i + .5) * step;
  const bandPath = (low: string, high: string) => [...bands.map((b, i) => `${x(history.length + i)},${y(Number(b.close_percentiles[high]))}`), ...bands.map((b, i) => `${x(history.length + i)},${y(Number(b.close_percentiles[low]))}`).reverse()].join(" ");
  return <>
    <svg className="fan-chart" viewBox="0 0 800 300" role="img" aria-label="Historical candlesticks and uncertain forecast percentile bands, not a guaranteed price target">
      <text x="10" y="23">Price ({f.currency ?? "currency unavailable"})</text>
      {[lo, (lo + hi) / 2, hi].map((v, i) => <g key={i}><line x1="70" x2="745" y1={y(v)} y2={y(v)} stroke="#d1d5db" /><text x="5" y={y(v) - 3}>{number(v)}</text></g>)}
      {history.map((c, i) => <g key={c.session}><title>{c.session}: open {c.open}, high {c.high}, low {c.low}, close {c.close}</title><line x1={x(i)} x2={x(i)} y1={y(Number(c.high))} y2={y(Number(c.low))} stroke="#24364b" /><rect x={x(i) - Math.min(5, step / 3)} width={Math.min(10, step * 2 / 3)} y={Math.min(y(Number(c.open)), y(Number(c.close)))} height={Math.max(1, Math.abs(y(Number(c.open)) - y(Number(c.close))))} fill={Number(c.close) >= Number(c.open) ? "#147d68" : "#b64545"} /></g>)}
      <polygon points={bandPath("5", "95")} fill="#d5ddff" /><polygon points={bandPath("25", "75")} fill="#95a9ed" />
      {bands.length === 1 && <line x1={x(history.length)} x2={x(history.length)} y1={y(Number(bands[0].close_percentiles["5"]))} y2={y(Number(bands[0].close_percentiles["95"]))} stroke="#667bc1" strokeWidth="12" />}
      <polyline points={bands.map((b, i) => `${x(history.length + i)},${y(Number(b.close_percentiles["50"]))}`).join(" ")} fill="none" stroke="#344881" strokeDasharray="5 4" strokeWidth="2" />
      <line x1={75 + history.length * step} x2={75 + history.length * step} y1="25" y2="260" stroke="#374151" strokeDasharray="3 3" />
      <text x="75" y="282">{history[0]?.session ?? "History unavailable"}</text><text x="740" y="282" textAnchor="end">{bands.at(-1)?.session}</text>
    </svg>
    <p className="muted">Vertical divider: forecast begins · light band: 5–95% · dark band: 25–75% · dashed: sampled median.</p>
    <details><summary>Accessible chart values</summary><div className="forecast-table" tabIndex={0} role="region" aria-label="Chart data"><table><caption>Historical OHLC and forecast closing-price percentiles ({f.currency})</caption><thead><tr><th scope="col">Session</th><th scope="col">Type</th><th scope="col">Values</th></tr></thead><tbody>{history.map(c => <tr key={c.session}><th scope="row">{c.session}</th><td>Historical</td><td>O {c.open} H {c.high} L {c.low} C {c.close}</td></tr>)}{bands.map(b => <tr key={b.session}><th scope="row">{b.session}</th><td>Forecast samples</td><td>{["5", "25", "50", "75", "95"].map(q => `${q}th: ${number(b.close_percentiles[q])}`).join(" · ")}</td></tr>)}</tbody></table></div></details>
  </>;
}
