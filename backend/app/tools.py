"""三个检索工具的实现（供 Agent tool_call 与 MCP Server 共用）。

检索为混合双腿：向量（语义主力）+ BM25（精确词补充），RRF 融合。
BM25 腿失败时自动降级为纯向量（wealth-manager 教训：可选扩展不能拖垮主链路）。
"""
from __future__ import annotations

import asyncio
import re

import asyncpg

from . import config
from .db import get_pool

# ---- 中文拆词：jieba cut_for_search（真分词）+ 停用字过滤 ----
# （旧方案为剥停用字+字 bigram；jieba 按词切分精度更高，2026-10-08 用户拍板换 jieba）
_STOPWORDS = set(
    "的了着吗呢吧啊呀哦把和与及或是在对于通过使用可以这个那个这些那些我们你们他们她们"
    "什么怎么怎样如何为什么因为所以如果那么还有但是而且并且就是也是都是不是没有"
    "一下一些一种一个这种哪种哪些以及或者例如等等进行实现关于由于因此然后接着最后首先"
)

_TERM_SPLIT = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")


def _cut_chinese(text: str) -> list[str]:
    import jieba

    return [t for t in jieba.cut_for_search(text) if t.strip()]


def extract_terms(query: str) -> list[str]:
    """整句 query → 关键词序列。英文原样小写；中文 jieba 分词后剥停用字。"""
    terms: list[str] = []
    for tok in _TERM_SPLIT.findall(query):
        if not tok.isascii():
            terms.extend(t for t in _cut_chinese(tok) if t not in _STOPWORDS and t.strip())
        else:
            terms.append(tok.lower())
    seen: set[str] = set()
    return [t for t in terms if not (t in seen or seen.add(t))]


def _vec_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


async def _vector_leg(query: str, top_k: int) -> list[dict]:
    from .llm import embed

    vec = (await embed([query]))[0]
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT c.id, c.doc_id, c.heading, c.content,
                   d.title, d.layer,
                   1 - (c.embedding <=> $1::vector) AS score
            FROM chunks c JOIN documents d ON d.doc_id = c.doc_id
            ORDER BY c.embedding <=> $1::vector
            LIMIT $2
            """,
            _vec_literal(vec),
            top_k,
        )
    return [
        {
            "doc_id": r["doc_id"], "title": r["title"], "layer": r["layer"],
            "heading": r["heading"], "score": round(float(r["score"]), 4),
            "content": r["content"],
        }
        for r in rows
    ]


async def _bm25_leg(terms: list[str], top_k: int) -> list[dict]:
    """BM25 关键词腿。独立连接 + 异常上抛由调用方降级（事务隔离教训）。"""
    pool = await get_pool()
    query_str = " ".join(terms)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT c.id, c.doc_id, c.heading, c.content,
                   d.title, d.layer,
                   paradedb.score(c.id) AS score
            FROM chunks c JOIN documents d ON d.doc_id = c.doc_id
            WHERE c.content @@@ $1
            ORDER BY score DESC
            LIMIT $2
            """,
            query_str,
            top_k,
        )
    return [
        {
            "doc_id": r["doc_id"], "title": r["title"], "layer": r["layer"],
            "heading": r["heading"], "score": round(float(r["score"]), 4),
            "content": r["content"],
        }
        for r in rows
    ]


def _rrf_fuse(*legs: list[dict], k: int = 60) -> list[dict]:
    """Reciprocal Rank Fusion：按 chunk 定位（doc_id+seq 内容 hash）融合多路排名。"""
    fused: dict[str, dict] = {}
    scores: dict[str, float] = {}
    for leg in legs:
        for rank, hit in enumerate(leg):
            key = f"{hit['doc_id']}::{hash(hit['content'])}"
            if key not in fused:
                fused[key] = hit
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
    for key in fused:
        fused[key]["rrf_score"] = round(scores[key], 5)
    return sorted(fused.values(), key=lambda h: h["rrf_score"], reverse=True)


async def search_docs(query: str, top_k: int | None = None) -> dict:
    """混合检索：向量腿 + BM25 腿 RRF 融合；BM25 失败自动降级纯向量。"""
    top_k = top_k or config.TOP_K
    vector_hits = await _vector_leg(query, top_k)

    bm25_hits: list[dict] = []
    bm25_error: str | None = None
    terms = extract_terms(query)
    if terms:
        try:
            bm25_hits = await _bm25_leg(terms, top_k)
        except Exception as e:  # noqa: BLE001
            bm25_error = f"{type(e).__name__}: {e}"

    fused = _rrf_fuse(vector_hits, bm25_hits)[:top_k] if bm25_hits else vector_hits
    return {
        "query": query,
        "retrieval": "hybrid" if bm25_hits else "vector_only",
        "bm25_terms": terms,
        "bm25_error": bm25_error,
        "hits": fused,
    }


async def get_document(doc_id: str) -> dict:
    """按 doc_id 取文档全文（markdown）。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT doc_id, layer, title, path, content FROM documents WHERE doc_id = $1",
            doc_id,
        )
    if row is None:
        return {"error": f"doc_id '{doc_id}' 不存在，请先用 list_documents 查看可用文档"}
    return {
        "doc_id": row["doc_id"],
        "layer": row["layer"],
        "title": row["title"],
        "path": row["path"],
        "content": row["content"],
    }


async def list_documents(layer: str | None = None) -> dict:
    """列出语料库中的全部文档（可选按层过滤 blog|basics）。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if layer:
            rows = await conn.fetch(
                "SELECT doc_id, layer, title, n_chunks FROM documents WHERE layer = $1 ORDER BY doc_id",
                layer,
            )
        else:
            rows = await conn.fetch(
                "SELECT doc_id, layer, title, n_chunks FROM documents ORDER BY layer, doc_id"
            )
    return {
        "total": len(rows),
        "documents": [
            {
                "doc_id": r["doc_id"],
                "layer": r["layer"],
                "title": r["title"],
                "n_chunks": r["n_chunks"],
            }
            for r in rows
        ],
    }


# ---- 供 LLM tool_call 使用的 schema ----
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_docs",
            "description": "在技术博客与基础知识库中做语义检索。回答任何知识性问题前应先调用本工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索查询语句"},
                    "top_k": {"type": "integer", "description": "返回条数，默认 5"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_document",
            "description": "按 doc_id 读取某篇文档的完整原文。",
            "parameters": {
                "type": "object",
                "properties": {"doc_id": {"type": "string", "description": "文档 ID，如 blog-01"}},
                "required": ["doc_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_documents",
            "description": "列出语料库全部文档清单，可按层过滤（blog=项目博客，basics=通用基础知识）。",
            "parameters": {
                "type": "object",
                "properties": {"layer": {"type": "string", "enum": ["blog", "basics"]}},
            },
        },
    },
]


async def dispatch_tool(name: str, args: dict) -> dict:
    """统一工具入口（agent 与 MCP server 共用）。"""
    if name == "search_docs":
        return await search_docs(args["query"], args.get("top_k"))
    if name == "get_document":
        return await get_document(args["doc_id"])
    if name == "list_documents":
        return await list_documents(args.get("layer"))
    return {"error": f"未知工具: {name}"}
