"""MCP Server（stdio）：把三个检索工具暴露给任意 MCP 客户端（FastMCP，mcp 1.x）。

运行：cd backend && docker compose run --rm -T api python -m app.mcp_server
MCP 客户端配置示例（mcp.json）：
{
  "mcpServers": {
    "agentic-rag": {
      "command": "docker",
      "args": ["compose", "--project-directory", "<backend绝对路径>",
               "run", "--rm", "-T", "api", "python", "-m", "app.mcp_server"]
    }
  }
}
注：mcp 2.x 已把 FastMCP 更名为 MCPServer，本项目钉在 mcp<2；升级时按官方迁移指南调整。
"""
from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("agentic-rag")


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
    mcp.run()
