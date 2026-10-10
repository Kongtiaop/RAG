// 类型与 API 封装
import { marked } from "marked";

export interface DocSummary {
  doc_id: string;
  layer: string;
  title: string;
  n_chunks: number;
}

export interface DocFull {
  doc_id: string;
  layer: string;
  title: string;
  path: string;
  content: string;
}

export interface Citation {
  doc_id: string;
  title: string;
  heading: string;
  score: number | null;
  snippet: string;
}

export interface StepInfo {
  step: number;
  type: "tool" | "final";
  tool?: string;
  args?: Record<string, unknown>;
  result_summary?: string;
  latency_ms?: number;
}

export interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  steps: StepInfo[];
  citations: Citation[];
  running: boolean;
}

export async function listDocs(layer: string | null): Promise<DocSummary[]> {
  const q = layer ? `?layer=${layer}` : "";
  const r = await fetch(`/api/documents${q}`);
  const d = await r.json();
  return d.documents;
}

export async function getDoc(docId: string): Promise<DocFull> {
  const r = await fetch(`/api/documents/${docId}`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export interface RunSummary {
  run_id: string;
  question: string;
  tool_call_count: number;
  duration_ms: number;
  started_at: string;
}

export interface RunDetail extends RunSummary {
  answer: string;
  citations: Citation[];
  steps: StepInfo[];
}

export async function listRuns(limit = 30): Promise<RunSummary[]> {
  const r = await fetch(`/api/runs?limit=${limit}`);
  return r.json();
}

export async function getRun(runId: string): Promise<RunDetail> {
  const r = await fetch(`/api/runs/${runId}`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

/** POST /chat 并解析 SSE 流：onStep 工具步骤、onToken 回答增量；resolve 于 answer 事件。 */
export async function streamChat(
  question: string,
  history: { role: string; content: string }[],
  onStep: (s: StepInfo) => void,
  onToken: (text: string) => void
): Promise<{ run_id: string; citations: Citation[]; duration_ms: number; truncated: boolean }> {
  const resp = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, history }),
  });
  if (!resp.body) throw new Error("no stream body");

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let final = { run_id: "", citations: [] as Citation[], duration_ms: 0, truncated: false };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const evLine = block.split("\n").find((l) => l.startsWith("event:"));
      const dataLine = block.split("\n").find((l) => l.startsWith("data:"));
      if (!evLine || !dataLine) continue;
      const event = evLine.slice(6).trim();
      const data = JSON.parse(dataLine.slice(5));
      if (event === "step") onStep(data as StepInfo);
      if (event === "token") onToken(data.text);
      if (event === "answer") final = data;
    }
  }
  return final;
}

export function renderMarkdown(md: string): string {
  // 语料为自产 markdown（blog/basics 均为本项目生成），marked 直出
  return marked.parse(md, { async: false }) as string;
}
