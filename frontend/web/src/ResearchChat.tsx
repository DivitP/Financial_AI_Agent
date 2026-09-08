import { FormEvent, useEffect, useState } from "react";

type Citation = { url: string; evidence_id: string; section: string; excerpt: string; published_at: string };
type Claim = { text: string; citation: Citation };
type Turn = { id: number; question: string; answer: { status: string; message: string; claims: Claim[] } };

export function ResearchChat({ runId }: { runId: string }) {
  const [history, setHistory] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [pending, setPending] = useState(false);
  const [partial, setPartial] = useState<Claim[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    fetch(`/api/v1/research-runs/${runId}/qa`, { signal: controller.signal })
      .then(async response => { if (!response.ok) throw Error(); return response.json(); })
      .then(data => { if (Array.isArray(data)) setHistory(current => [...data, ...current.filter(turn => !data.some(saved => saved.id === turn.id))]); })
      .catch(() => { if (!controller.signal.aborted) setError("Conversation history is unavailable."); });
    return () => controller.abort();
  }, [runId]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (pending || question.trim().length < 3) return;
    setPending(true); setPartial([]); setError("");
    try {
      const response = await fetch(`/api/v1/research-runs/${runId}/qa`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question }),
      });
      if (!response.ok || !response.body) throw Error("The answer could not be verified or the service is unavailable.");
      const reader = response.body.getReader(); const decoder = new TextDecoder();
      let buffer = ""; let complete = false;
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        let boundary;
        while ((boundary = buffer.indexOf("\n\n")) >= 0) {
          const frame = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
          const data = frame.split("\n").find(line => line.startsWith("data: "))?.slice(6);
          if (!data) continue;
          if (frame.startsWith("event: claim")) setPartial(items => [...items, JSON.parse(data) as Claim]);
          if (frame.startsWith("event: complete")) {
            const turn = JSON.parse(data) as Turn;
            setHistory(items => [...items.filter(item => item.id !== turn.id), turn]);
            setPartial([]); setQuestion(""); complete = true;
          }
        }
        if (done) break;
      }
      if (!complete) throw Error("Answer stream was interrupted. Reload to recover saved history.");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Question failed."); setPartial([]); }
    finally { setPending(false); }
  }
  return <section className="card" aria-label="Research chat">
    <h2>Ask about this research</h2>
    <div className="actions">{["What are the revenue risks?", "What changed in management guidance?"].map(text =>
      <button className="secondary" key={text} disabled={pending} onClick={() => setQuestion(text)}>{text}</button>)}</div>
    {history.map(turn => <article key={turn.id}><h3>{turn.question}</h3><p>{turn.answer.message}</p>
      {turn.answer.claims.map((claim, i) => <CitedClaim key={i} claim={claim} />)}</article>)}
    <div aria-live="polite">{partial.map((claim, i) => <CitedClaim key={i} claim={claim} />)}{pending && <p>Checking evidence…</p>}</div>
    {error && <p role="alert">{error}</p>}
    <form onSubmit={submit}><label>Research question<textarea value={question} maxLength={1000} onChange={e => setQuestion(e.target.value)} disabled={pending} /></label>
      <button disabled={pending || question.trim().length < 3}>Ask question</button></form>
  </section>;
}

function CitedClaim({ claim }: { claim: Claim }) {
  const [open, setOpen] = useState(false);
  const source = claim.citation;
  return <div><blockquote>{claim.text}</blockquote><span onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
    <button className="secondary" aria-expanded={open} onFocus={() => setOpen(true)} onClick={() => setOpen(!open)}>Source: {source.section}</button>
    {open && <aside><p>{source.excerpt}</p><small>{source.published_at} · {source.evidence_id}</small><p>
      {/^https?:\/\//i.test(source.url) && <a href={source.url} target="_blank" rel="noopener noreferrer">Open exact source</a>}</p></aside>}
  </span></div>;
}
