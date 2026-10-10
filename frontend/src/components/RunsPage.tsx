import { useEffect, useState } from "react";
import { RunDetail, RunSummary, getRun, listRuns, renderMarkdown } from "../api";
import { CitationCard, TraceTimeline } from "./Trace";

interface Props {
  onOpenDoc: (docId: string) => void;
}

export default function RunsPage({ onOpenDoc }: Props) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    listRuns().then(setRuns).catch(console.error);
  }, []);

  const openRun = async (runId: string) => {
    setLoading(true);
    try {
      setDetail(await getRun(runId));
    } finally {
      setLoading(false);
    }
  };

  if (detail) {
    return (
      <div className="reader">
        <button className="back-btn" onClick={() => setDetail(null)}>← 返回列表</button>
        <h1 className="reader-title">{detail.question}</h1>
        <div className="reader-src">
          {detail.started_at.slice(0, 19).replace("T", " ")} · {detail.tool_call_count} 次工具调用 ·{" "}
          {(detail.duration_ms / 1000).toFixed(1)}s · run {detail.run_id.slice(0, 8)}
        </div>

        <TraceTimeline steps={detail.steps} />

        <div className="msg assistant">
          <div className="msg-body" dangerouslySetInnerHTML={{ __html: renderMarkdown(detail.answer) }} />
        </div>

        {detail.citations.length > 0 && (
          <div className="citations">
            {detail.citations.map((c, j) => (
              <CitationCard key={j} c={c} onOpenDoc={onOpenDoc} />
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="reader">
      <h1 className="reader-title">对话历史</h1>
      <div className="reader-src">每轮问答的完整工具链路已落库，可随时回放</div>
      {loading && <div className="hint">加载中…</div>}
      {!loading && runs.length === 0 && <div className="hint">还没有对话记录——去右下角气泡问第一个问题吧。</div>}
      {runs.map((r) => (
        <div key={r.run_id} className="doc-item" onClick={() => openRun(r.run_id)}>
          <div className="doc-title">{r.question}</div>
          <div className="doc-meta">
            {r.started_at.slice(0, 19).replace("T", " ")} · {r.tool_call_count} 次工具 ·{" "}
            {(r.duration_ms / 1000).toFixed(1)}s · {r.run_id.slice(0, 8)}
          </div>
        </div>
      ))}
    </div>
  );
}
