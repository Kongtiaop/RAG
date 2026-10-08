import { useEffect, useRef, useState } from "react";
import { Citation, ChatMessage, StepInfo, renderMarkdown, streamChat } from "../api";

interface Props {
  onOpenDoc: (docId: string) => void;
}

const TYPEWRITER_TICK_MS = 30;     // 打字机节拍
const TYPEWRITER_CHARS_PER_TICK = 5; // 每拍吐 5 字 ≈ 166 字/秒（可调）

export default function Bubble({ onOpenDoc }: Props) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState<StepInfo[]>([]);
  const [streamText, setStreamText] = useState("");   // 打字机当前显示
  const tokenBuf = useRef("");                        // 已到未吐的 token 缓冲
  const displayedRef = useRef("");                    // 已吐出的完整文本（避免闭包读旧 state）
  const typingRef = useRef(false);
  const listRef = useRef<HTMLDivElement>(null);

  const scrollBottom = () =>
    requestAnimationFrame(() => listRef.current?.scrollTo(0, listRef.current.scrollHeight));

  // 打字机：每拍从缓冲搬若干字到显示区；缓冲有积压就持续吐，吐完自然停拍
  useEffect(() => {
    const timer = setInterval(() => {
      if (!typingRef.current) return;
      const buf = tokenBuf.current;
      if (!buf) return;
      const take = Math.min(TYPEWRITER_CHARS_PER_TICK, buf.length);
      displayedRef.current += buf.slice(0, take);
      setStreamText(displayedRef.current);
      tokenBuf.current = buf.slice(take);
      scrollBottom();
    }, TYPEWRITER_TICK_MS);
    return () => clearInterval(timer);
  }, []);

  const send = async () => {
    const q = input.trim();
    if (!q || messages.some((m) => m.running)) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", text: q } as ChatMessage, { role: "assistant", text: "", steps: [], citations: [], running: true }]);
    setThinking([]);
    setStreamText("");
    displayedRef.current = "";
    tokenBuf.current = "";
    typingRef.current = true;
    scrollBottom();
    try {
      const res = await streamChat(
        q,
        (s: StepInfo) => {
          setThinking((t) => [...t, s]);
          scrollBottom();
        },
        (text: string) => {
          tokenBuf.current += text;
        }
      );
      // 收尾：清空缓冲与打字机区，把完整文本定稿为正式消息
      tokenBuf.current = "";
      typingRef.current = false;
      const full = displayedRef.current;
      setStreamText("");
      setMessages((m) => {
        const copy = [...m];
        copy[copy.length - 1] = {
          role: "assistant",
          text: full,
          steps: [],
          citations: res.citations,
          running: false,
        };
        return copy;
      });
    } catch (e) {
      typingRef.current = false;
      setMessages((m) => {
        const copy = [...m];
        copy[copy.length - 1] = { role: "assistant", text: `出错了：${String(e)}`, steps: [], citations: [], running: false };
        return copy;
      });
    } finally {
      setThinking([]);
      scrollBottom();
    }
  };

  return (
    <>
      <button className="bubble-fab" onClick={() => setOpen((o) => !o)} title="向知识库提问">
        {open ? "×" : "问"}
      </button>

      {open && (
        <div className="bubble-panel">
          <div className="bubble-head">知识库助手 · 检索链路全程可见 · 流式回答</div>
          <div className="bubble-list" ref={listRef}>
            {messages.length === 0 && (
              <div className="hint">试试：「什么是受限 ReAct？」「MCP 有哪几种传输方式？」</div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`msg ${m.role}`}>
                {m.role === "assistant" ? (
                  <>
                    <TraceTimeline steps={m.steps} />
                    {m.text && (
                      <div className="msg-body" dangerouslySetInnerHTML={{ __html: renderMarkdown(m.text) }} />
                    )}
                    {m.citations.length > 0 && (
                      <div className="citations">
                        {m.citations.map((c, j) => (
                          <CitationCard key={j} c={c} onOpenDoc={onOpenDoc} />
                        ))}
                      </div>
                    )}
                  </>
                ) : (
                  <div className="msg-body">{m.text}</div>
                )}
              </div>
            ))}
            {thinking.length > 0 && (
              <div className="msg assistant">
                <div className="thinking-tag">检索中…</div>
                <TraceTimeline steps={thinking} />
              </div>
            )}
            {streamText && (
              <div className="msg assistant">
                <div
                  className="msg-body streaming"
                  dangerouslySetInnerHTML={{ __html: renderMarkdown(streamText) }}
                />
              </div>
            )}
          </div>
          <div className="bubble-input">
            <input
              value={input}
              placeholder="向知识库提问…"
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
            />
            <button onClick={send}>发送</button>
          </div>
        </div>
      )}
    </>
  );
}

function TraceTimeline({ steps }: { steps: StepInfo[] }) {
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

function CitationCard({ c, onOpenDoc }: { c: Citation; onOpenDoc: (id: string) => void }) {
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
