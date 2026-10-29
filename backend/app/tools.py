"""三个检索工具的实现（供 Agent tool_call 与 MCP Server 共用）。

检索为混合双腿：向量（语义主力）+ BM25（精确词补充），RRF 融合。
BM25 腿失败时自动降级为纯向量（wealth-manager 教训：可选扩展不能拖垮主链路）。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from . import config
from .db import get_pool

# ---- 语料分层：与其让模型猜，不如显式声明（工具描述/过滤参数都以这里为准）----
LAYERS = {
    "blog": "项目博客（本项目的设计决策与踩坑）",
    "basics": "通用基础知识（Python/数据库/LLM/Agent 等）",
    "daily": "开源日报（每天 GitHub 趋势项目摘要）",
}
_CN_TZ = timezone(timedelta(hours=8))

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


async def _vector_leg(query: str, top_k: int, layers: list[str] | None = None) -> list[dict]:
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
            WHERE ($3::text[] IS NULL OR d.layer = ANY($3::text[]))
            ORDER BY c.embedding <=> $1::vector
            LIMIT $2
            """,
            _vec_literal(vec),
            top_k,
            layers,
        )
    return [
        {
            "doc_id": r["doc_id"], "title": r["title"], "layer": r["layer"],
            "heading": r["heading"], "score": round(float(r["score"]), 4),
            "content": r["content"],
        }
        for r in rows
    ]


