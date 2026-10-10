"""MCP Server：把三个检索工具暴露给任意 MCP 客户端（FastMCP，mcp 1.x）。

两种传输：
- stdio（默认，本地/同机客户端）：
    cd backend && docker compose run --rm -T api python -m app.mcp_server
- streamable-http（远程客户端，如 WorkBuddy / Claude Desktop）：
    MCP_TRANSPORT=streamable-http MCP_PORT=9001 python -m app.mcp_server
    服务路径 /mcp/，生产环境由 nginx 加 X-MCP-Token 门禁后对外。

注：mcp 2.x 已把 FastMCP 更名为 MCPServer，本项目钉在 mcp<2。
"""
from __future__ import annotations

import json
import os

from mcp.server.fastmcp import FastMCP

TRANSPORT = os.environ.get("MCP_TRANSPORT", "stdio")
MCP_PORT = int(os.environ.get("MCP_PORT", "9001"))

mcp = FastMCP(
    "agentic-rag",
    host="0.0.0.0" if TRANSPORT == "streamable-http" else "127.0.0.1",
    port=MCP_PORT,
    # 无状态模式：适配经 nginx 代理的远程客户端（无需会话粘滞）
    stateless_http=(TRANSPORT == "streamable-http"),
)


@mcp.tool()
async def search_docs(query: str, top_k: int = 5) -> str:
    """在技术博客与基础知识库中做语义检索，回答知识性问题前应先调用本工具。"""
    from .tools import search_docs as _impl

    return json.dumps(await _impl(query, top_k), ensure_ascii=False)


@mcp.tool()
async def get_document(doc_id: str) -> str:
    """按 doc_id 读取某篇文档的完整原文（markdown）。"""
    from .tools import get_document as _impl

    return json.dumps(await _impl(doc_id), ensure_ascii=False)


@mcp.tool()
async def list_documents(layer: str = "") -> str:
    """列出语料库全部文档清单，可按层过滤（blog=项目博客，basics=通用基础知识）。"""
    from .tools import list_documents as _impl

    return json.dumps(await _impl(layer or None), ensure_ascii=False)


if __name__ == "__main__":
    mcp.run(transport=TRANSPORT)
