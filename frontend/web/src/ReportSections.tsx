import { useState } from "react";
import { ResearchReport } from "./api";
import { safeExternalUrl } from "./security";
import { ResearchModeNotice } from "./ResearchModeNotice";

/** Bound DOM work, without changing the saved report, evidence, or exports. */
export function ReportSections({ report }: { report: ResearchReport }) {
  const [sectionIndex, setSection] = useState(0);
  const [page, setPage] = useState(0);
  const section = report.sections[Math.min(sectionIndex, report.sections.length - 1)];
  if (!section) return <p>No detailed sections in this report.</p>;
  const start = page * 25;
  return <>
    <ResearchModeNotice mode={report.research_mode} />
    <label>Report section<select value={sectionIndex} onChange={e => { setSection(Number(e.target.value)); setPage(0); }}>{report.sections.map((item, i) => <option key={i} value={i}>{item.title}</option>)}</select></label>
    <section aria-label={section.title}><h3>{section.title}</h3>
      <p role="status">Showing findings {section.findings.length ? start + 1 : 0}–{Math.min(start + 25, section.findings.length)} of {section.findings.length}</p>
      {section.findings.slice(start, start + 25).map((finding, i) => <article key={start + i}><p>{finding.summary}</p>{finding.limitations?.map((text, j) => <p key={j}>Limitation: {text}</p>)}<ul>{finding.evidence_ids.map(id => <li key={id}><a href={safeExternalUrl(report.evidence_links[id])} target="_blank" rel="noopener noreferrer">{id}</a></li>)}</ul></article>)}
      <div className="actions"><button className="secondary" disabled={!page} onClick={() => setPage(page - 1)}>Previous findings</button><button className="secondary" disabled={start + 25 >= section.findings.length} onClick={() => setPage(page + 1)}>Next findings</button></div>
    </section>
  </>;
}