async def _bm25_leg(terms: list[str], top_k: int, layers: list[str] | None = None) -> list[dict]:
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
              AND ($3::text[] IS NULL OR d.layer = ANY($3::text[]))
            ORDER BY score DESC
            LIMIT $2
            """,
            query_str,
            top_k,
            layers,
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


def _normalize_layers(layers: list[str] | str | None) -> tuple[list[str] | None, str | None]:
    """把入参收敛成白名单内的层列表。返回 (layers, error)。

    显式白名单而非自由文本：层是闭集，非法值直接拒绝并回报可选值，
    比"静默忽略"更容易被模型自我纠正。
    """
    if layers is None or layers == "" or layers == []:
        return None, None
    if isinstance(layers, str):
        layers = [x.strip() for x in re.split(r"[,，\s]+", layers) if x.strip()]
    bad = [x for x in layers if x not in LAYERS]
    if bad:
        return None, f"未知层 {bad}，可选值：{list(LAYERS)}"
    return layers, None


def _hit_date(doc_id: str) -> str | None:
    """daily-20261020 → 2026-10-20;其余层返回 None。"""
    m = re.fullmatch(r"daily-(\d{4})(\d{2})(\d{2})", doc_id)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def _decorate(hits: list[dict]) -> list[dict]:
    for h in hits:
        d = _hit_date(h["doc_id"])
        if d:
            h["date"] = d
    return hits


async def search_docs(
    query: str,
    top_k: int | None = None,
    layers: list[str] | str | None = None,
) -> dict:
    """混合检索：向量腿 + BM25 腿 RRF 融合；BM25 失败自动降级纯向量。

    layers 为空 = 在全部三层语料（blog / basics / daily）中检索。
    """
    top_k = top_k or config.TOP_K
    layer_list, layer_error = _normalize_layers(layers)
    if layer_error:
        return {"error": layer_error, "available_layers": LAYERS}

    vector_hits = await _vector_leg(query, top_k, layer_list)

    bm25_hits: list[dict] = []
    bm25_error: str | None = None
    terms = extract_terms(query)
    if terms:
        try:
            bm25_hits = await _bm25_leg(terms, top_k, layer_list)
        except Exception as e:  # noqa: BLE001
            bm25_error = f"{type(e).__name__}: {e}"

    fused = _rrf_fuse(vector_hits, bm25_hits)[:top_k] if bm25_hits else vector_hits
    return {
        "query": query,
        "layers": layer_list or list(LAYERS),
        "retrieval": "hybrid" if bm25_hits else "vector_only",
        "bm25_terms": terms,
        "bm25_error": bm25_error,
        "hits": _decorate(fused),
    }


def _as_int(value, default: int, lo: int, hi: int) -> int:
    """容错取整：模型可能把数字写成字符串，非法值回落默认并夹在区间内。"""
    try:
        v = int(value)
    except (TypeError, ValueError):
        v = default
    return max(lo, min(v, hi))


async def latest_daily(days: int = 7, limit: int = 5) -> dict:
    """按日期倒序列出最近 N 天的开源日报（先看清单，需要细节再 get_document 读全文）。

    日报是"每天新增一篇、标题带日期"的时序语料，纯语义检索常常排不上来；
    问"最近/某天的日报"时用它定位，比 search_docs 稳。
    """
    days = _as_int(days, 7, 1, 60)
    limit = _as_int(limit, 5, 1, 30)
    cutoff = (datetime.now(_CN_TZ).date() - timedelta(days=days - 1)).isoformat()

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT doc_id, title, n_chunks
            FROM documents
            WHERE layer = 'daily'
            ORDER BY doc_id DESC
            """
        )

    picked = []
    for r in rows:
        d = _hit_date(r["doc_id"])
        if d is None or d < cutoff:
            continue
        picked.append(
            {
                "doc_id": r["doc_id"],
                "date": d,
                "title": r["title"],
                "n_chunks": r["n_chunks"],
            }
        )
        if len(picked) >= limit:
            break

    return {
        "today": datetime.now(_CN_TZ).date().isoformat(),
        "window_days": days,
        "total_daily": len(rows),
        "count": len(picked),
        "documents": picked,
        "hint": "读某天全文用 get_document(doc_id)",
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
    """列出语料库中的全部文档（可按层过滤 blog|basics|daily）。"""
    layer_list, layer_error = _normalize_layers(layer)
    if layer_error:
        return {"error": layer_error, "available_layers": LAYERS}
    pool = await get_pool()
    async with pool.acquire() as conn:
        if layer_list:
            rows = await conn.fetch(
                "SELECT doc_id, layer, title, n_chunks FROM documents"
                " WHERE layer = ANY($1::text[]) ORDER BY layer, doc_id",
                layer_list,
            )
        else:
            rows = await conn.fetch(
                "SELECT doc_id, layer, title, n_chunks FROM documents ORDER BY layer, doc_id"
            )
    documents = [
        {
            "doc_id": r["doc_id"],
            "layer": r["layer"],
            "title": r["title"],
            "n_chunks": r["n_chunks"],
        }
        for r in rows
    ]
    for d in documents:
        date = _hit_date(d["doc_id"])
        if date:
            d["date"] = date
    return {
        "total": len(documents),
        "layers": {
            k: sum(1 for d in documents if d["layer"] == k) for k in LAYERS
        },
        "documents": documents,
    }


# ---- 供 LLM tool_call 使用的 schema ----
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_docs",
            "description": (
                "混合检索个人知识库（语义 + BM25）。语料共三层："
                "blog=项目博客（设计决策与踩坑）、basics=通用基础知识、daily=开源日报。"
                "默认三层全查，也可用 layers 限定范围。回答任何知识性问题前应先调用本工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索查询语句"},
                    "top_k": {"type": "integer", "description": "返回条数，默认 5"},
                    "layers": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(LAYERS)},
                        "description": "限定检索层，不传=全部三层",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "latest_daily",
            "description": (
                "列出最近 N 天的开源日报清单（按日期倒序）。"
                "用户问“最近/今天的开源日报”“这几天有什么新项目”时先用它定位，"
                "需要细节再用 get_document 读全文。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "回看天数，默认 7"},
                    "limit": {"type": "integer", "description": "最多返回几篇，默认 5"},
                },
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
                "properties": {"doc_id": {"type": "string", "description": "文档 ID，如 blog-01 / daily-20261029"}},
                "required": ["doc_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_documents",
            "description": (
                "列出语料库全部文档清单，可按层过滤"
                "（blog=项目博客，basics=通用基础知识，daily=开源日报）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {"layer": {"type": "string", "enum": list(LAYERS)}},
            },
        },
    },
]


async def dispatch_tool(name: str, args: dict) -> dict:
    """统一工具入口（agent 与 MCP server 共用）。"""
    if name == "search_docs":
        return await search_docs(args["query"], args.get("top_k"), args.get("layers"))
    if name == "latest_daily":
        return await latest_daily(args.get("days", 7), args.get("limit", 5))
    if name == "get_document":
        return await get_document(args["doc_id"])
    if name == "list_documents":
        return await list_documents(args.get("layer"))
    return {"error": f"未知工具: {name}"}
