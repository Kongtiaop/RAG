import { useEffect, useState } from "react";
import { DocFull, DocSummary, listDocs, getDoc, renderMarkdown } from "./api";
import Bubble from "./components/Bubble";

export default function App() {
  const [layer, setLayer] = useState<string>("blog");
  const [docs, setDocs] = useState<DocSummary[]>([]);
  const [current, setCurrent] = useState<DocFull | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    listDocs(layer).then(setDocs).catch(console.error);
  }, [layer]);

  const openDoc = async (docId: string) => {
    setLoading(true);
    try {
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
          {["blog", "basics"].map((l) => (
            <button
              key={l}
              className={`tab ${layer === l ? "active" : ""}`}
              onClick={() => setLayer(l)}
            >
              {l === "blog" ? "项目博客" : "基础知识"}
            </button>
          ))}
        </div>
      </header>

      <div className="body">
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
              ← 从左侧选择一篇文章阅读；右下角气泡可直接向知识库提问。
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
      </div>

      <Bubble onOpenDoc={openDoc} />
    </div>
  );
}
