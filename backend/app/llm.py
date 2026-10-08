"""DashScope（OpenAI 兼容）调用：Embedding 与 Chat。"""
from __future__ import annotations

import asyncio

from openai import AsyncOpenAI

from . import config

_client = AsyncOpenAI(
    api_key=config.DASHSCOPE_API_KEY,
    base_url=config.DASHSCOPE_BASE_URL,
)


async def embed(texts: list[str]) -> list[list[float]]:
    """批量向量化。text-embedding-v4 单条上限 2048 tokens/8192，块大小已受控。"""
    resp = await _client.embeddings.create(
        model=config.EMBEDDING_MODEL,
        input=texts,
        dimensions=config.EMBEDDING_DIM,
    )
    return [d.embedding for d in resp.data]


async def embed_in_batches(texts: list[str], batch_size: int = 10) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        out.extend(await embed(texts[i : i + batch_size]))
        await asyncio.sleep(0.2)  # 轻微限速
    return out


async def chat(messages: list[dict], tools: list[dict] | None = None):
    """单轮 chat，返回原始 response（含 tool_calls 时由调用方处理）。"""
    return await _client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=messages,
        tools=tools or None,
        temperature=0.3,
    )


async def chat_stream(messages: list[dict], tools: list[dict] | None = None):
    """流式 chat，返回 chunk 异步迭代器（tool_calls 以增量 delta 形式出现）。"""
    return await _client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=messages,
        tools=tools or None,
        temperature=0.3,
        stream=True,
    )
