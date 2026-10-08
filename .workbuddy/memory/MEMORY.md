# agentic_rag 项目长期备忘

## 定位与结构
- 个人技术博客 + agentic RAG 系统（自用知识库，非考核交付物）。
- 双层+基础语料：`docs/blog/`（7 篇问题驱动博客，主语料）+ `docs/basics/`（20 篇通用基础：Python/MySQL/PG+pgvector/LangChain/LangGraph/Milvus/RAG/知识图谱/AG-UI/A2UI/本体/上下文工程/Agent范式/FunctionCalling/MCP+Skills/Embedding/FastAPI/并发/评测Harness/数据飞轮）+ `docs/reference/`（12 篇参考文档）。
- **检索范围（2026-10-08 用户明确）**：只索引并检索 blog + basics；reference 不入向量库、不被检索、前端不展示，仅留档。摄取范围走可配置目录列表，chunk 带 doc_layer 元数据。选材依据 `docs/inventory.md`。
- 业务/合规/客户 FAQ 内容已整体剔除（2026-10-08 用户定位技术博客）。
- **内容口味**：用户嫌《实现了但没接线》太低级已删；《压测撕开的真相》也已删（压测题材不要）——博客只收有深度/有故事的题材，基础常识类和性能数字类都不要。压测/死代码的事实数据仍在 reference 层留档。

## 技术选型（已定案）
- LLM/Embedding：DashScope Qwen（qwen-plus + text-embedding-v4），Key 在 .env。
- 向量存储：**PostgreSQL 16（ParadeDB 镜像）+ pgvector + pg_search BM25 混合检索**（2026-10-08 决策；RRF 融合，BM25 失败自动降级纯向量；中文拆词剥停用字+bigram）。部署目标 2C2G 单机（后续可能升 4G）。
- 后端 FastAPI / 前端 React 悬浮气泡 / MCP Server 三工具：search_docs、get_document、list_documents（web_search 已剔除）。
- 联网搜索决策：不做（Tavily 免费档可选但用户剔除；Qwen enable_search 因黑盒破坏链路可检测性被否）。
- 可观测决策：不上 LangSmith；M4 自建 Trace（run_type=agent|tool|llm，层级 span + token 字段，预留 exporter 外推，将来可接 Langfuse）。

## 架构参照
- docs/reference/06 的"渐进式披露三 MCP（搜文件/看大纲/读文件）"与本系统工具层同构，是 M3 工具设计的直接参考。

## 工作纪律
- **语料目录可能被用户手动增删**（2026-10-08 教训：用户手动删了 3 篇博客，我的记忆快照不知道）。任何涉及语料清单的操作前，先 `ls` 确认现状，不信任记忆。

## 进度
- M1 ✅ inventory.md（核心46/参考21/排除，仅 1 篇 GBK 已处理）
- M2 ✅ reference 12 篇 + blog 7 篇 + basics 20 篇（检索语料 27 篇）
- M3 ✅ 后端全链路：混合检索（pgvector+BM25/jieba，RRF）+ FastAPI（/chat SSE /documents）+ Agent tool_call（qwen-plus ≤6步）+ MCP Server——E2E 实测通过。运行命令与已知坑见 backend/README.md。
- M4 ✅ Trace 持久化（chat_runs + trace_steps 落 PG）+ /runs 回放端点 + 守卫测试 G0~G6（容器内真实链路断言）。
- M5 ⬜ React 前端（悬浮气泡 + 文章阅读页 + 链路时间线）
