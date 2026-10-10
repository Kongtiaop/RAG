import { useEffect, useRef, useState } from "react";
import {
  ChatMessage, RunDetail, RunSummary, StepInfo,
  getRun, listRuns, renderMarkdown, streamChat,
} from "../api";
import { CitationCard, TraceTimeline } from "./Trace";

interface Props {
  onOpenDoc: (docId: string) => void;
}

const TYPEWRITER_TICK_MS = 30;     // 打字机节拍
const TYPEWRITER_CHARS_PER_TICK = 5; // 每拍吐 5 字 ≈ 166 字/秒（可调）

export default function Bubble({ onOpenDoc }: Props) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"chat" | "history">("chat");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState<StepInfo[]>([]);
  const [streamText, setStreamText] = useState("");   // 打字机当前显示
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [runDetail, setRunDetail] = useState<RunDetail | null>(null);
  const [runsLoading, setRunsLoading] = useState(false);
  const [seedHistory, setSeedHistory] = useState<{ role: string; content: string }[]>([]);
  const tokenBuf = useRef("");                        // 已到未吐的 token 缓冲
  const displayedRef = useRef("");                    // 已吐出的完整文本（避免闭包读旧 state）
  const typingRef = useRef(false);
  const listRef = useRef<HTMLDivElement>(null);

  const scrollBottom = () =>
    requestAnimationFrame(() => listRef.current?.scrollTo(0, listRef.current.scrollHeight));

  const openHistory = () => {
    setMode("history");
    setRunsLoading(true);
    listRuns().then(setRuns).catch(console.error).finally(() => setRunsLoading(false));
  };

  const openRun = (runId: string) => {
    setRunsLoading(true);
    getRun(runId)
      .then(setRunDetail)
      .catch(console.error)
      .finally(() => setRunsLoading(false));
  };

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
      // 多轮：历史种子（从回放载入）+ 已完成的问答（最多 3 轮）
      const history = [
        ...seedHistory,
        ...messages
          .filter((m) => !m.running && m.text)
          .map((m) => ({ role: m.role, content: m.text })),
      ].slice(-6);
      const res = await streamChat(
        q,
        history,
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
          <div className="bubble-head">
            <button
              className={`head-tab ${mode === "chat" ? "active" : ""}`}
              onClick={() => setMode("chat")}
            >
              对话
            </button>
            <button
              className={`head-tab ${mode === "history" ? "active" : ""}`}
              onClick={openHistory}
            >
              历史
            </button>
            <span className="head-note">流式回答 · 链路全程可见</span>
          </div>

          {mode === "chat" ? (
            <>
              <div className="bubble-list" ref={listRef}>
                {seedHistory.length > 0 && (
                  <div className="seed-banner">
                    📎 已载入历史对话「{seedHistory[0].content.slice(0, 16)}…」为上下文
                    <button className="seed-clear" onClick={() => setSeedHistory([])}>×</button>
                  </div>
                )}
                {messages.length === 0 && seedHistory.length === 0 && (
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
            </>
          ) : (
            <div className="bubble-list">
              {runsLoading && <div className="hint">加载中…</div>}
              {!runsLoading && runDetail && (
                <>
                  <button className="back-btn" onClick={() => setRunDetail(null)}>← 返回历史列表</button>
                  <div className="msg user">
                    <div className="msg-body">{runDetail.question}</div>
                  </div>
                  <TraceTimeline steps={runDetail.steps} />
                  <div className="msg assistant">
                    <div className="msg-body" dangerouslySetInnerHTML={{ __html: renderMarkdown(runDetail.answer) }} />
                  </div>
                  {runDetail.citations.length > 0 && (
                    <div className="citations">
                      {runDetail.citations.map((c, j) => (
                        <CitationCard key={j} c={c} onOpenDoc={onOpenDoc} />
                      ))}
                    </div>
                  )}
                  <button
                    className="continue-btn"
                    onClick={() => {
                      // 把这轮问答作为上下文种子，回到对话模式继续追问
                      setSeedHistory([
                        { role: "user", content: runDetail.question },
                        { role: "assistant", content: runDetail.answer },
                      ]);
                      setRunDetail(null);
                      setMode("chat");
                    }}
                  >
                    💬 以此为上下文继续提问
                  </button>
                </>
              )}
              {!runsLoading && !runDetail && runs.length === 0 && (
                <div className="hint">还没有对话记录。</div>
              )}
              {!runsLoading && !runDetail &&
                runs.map((r) => (
                  <div key={r.run_id} className="doc-item" onClick={() => openRun(r.run_id)}>
                    <div className="doc-title">{r.question}</div>
                    <div className="doc-meta">
                      {r.started_at.slice(0, 19).replace("T", " ")} · {r.tool_call_count} 次工具 ·{" "}
                      {(r.duration_ms / 1000).toFixed(1)}s · {r.run_id.slice(0, 8)}
                    </div>
                  </div>
                ))}
            </div>
          )}
        </div>
      )}
    </>
  );
}
