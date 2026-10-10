import { useEffect, useState } from "react";
import { DocFull, DocSummary, listDocs, getDoc, renderMarkdown } from "./api";
import Bubble from "./components/Bubble";
import RunsPage from "./components/RunsPage";

export default function App() {
  const [view, setView] = useState<"reader" | "runs">("reader");
  const [layer, setLayer] = useState<string>("blog");
  const [docs, setDocs] = useState<DocSummary[]>([]);
  const [current, setCurrent] = useState<DocFull | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (view === "reader") listDocs(layer).then(setDocs).catch(console.error);
  }, [layer, view]);

  const openDoc = async (docId: string) => {
    setLoading(true);
    try {
      setView("reader");
      setCurrent(await getDoc(docId));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">叶先生的知识库</div>
        <div className="tabs">
          <button
            className={`tab ${view === "reader" ? "active" : ""}`}
            onClick={() => setView("reader")}
          >
            文章
          </button>
          <button
            className={`tab ${view === "runs" ? "active" : ""}`}
            onClick={() => setView("runs")}
          >
            对话历史
          </button>
          {view === "reader" &&
            ["blog", "basics"].map((l) => (
              <button
                key={l}
                className={`tab sub ${layer === l ? "active" : ""}`}
                onClick={() => setLayer(l)}
              >
                {l === "blog" ? "项目博客" : "基础知识"}
              </button>
            ))}
        </div>
      </header>

      <div className="body">
        {view === "runs" ? (
          <RunsPage onOpenDoc={openDoc} />
        ) : (
          <>
            <aside className="sidebar">
              {docs.map((d) => (
                <div
                  key={d.doc_id}
                  className={`doc-item ${current?.doc_id === d.doc_id ? "current" : ""}`}
                  onClick={() => openDoc(d.doc_id)}
                >
                  <div className="doc-title">{d.title}</div>
                  <div className="doc-meta">
                    {d.doc_id} · {d.n_chunks} chunks
                  </div>
                </div>
              ))}
            </aside>

            <main className="reader">
              {loading && <div className="hint">加载中…</div>}
              {!loading && !current && (
                <div className="hint">
                  ← 从左侧选择一篇文章阅读；右下角气泡可直接向知识库提问（支持多轮追问）。
                </div>
              )}
              {!loading && current && (
                <>
                  <h1 className="reader-title">{current.title}</h1>
                  <div className="reader-src">来源文件：{current.path}</div>
                  <article
                    className="markdown-body"
                    dangerouslySetInnerHTML={{ __html: renderMarkdown(current.content) }}
                  />
                </>
              )}
            </main>
          </>
        )}
      </div>

      <Bubble onOpenDoc={openDoc} />
    </div>
  );
}
