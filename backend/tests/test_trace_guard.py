"""M4 守卫测试：跑一轮真实对话，逐条断言 Trace 不变量。

需在容器内运行（依赖 DB + DashScope）：
  docker compose run --rm -T api python -m pytest tests/test_trace_guard.py -q
"""
from __future__ import annotations

import asyncio

from app.agent import run_agent
from app.db import get_pool
from app.trace import get_run, save_run

QUESTION = "什么是混合检索？为什么要用两条腿？"


async def _setup():
    pool = await get_pool()
    result = await run_agent(QUESTION)
    run_id = await save_run(
        pool, QUESTION, result.answer, result.steps,
        result.citations, result.tool_call_count, 0,
    )
    trace = await get_run(pool, run_id)
    return result, trace


def test_guards():
    result, trace = asyncio.run(_setup())

    # G0 基线：回答非空，检索真实发生
    assert result.answer, "回答为空"
    assert result.tool_call_count >= 1, "一次工具调用都没发生——Agent 未走检索链路"

    # G1 任何一次 run_agent 必须在 chat_runs 产生一行（get_run 取到即证明）
    assert trace is not None, "trace 未落库"
    assert trace["question"] == QUESTION
    assert trace["answer"] == result.answer

    # G2 tool 行数 == tool_call_count
    tool_steps = [s for s in trace["steps"] if s["type"] == "tool"]
    assert len(tool_steps) == trace["tool_call_count"] == result.tool_call_count, (
        f"工具行数({len(tool_steps)}) 与计数({trace['tool_call_count']}/{result.tool_call_count})不一致"
    )

    # G3 每个 tool 行必须有 tool 名、args、latency
    for s in tool_steps:
        assert s["tool"], f"step {s['step']} 缺工具名"
        assert s["args"] is not None, f"step {s['step']} 缺 args"
        assert isinstance(s["latency_ms"], int) and s["latency_ms"] >= 0, (
            f"step {s['step']} 缺 latency"
        )
        assert s["result_summary"], f"step {s['step']} 缺结果摘要"

    # G4 必须有 final 收尾行
    assert any(s["type"] == "final" for s in trace["steps"]), "缺 final 收尾行"

    # G5 引用字段完整（Agent 回答知识问题必有引用）
    assert trace["citations"], "知识类回答没有任何引用——检索结果未进入答案"
    for c in trace["citations"]:
        assert c["doc_id"] and c["title"] and c["heading"], f"引用字段不完整: {c}"

    # G6 工具名全部在白名单内
    allowed = {"search_docs", "get_document", "list_documents"}
    assert all(s["tool"] in allowed for s in tool_steps), "出现未注册工具"
