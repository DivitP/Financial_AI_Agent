import { ResearchSnapshot } from "./api";

export function PriceHistory({ snapshots }: { snapshots: ResearchSnapshot[] }) {
  const payload = snapshots.find(s => s.lane === "ohlcv" && s.status === "completed")?.payload;
  const raw = payload?.candles;
  if (!Array.isArray(raw)) return null;
  const candles = raw.filter((c): c is {timestamp: string; close: number} =>
    typeof c?.timestamp === "string" && typeof c?.close === "number" && Number.isFinite(c.close) && c.close > 0);
  if (candles.length < 2) return null;
  const values = candles.slice(-120);
  const low = Math.min(...values.map(c => c.close)), high = Math.max(...values.map(c => c.close));
  const points = values.map((c, i) => `${10 + i * 580 / (values.length - 1)},${190 - (c.close - low) / (high - low || 1) * 180}`).join(" ");
  return <section className="card" aria-label="Historical closing prices"><h2>Historical closing prices</h2>
    <p>Last {values.length} observations · {String(payload?.currency ?? "currency unavailable")} · {String(payload?.adjustment_policy ?? "adjustment unavailable")}</p>
    <svg viewBox="0 0 600 210" role="img" aria-label={`Historical prices from ${values[0].timestamp} to ${values.at(-1)!.timestamp}; range ${low} to ${high}. No future predictions.`}>
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="2" />
    </svg><p>Historical observations only; not a guaranteed future price path.</p>
    <details><summary>Show chart values</summary><table><caption>Historical prices</caption><thead><tr><th scope="col">Timestamp</th><th scope="col">Close</th></tr></thead><tbody>{values.map(c => <tr key={c.timestamp}><td>{c.timestamp}</td><td>{c.close}</td></tr>)}</tbody></table></details>
  </section>;
}
