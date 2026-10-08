# agentic_rag 技术知识库

> 由 `Desktop/wealth-manager` 项目存量文档提炼而成，定位：**技术博客**。
> 两层结构：`blog/` 是问题驱动的博客文章（碰到什么问题→怎么解决→为什么这么选），`reference/` 是按主题重写的参考文档（参数、表结构、清单类事实，供检索与查证）。
> 重写于 2026-10-08；选材依据见 [inventory.md](inventory.md)。业务类内容已整体剔除。

## blog/ —— 博客文章（问题驱动）

| # | 文章 | 一句话 |
|---|---|---|
| 01 | 为什么是受限 ReAct | 全自动多 Agent 很性感，但权限先于路由才活得下来 |
| 02 | 渐进式披露：三个小工具胜过一个大工具 | 搜文件/看大纲/读文件的 MCP 设计 |
| 03 | 分层记忆是怎么长出来的 | L0-L3 不是设计出来的，是被问题逼出来的 |
| 04 | Outbox + Streams：异步可靠性的笨办法 | 消息丢了才知道"直接写"有多天真 |
| 05 | 给 RAG 加 BM25 的全过程 | 向量检索不是银弹，三路评测说话 |
| 06 | 一次"答案重复"引发的八层缺陷排查 | 表层症状挖到第八层才见底 |
| 07 | 两个并发死锁的复盘 | profile/me 死锁与多 worker seed 死锁 |
| 08 | 从 280+ 条 BUG 里学到的 | 六类高频坑与九条被证伪的假设 |
| 09 | 权限为什么必须先于路由 | RBAC + 能力白名单的设计动因 |
| 10 | 受控 NL2SQL：把"能写 SQL"关进笼子 | 白名单 + 数据目录 + 确认令牌 |

## reference/ —— 参考文档（事实与参数）

01 架构总览 / 02 数据模型 / 03 API 与错误码 / 04 Agent 编排 / 05 记忆架构 / 06 RAG 检索 / 07 任务可靠性 / 08 权限安全 / 09 性能压测 / 10 可观测与飞轮 / 11 工程实践方法论 / 12 运维手册

## basics/ —— 通用基础知识（与项目无关）

| # | 文章 | 覆盖 |
|---|---|---|
| 01 | [Python 基础与工程实践](basics/01-Python基础与工程实践.md) | venv/uv、类型注解、asyncio、装饰器/生成器、常见坑 |
| 02 | [MySQL 基础](basics/02-MySQL基础.md) | CRUD/JOIN、索引与最左前缀、事务隔离、EXPLAIN |
| 03 | [PostgreSQL 与 pgvector 基础](basics/03-PostgreSQL与pgvector基础.md) | JSONB/CTE、pgvector 向量检索与 HNSW、混合查询 |
| 04 | [LangChain 基础](basics/04-LangChain基础.md) | 模块全景、LCEL、RAG 最小链路（对齐 1.0 API） |
| 05 | [LangGraph 基础](basics/05-LangGraph基础.md) | StateGraph、Checkpointer、interrupt、多 Agent 模式 |
| 06 | [Milvus 基础](basics/06-Milvus基础.md) | 部署形态选型、MilvusClient、索引对比、常见坑 |
| 07 | [RAG 基础](basics/07-RAG基础.md) | 摄取/检索双链路、切块权衡、混合检索+重排、评测、进阶方向 |
| 08 | [知识图谱基础](basics/08-知识图谱基础.md) | 三元组与本体、构建路径、Neo4j/Cypher、GraphRAG 结合 |
| 09 | [AG-UI 协议基础](basics/09-AG-UI协议基础.md) | Agent→前端事件流标准（1.0，31 事件）、框架集成 |
| 10 | [A2UI 基础](basics/10-A2UI基础.md) | Agent 动态生成 UI（Google，v0.9）、与 AG-UI 互补关系 |
| 11 | [本体 Ontology 基础](basics/11-本体Ontology基础.md) | 类/属性/公理建模、RDF/OWL/SHACL 技术栈、与 LLM 时代结合 |
| 12 | [上下文工程](basics/12-上下文工程Context-Engineering.md) | 上下文预算与分配、压缩淘汰、工具结果处理 |
| 13 | [Agent 范式](basics/13-Agent范式：ReAct-Plan-and-Execute-反思与多Agent.md) | ReAct / Plan-and-Execute / 反思 / 多 Agent 对比与选择 |
| 14 | [Function Calling 与结构化输出](basics/14-FunctionCalling与结构化输出.md) | tool_call 机制、schema 设计、strict mode、工具设计原则 |
| 15 | [MCP 协议与 Agent Skills](basics/15-MCP协议与Agent-Skills.md) | MCP 架构与能力集（2026-07 规范）、SKILL.md 技能包 |
| 16 | [Embedding 与向量索引原理](basics/16-Embedding与向量索引原理.md) | 语义几何直觉、相似度度量、HNSW/IVF-PQ 对比 |
| 17 | [FastAPI 与异步编程](basics/17-FastAPI与异步编程.md) | 依赖注入、Pydantic、SSE 流式、async 心智模型 |
| 18 | [Python 并发：协程线程与进程](basics/18-Python并发：协程线程与进程.md) | 三类并发对比与选型、GIL、TaskGroup、常见坑 |
| 19 | [LLM 评测与 Harness 基础](basics/19-LLM评测与Harness基础.md) | 黄金数据集、LLM-as-a-Judge、rubric 设计、任务级指标 |
| 20 | [数据飞轮](basics/20-数据飞轮Data-Flywheel.md) | badcase 回流、评测集版本化、冷启动内循环 |

## 阅读建议

- 想看故事与教训：从 blog/01 顺着读。
- 想查事实与参数：直接翻 reference/ 对应主题。
- 想补基础：basics/ 按需查阅，04/05（LangChain/LangGraph）是理解 Agent 编排的前置。
- reference/06 的"渐进式披露三 MCP"与本库 agentic RAG 工具层同构，是 backend 工具设计的直接参考。
