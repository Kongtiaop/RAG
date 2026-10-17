"""摄取脚本：扫描 INGEST_DIRS 下的 md → 切块 → Embedding → 入库。

增量策略（2026-10-08）：按文件 sha256 判定变化——
  - 内容未变的文档整篇跳过（不重新 embedding）；
  - 变更/新增的文档单篇替换（先删后插，事务内，失败自动回滚）；
  - 磁盘上已删除的文档从库中清除。

护栏（2026-10-17，继承自 pg_prefect 的事故教训）：
  - missing_path：扫描结果为空但库中有文档 → 疑似目录未挂载，拒绝执行；
  - 删除双阈值：stale 占比 > 20% 或数量 > 1000 → 阻断批量删除，
    确认无误可用 --allow-mass-delete 显式放行。

用法：cd backend && python -m app.ingest          # 增量摄取
      python -m app.ingest --full                 # 全量重建
      python -m app.ingest --check                # 只统计，不写库
      python -m app.ingest --allow-mass-delete    # 放行大规模删除
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
import uuid
from pathlib import Path

from . import config
from .chunker import chunk_markdown
from .db import get_pool
from .llm import embed_in_batches

ROOT = Path(__file__).resolve().parents[2]
LAYER_BY_DIR = {"docs/blog": "blog", "docs/basics": "basics"}

# 批量删除护栏阈值（pg_prefect 事故同款默认值）
SYNC_DELETE_MAX_RATIO = 0.2
SYNC_DELETE_MAX_COUNT = 1000


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def collect_documents() -> list[dict]:
    """扫描目录。doc_id 用"层-编号前缀"保证稳定（如 blog-01 / basics-15）。"""
    docs: list[dict] = []
    for rel, layer in LAYER_BY_DIR.items():
        for md in sorted((ROOT / rel).glob("*.md")):
            prefix = md.stem.split("-")[0]
            if not prefix.isalnum():
                prefix = uuid.uuid4().hex[:6]
            content = md.read_text(encoding="utf-8")
            docs.append(
                {
                    "doc_id": f"{layer}-{prefix}",
                    "layer": layer,
                    "title": md.stem,
                    "path": str(md.relative_to(ROOT)),
                    "content": content,
                    "content_hash": _sha256(content),
                }
            )
    return docs


def _vec_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


async def _upsert_doc(conn, d: dict, vectors: list[list[float]] | None) -> None:
    """单篇替换：先删后插（chunks 级联删除）。vectors 为 None 表示重用已有 embedding（不应发生）。"""
    async with conn.transaction():
        await conn.execute("DELETE FROM documents WHERE doc_id = $1", d["doc_id"])
        await conn.execute(
            """INSERT INTO documents (doc_id, layer, title, path, content, content_hash, n_chunks)
               VALUES ($1,$2,$3,$4,$5,$6,$7)""",
            d["doc_id"], d["layer"], d["title"], d["path"], d["content"],
            d["content_hash"], len(d["chunks"]),
        )
        for c, vec in zip(d["chunks"], vectors, strict=True):
            await conn.execute(
                """INSERT INTO chunks (doc_id, seq, heading, content, embedding)
                   VALUES ($1,$2,$3,$4,$5::vector)""",
                d["doc_id"], c.seq, c.heading, c.content, _vec_literal(vec),
            )


async def ingest(
    dry_run: bool = False, full: bool = False, allow_mass_delete: bool = False
) -> None:
    docs = collect_documents()
    for d in docs:
        d["chunks"] = chunk_markdown(d["title"], d["content"])

    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = {
            r["doc_id"]: r["content_hash"]
            for r in await conn.fetch("SELECT doc_id, content_hash FROM documents")
        }

    if full:
        for d in docs:
            existing.pop(d["doc_id"], None)
        to_upsert, unchanged = list(docs), []
    else:
        to_upsert = [d for d in docs if existing.get(d["doc_id"]) != d["content_hash"]]
        unchanged = [d for d in docs if existing.get(d["doc_id"]) == d["content_hash"]]
    stale_ids = [doc_id for doc_id in existing if doc_id not in {d["doc_id"] for d in docs}]

    print(f"扫描 {len(docs)} 篇：{len(unchanged)} 篇未变跳过，{len(to_upsert)} 篇需重灌，"
          f"{len(stale_ids)} 篇已删除待清理")
    for d in to_upsert:
        print(f"  [changed] {d['doc_id']:14s} {len(d['chunks']):3d} chunks  {d['title']}")
    for doc_id in stale_ids:
        print(f"  [deleted] {doc_id}")
    if dry_run:
        return

    # 护栏一（missing_path）：扫描为空但库里有文档 → 疑似目录未挂载，拒绝执行
    if not full and not docs and existing:
        print("护栏触发：扫描结果为空但库中有文档——疑似 INGEST_DIRS 未挂载（missing_path），拒绝执行任何写操作。")
        return

    # 护栏二（批量删除双阈值）：stale 占比/数量超限 → 阻断，需显式放行
    if stale_ids and not full and not allow_mass_delete:
        ratio = len(stale_ids) / len(existing) if existing else 0.0
        if ratio > SYNC_DELETE_MAX_RATIO or len(stale_ids) > SYNC_DELETE_MAX_COUNT:
            print(f"删除护栏触发：stale {len(stale_ids)} 篇占库 {ratio:.0%}，超过阈值"
                  f"（{SYNC_DELETE_MAX_RATIO:.0%} / {SYNC_DELETE_MAX_COUNT} 条），已阻断。"
                  "确认无误可用 --allow-mass-delete 放行。")
            stale_ids = []

    if to_upsert:
        all_texts = [
            f"{d['title']} > {c.heading}\n{c.content}" for d in to_upsert for c in d["chunks"]
        ]
        print(f"向量化 {len(all_texts)} 个 chunk（{config.EMBEDDING_MODEL}）…")
        vectors = await embed_in_batches(all_texts)

        conn = await pool.acquire()
        try:
            idx = 0
            for d in to_upsert:
                await _upsert_doc(conn, d, vectors[idx : idx + len(d["chunks"])])
                idx += len(d["chunks"])
        finally:
            await pool.release(conn)

    if stale_ids:
        conn = await pool.acquire()
        try:
            for doc_id in stale_ids:
                await conn.execute("DELETE FROM documents WHERE doc_id = $1", doc_id)
        finally:
            await pool.release(conn)

    print(f"完成：重灌 {len(to_upsert)} 篇 / 清理 {len(stale_ids)} 篇 / 跳过 {len(unchanged)} 篇")


if __name__ == "__main__":
    asyncio.run(
        ingest(
            dry_run="--check" in sys.argv,
            full="--full" in sys.argv,
            allow_mass_delete="--allow-mass-delete" in sys.argv,
        )
    )
