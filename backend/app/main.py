"""FastAPI 入口。

端点：
  GET  /health                 健康检查（含 DB 连通性）
  GET  /documents              文档清单（可按 layer 过滤）—— 前端阅读页列表
  GET  /documents/{doc_id}     文档全文 markdown —— 前端阅读页 + Agent 工具共用
  POST /chat                   对话（SSE：step 事件 → answer 事件 → done 事件）
  GET  /runs                   最近对话列表
  GET  /runs/{run_id}          单轮完整链路回放（M4 Trace）
"""
from __future__ import annotations

import json
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import db
from .agent import run_agent_stream
from .tools import get_document, list_documents
from .trace import get_run, list_runs, save_run

app = FastAPI(title="agentic_rag", version="0.1.0")


@app.on_event("startup")
async def _startup() -> None:
    from .trace import TRACE_SCHEMA

    pool = await db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(TRACE_SCHEMA)


@app.on_event("shutdown")
async def _shutdown() -> None:
    await db.close_pool()


@app.get("/health")
async def health():
    try:
        pool = await db.get_pool()
        async with pool.acquire() as conn:
            n_docs = await conn.fetchval("SELECT count(*) FROM documents")
            n_chunks = await conn.fetchval("SELECT count(*) FROM chunks")
        return {"status": "ok", "documents": n_docs, "chunks": n_chunks}
    except Exception as e:  # noqa: BLE001
        return {"status": "degraded", "error": str(e)}


@app.get("/documents")
async def documents(layer: str | None = None):
    return await list_documents(layer)


@app.get("/documents/{doc_id}")
async def document_detail(doc_id: str):
    doc = await get_document(doc_id)
    if "error" in doc:
        raise HTTPException(status_code=404, detail=doc["error"])
    return doc


class ChatRequest(BaseModel):
    question: str
    history: list[dict] | None = None


@app.post("/chat")
async def chat(req: ChatRequest):
    """SSE 真流式：step（工具）→ token（逐段回答）→ answer（收尾+run_id）→ done。"""

    async def event_stream():
        t0 = time.monotonic()
        pool = await db.get_pool()
        answer_parts: list[str] = []
        steps: list = []
        final_ev: dict | None = None

        async for ev in run_agent_stream(req.question, req.history):
            if ev["type"] == "tool":
                steps.append(ev["step"])
                yield f"event: step\ndata: {json.dumps(ev['step'].to_dict(), ensure_ascii=False)}\n\n"
            elif ev["type"] == "token":
                answer_parts.append(ev["text"])
                yield f"event: token\ndata: {json.dumps({'text': ev['text']}, ensure_ascii=False)}\n\n"
            elif ev["type"] == "end":
                final_ev = ev
                steps.append(ev["final_step"])

        if final_ev is None:
            yield f"event: error\ndata: {json.dumps({'message': 'agent 未正常收敛'})}\n\n"
            return

        duration_ms = int((time.monotonic() - t0) * 1000)
        tool_call_count = sum(1 for s in steps if s.type == "tool")
        run_id = await save_run(
            pool, req.question, "".join(answer_parts), steps,
            final_ev["citations"], tool_call_count, duration_ms,
        )
        yield (
            "event: answer\ndata: "
            + json.dumps(
                {"run_id": run_id, "citations": final_ev["citations"],
                 "duration_ms": duration_ms, "truncated": final_ev.get("truncated", False)},
                ensure_ascii=False,
            )
            + "\n\n"
        )
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/runs")
async def runs(limit: int = 20):
    return await list_runs(await db.get_pool(), limit)


@app.get("/runs/{run_id}")
async def run_detail(run_id: str):
    trace = await get_run(await db.get_pool(), run_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"run '{run_id}' 不存在")
    return trace


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
