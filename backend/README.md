# agentic_rag 后端

## 架构

```
FastAPI (8000) ── /chat (SSE: step→answer→done)
               ├─ /documents, /documents/{id}   ← 前端阅读页 + Agent 工具共用
               └─ Agent tool_call 循环 (qwen-plus, ≤6 步)
                    └─ search_docs（混合：向量 + BM25，RRF 融合，BM25 失败自动降级）
                       ├─ pgvector HNSW（1024 维，语义主力）
                       └─ pg_search BM25（精确词补充，中文拆词：剥停用字+bigram）
                         └─ PostgreSQL 16 (ParadeDB 镜像)

MCP Server (stdio, FastMCP) —— 同一组工具暴露给任意 MCP 客户端
```

语料：`docs/blog` + `docs/basics`（reference 不入库）。每次摄取为全量重建。

## 常用命令（均在 backend/ 目录下）

```bash
docker compose up -d postgres          # 起库
docker compose run --rm -T api python -m app.ingest --check   # 干跑：只统计
docker compose run --rm -T api python -m app.ingest           # 全量摄取
docker compose up -d api               # 起 API（localhost:8000）

curl localhost:8000/health             # {"status":"ok","documents":27,"chunks":348}
curl -N -X POST localhost:8000/chat -H "Content-Type: application/json" \
     -d '{"question":"..."}'           # SSE 流式：step 事件（工具链路）→ answer → done

../.venv/Scripts/python.exe -m pytest tests/ -q    # 单测（宿主机 venv 即可）

# MCP server（stdio）—— 客户端 mcp.json 里配 docker compose run 方式启动
docker compose run --rm -T api python -m app.mcp_server
```

## 已知坑（勿重蹈）

1. **沙箱内宿主机 raw TCP 到 localhost 会被透明代理拦截**（HTTP/HTTPS 走代理正常，asyncpg 裸连必被 reset）→ **数据库连接一律走容器网络**（DATABASE_URL=postgres:5432），宿主机 venv 只跑不碰网的单测。
2. MCP 客户端会**清洗子进程环境变量**（白名单制）→ MCP 子进程拿不到 DATABASE_URL；config.py 已做容器内兜底（/.dockerenv 存在时默认 postgres:5432），外部客户端接入时在 mcp.json 的 env 里显式配置。
3. `mcp` 包钉在 `<2`（2.x 把 FastMCP 更名 MCPServer，API 不兼容）。
4. bash 管道 `| tail` 会吞掉非零退出码和报错——排障时先落盘日志再 grep。
5. compose 的 `environment` 空值插值会覆盖 `env_file`——Key 类变量只用 env_file。
