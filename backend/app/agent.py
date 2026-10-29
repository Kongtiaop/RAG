"""Agent tool_call 循环：qwen-plus + 3 个检索工具，全程产出可检测的 trace。

M5 升级：真流式——run_agent_stream 是核心生成器，逐段 yield 事件：
  {"type": "tool",  "step": TraceStep}   工具调用完成（含参数/结果摘要/耗时）
  {"type": "token", "text": str}         最终回答的增量 token
  {"type": "end",   "citations": [...], "final_step": TraceStep}
run_agent()（非流式，供测试）由事件流聚合而成。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import AsyncIterator

from . import config
from .llm import chat_stream
from .tools import TOOL_SCHEMAS, dispatch_tool

SYSTEM_PROMPT = """你是"叶先生的个人技术知识库助手"，基于三层语料回答问题：
- blog：项目博客（本项目的设计决策与踩坑）
- basics：通用基础知识（Python/数据库/LLM/Agent 等）
- daily：开源日报（每天 GitHub 趋势项目摘要，doc_id 形如 daily-20261029）

规则：
1. 回答知识性问题前，必须先调用 search_docs 检索（默认三层全查）；检索结果不足以覆盖问题时，
   可调整 query、用 layers 限定某层再检索，或用 get_document 读全文。
2. 用户问"最近的日报""今天有什么新项目"时，先调用 latest_daily 拿清单，再 get_document 读某天全文。
3. 回答必须基于检索到的语料，并标注来源（doc_id 与章节标题）。语料没有的内容，如实说明"语料中未涉及"，不要编造。
4. 用简体中文回答，结构清晰，重要结论先行。
5. 用户若询问语料库里有什么，用 list_documents。"""


@dataclass
class TraceStep:
    step: int
    type: str                     # tool | final
    name: str | None = None       # 工具名
    args: dict | None = None
    result_summary: str | None = None
    latency_ms: int = 0

    def to_dict(self) -> dict:
        d = {"step": self.step, "type": self.type}
        if self.name:
            d["tool"] = self.name
            d["args"] = self.args
            d["result_summary"] = self.result_summary
            d["latency_ms"] = self.latency_ms
        return d


@dataclass
class AgentResult:
    answer: str
    steps: list[TraceStep] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)   # 引用的 doc_id+heading
    tool_call_count: int = 0


def _summarize(result: dict, limit: int = 300) -> str:
    s = json.dumps(result, ensure_ascii=False)
    return s[:limit] + ("…" if len(s) > limit else "")


async def run_agent_stream(
    question: str, history: list[dict] | None = None
) -> AsyncIterator[dict]:
    """受限 ReAct 事件流。"""
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages.extend(history[-6:])
    messages.append({"role": "user", "content": question})

    seen_citations: dict[str, dict] = {}
    tool_call_count = 0
    final_step: TraceStep | None = None

    for step_no in range(1, config.AGENT_MAX_STEPS + 1):
        t0 = time.monotonic()
        stream = await chat_stream(messages, tools=TOOL_SCHEMAS)

        content_parts: list[str] = []
        tc_acc: dict[int, dict] = {}

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue
            if delta.content:
                content_parts.append(delta.content)
                yield {"type": "token", "text": delta.content}
            for tc in delta.tool_calls or []:
                acc = tc_acc.setdefault(
                    tc.index, {"id": "", "name": "", "arguments": ""}
                )
                if tc.id:
                    acc["id"] = tc.id
                if tc.function and tc.function.name:
                    acc["name"] = tc.function.name
                if tc.function and tc.function.arguments:
                    acc["arguments"] += tc.function.arguments

        content = "".join(content_parts)

        if not tc_acc:
            final_step = TraceStep(
                step=step_no, type="final",
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
            yield {"type": "end", "citations": list(seen_citations.values()),
                   "final_step": final_step}
            return

        # 本轮是工具调用轮：把增量聚合成完整 tool_calls
        messages.append(
            {
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {"id": a["id"], "type": "function",
                     "function": {"name": a["name"], "arguments": a["arguments"]}}
                    for a in (tc_acc[i] for i in sorted(tc_acc))
                ],
            }
        )
        for i in sorted(tc_acc):
            acc = tc_acc[i]
            try:
                args = json.loads(acc["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            t1 = time.monotonic()
            tool_result = await dispatch_tool(acc["name"], args)
            latency = int((time.monotonic() - t1) * 1000)

            tool_call_count += 1
            ts = TraceStep(
                step=step_no, type="tool", name=acc["name"], args=args,
                result_summary=_summarize(tool_result), latency_ms=latency,
            )
            yield {"type": "tool", "step": ts}

            for hit in tool_result.get("hits", []):
                seen_citations[f"{hit['doc_id']}::{hit['heading']}"] = {
                    "doc_id": hit["doc_id"], "title": hit["title"], "heading": hit["heading"],
                    "score": hit["score"], "snippet": hit["content"][:300],
                }
            if "doc_id" in tool_result and "error" not in tool_result:
                seen_citations.setdefault(
                    f"{tool_result['doc_id']}::全文",
                    {"doc_id": tool_result["doc_id"], "title": tool_result["title"],
                     "heading": "全文", "score": None,
                     "snippet": tool_result["content"][:300]},
                )

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": acc["id"],
                    "content": json.dumps(tool_result, ensure_ascii=False)[:6000],
                }
            )

    # 达到步数上限仍未收敛
    final_step = TraceStep(step=config.AGENT_MAX_STEPS + 1, type="final", latency_ms=0)
    yield {"type": "end",
           "citations": list(seen_citations.values()),
           "final_step": final_step,
           "truncated": True}


async def run_agent(question: str, history: list[dict] | None = None) -> AgentResult:
    """非流式封装：聚合同一事件流（供守卫测试等使用）。"""
    answer_parts: list[str] = []
    steps: list[TraceStep] = []
    citations: list[dict] = []
    truncated = False

    async for ev in run_agent_stream(question, history):
        if ev["type"] == "token":
            answer_parts.append(ev["text"])
        elif ev["type"] == "tool":
            steps.append(ev["step"])
        elif ev["type"] == "end":
            citations = ev["citations"]
            steps.append(ev["final_step"])
            truncated = ev.get("truncated", False)

    answer = "".join(answer_parts)
    if truncated:
        answer = "（已达工具调用步数上限，以下基于已检索内容回答）" + answer
    return AgentResult(
        answer=answer, steps=steps, citations=citations,
        tool_call_count=sum(1 for s in steps if s.type == "tool"),
    )
