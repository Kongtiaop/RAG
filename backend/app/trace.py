"""Trace 持久化：每轮对话的 run 与逐步工具调用落库（M4 核心）。

守卫不变量（tests/test_trace_guard.py 逐条断言）：
  G1 任何一次 run_agent 必须在 chat_runs 产生一行；
  G2 trace_steps 的 tool 行数 == run.tool_call_count；
  G3 每个 tool 行必须有 tool 名、args、latency_ms；
  G4 每个 run 必须有 type='final' 的收尾行；
  G5 引用列表可空但字段完整（doc_id/title/heading）。
"""
from __future__ import annotations

import json
import uuid

from asyncpg import Pool

from .agent import TraceStep

TRACE_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_runs (
    id              SERIAL PRIMARY KEY,
    run_id          UUID NOT NULL UNIQUE,
    question        TEXT NOT NULL,
    answer          TEXT NOT NULL,
    tool_call_count INT NOT NULL DEFAULT 0,
    citations       JSONB NOT NULL DEFAULT '[]',
    duration_ms     INT NOT NULL DEFAULT 0,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS trace_steps (
    id             SERIAL PRIMARY KEY,
    run_id         UUID NOT NULL REFERENCES chat_runs(run_id) ON DELETE CASCADE,
    step           INT NOT NULL,
    type           TEXT NOT NULL,
    tool           TEXT,
    args           JSONB,
    result_summary TEXT,
    latency_ms     INT
);
CREATE INDEX IF NOT EXISTS idx_trace_steps_run ON trace_steps (run_id, step);
"""


async def save_run(
    pool: Pool, question: str, answer: str, steps: list[TraceStep],
    citations: list[dict], tool_call_count: int, duration_ms: int,
) -> str:
    run_id = str(uuid.uuid4())
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """INSERT INTO chat_runs (run_id, question, answer, tool_call_count, citations, duration_ms)
                   VALUES ($1,$2,$3,$4,$5::jsonb,$6)""",
                run_id, question, answer, tool_call_count,
                json.dumps(citations, ensure_ascii=False), duration_ms,
            )
            for s in steps:
                await conn.execute(
                    """INSERT INTO trace_steps (run_id, step, type, tool, args, result_summary, latency_ms)
                       VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7)""",
                    run_id, s.step, s.type, s.name,
                    json.dumps(s.args, ensure_ascii=False) if s.args else None,
                    s.result_summary, s.latency_ms,
                )
    return run_id


async def get_run(pool: Pool, run_id: str) -> dict | None:
    async with pool.acquire() as conn:
        run = await conn.fetchrow(
            "SELECT run_id, question, answer, tool_call_count, citations, duration_ms, started_at"
            " FROM chat_runs WHERE run_id = $1", run_id)
        if run is None:
            return None
        steps = await conn.fetch(
            "SELECT step, type, tool, args, result_summary, latency_ms"
            " FROM trace_steps WHERE run_id = $1 ORDER BY step, id", run_id)
    return {
        "run_id": run["run_id"],
        "question": run["question"],
        "answer": run["answer"],
        "tool_call_count": run["tool_call_count"],
        "citations": json.loads(run["citations"]),
        "duration_ms": run["duration_ms"],
        "started_at": run["started_at"].isoformat(),
        "steps": [
            {
                "step": s["step"], "type": s["type"], "tool": s["tool"],
                "args": json.loads(s["args"]) if s["args"] else None,
                "result_summary": s["result_summary"], "latency_ms": s["latency_ms"],
            }
            for s in steps
        ],
    }


async def list_runs(pool: Pool, limit: int = 20) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT run_id, question, tool_call_count, duration_ms, started_at"
            " FROM chat_runs ORDER BY id DESC LIMIT $1", limit)
    return [
        {
            "run_id": r["run_id"], "question": r["question"],
            "tool_call_count": r["tool_call_count"], "duration_ms": r["duration_ms"],
            "started_at": r["started_at"].isoformat(),
        }
        for r in rows
    ]
