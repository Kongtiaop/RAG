import { Citation, StepInfo, renderMarkdown } from "../api";

export function TraceTimeline({ steps }: { steps: StepInfo[] }) {
  const tools = steps.filter((s) => s.type === "tool");
  if (tools.length === 0) return null;
  return (
    <div className="timeline">
      {tools.map((s, i) => (
        <details key={i} className="tl-step">
          <summary>
            <span className="tl-tool">{s.tool}</span>
            <span className="tl-args">{JSON.stringify(s.args)}</span>
            <span className="tl-latency">{s.latency_ms}ms</span>
          </summary>
          <pre className="tl-result">{s.result_summary}</pre>
        </details>
      ))}
    </div>
  );
}

export function CitationCard({ c, onOpenDoc }: { c: Citation; onOpenDoc: (id: string) => void }) {
  return (
    <details className="cite-card">
      <summary>
        <span className="cite-doc" onClick={() => onOpenDoc(c.doc_id)} title="打开原文">
          {c.doc_id} · {c.title}
        </span>
        <span className="cite-heading">{c.heading}</span>
        {c.score != null && <span className="cite-score">{c.score}</span>}
      </summary>
      <div className="cite-snippet" dangerouslySetInnerHTML={{ __html: renderMarkdown(c.snippet) }} />
    </details>
  );
}
