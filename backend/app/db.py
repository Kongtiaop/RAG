"""数据库连接池与 schema。"""
from __future__ import annotations

import asyncpg

from . import config

_pool: asyncpg.Pool | None = None

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id           SERIAL PRIMARY KEY,
    doc_id       TEXT UNIQUE NOT NULL,          -- 如 blog-01 / basics-15
    layer        TEXT NOT NULL,                 -- blog | basics
    title        TEXT NOT NULL,
    path         TEXT NOT NULL,
    content      TEXT NOT NULL,                 -- 全文 markdown
    content_hash TEXT,                          -- 增量摄取：内容 sha256，未变则跳过
    n_chunks     INT NOT NULL DEFAULT 0,
    ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash TEXT;

CREATE TABLE IF NOT EXISTS chunks (
    id        SERIAL PRIMARY KEY,
    doc_id    TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    seq       INT NOT NULL,
    heading   TEXT NOT NULL DEFAULT '',        -- 章节路径，如 "## 2 / ### 2.3"
    content   TEXT NOT NULL,
    embedding vector(1024) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks (doc_id, seq);
"""

# BM25 索引单独建（pg_search 未就绪时不阻塞主 schema）
# ⚠️ wealth-manager 教训：key_field 指名的列必须写进字段列表（bm25(id, content)），
#    写成 USING bm25(content) WITH (key_field='id') 会导致所有 INSERT 静默失败。
BM25_INDEX = """
CREATE INDEX IF NOT EXISTS idx_chunks_bm25
    ON chunks USING bm25 (id, content) WITH (key_field='id');
"""


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            config.DATABASE_URL, min_size=1, max_size=5
        )
        async with _pool.acquire() as conn:
            await conn.execute(SCHEMA)
            try:
                await conn.execute(BM25_INDEX)
            except Exception as e:  # noqa: BLE001 —— pg_search 未就绪时只降级不阻塞
                print(f"[warn] bm25 index unavailable: {e}")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
