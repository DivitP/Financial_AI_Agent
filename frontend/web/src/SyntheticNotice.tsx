import { ResearchSnapshot } from "./api";

export function SyntheticNotice({ snapshots }: { snapshots: ResearchSnapshot[] }) {
  if (!snapshots.some(snapshot => snapshot.payload?.synthetic === true)) return null;
  return <section className="card" role="note" aria-label="Synthetic data notice">
    <h2>Synthetic sample — invented data</h2>
    <p>All figures and organizations in this sample are fictional. Ticker labels are examples,
      not real company research. Evidence links open local sample records, not SEC filings.
      Do not use these figures for investment decisions.</p>
  </section>;
}
