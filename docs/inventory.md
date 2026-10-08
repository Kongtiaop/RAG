# 文档清单与价值分级（inventory）

> 生成日期：2026-10-08
> 来源：`C:/Users/tx360/Desktop/wealth-manager`（105 篇 md + 若干 pdf/docx/html/txt）
> 用途：M2 按主题重写的选材依据。分级规则只做初筛，逐篇人工判断；**最终取舍以用户抽查确认为准**。

## 1. 统计概览

| 分级 | 篇数 | 说明 |
|---|---|---|
| 核心 | 46 | 重写入库的主材 |
| 参考 | 21 | M2 时按主题吸收其内容，不单独成文 |
| 排除 | 38 | 个人材料 / 版本重复 / 过程台账 / 凭据与临时文件 |

## 2. 分级标准

- **核心**：含可长期复用的架构、设计、机制、业务知识，且非重复版本。
- **参考**：有价值但属过程性/草稿/与其他文档高度重叠，重写时吸收观点即可。
- **排除**：简历与面试答辩材料（个人考核）、同一文档的旧版本、流水账台账、账号凭据、空临时文件。

## 3. 清单明细

### 3.1 架构与系统设计（核心为主）

| 文件 | 行数 | 分级 | 备注 |
|---|---|---|---|
| docs/README.md | 11 | 参考 | 目录索引 |
| README.md（根） | 56 | 核心 | 项目总览，含系统定位 |
| docs/ARCHITECTURE_OVERVIEW.md | 554 | 核心 | 整体架构 v1.1，§15~§20 为最新增补 |
| docs/ARCHITECTURE.md | 144 | 核心 | 可替换基础设施与 Agent 接口（Port/Adapter） |
| docs/ARCHITECTURE_DATABASE_DRAFT.md | 1348 | 核心 | 名为 draft 实为完整架构+数据库前置方案 |
| docs/DATABASE_TABLE_REFERENCE.md | 927 | 核心 | 50 张表结构权威参考 |
| docs/DEFENSE_SYSTEM_DESIGN_AND_EVOLUTION.md | 4209 | 核心 | 系统设计+架构演进+工程复盘，最全面的一篇 |
| docs/企业级智能Agent系统架构设计全书.md | 1271 | 核心 | 系统化架构设计长文 |
| docs/功能设计文档.html（根） | - | 参考 | HTML，M2 时提取内容 |
| docs/需求文档.html（根） | - | 参考 | HTML，M2 时提取内容 |
| docs/记忆架构设计.html（根） | - | 参考 | HTML，M2 时提取内容 |

### 3.2 API / 数据 / 错误码（核心）

| 文件 | 行数 | 分级 | 备注 |
|---|---|---|---|
| docs/API.md | 478 | 核心 | 接口文档 |
| docs/ERROR_CODES.md | 328 | 核心 | 错误码与成功码体系 |
| docs/RBAC_PERMISSION_MATRIX.md | 234 | 核心 | 权限矩阵 |
| docs/DATA_ANALYSIS_AGENT_SECURITY_2026-08-12.md | 58 | 核心 | 数据分析 Agent 安全执行 |

### 3.3 Agent 编排与记忆（核心）

| 文件 | 行数 | 分级 | 备注 |
|---|---|---|---|
| docs/MULTI_AGENT_PARADIGM_AND_BOUNDED_REACT_2026-08-12.md | 191 | 核心 | 受限 ReAct 演进设计 |
| docs/AGENT_FUNCTIONS_AND_BUSINESS_DESIGN.md | 486 | 核心 | Agent 功能与业务映射总览 |
| docs/多 Agent 共享记忆设计方案.md | 1186 | 核心 | 记忆架构主设计 |
| docs/记忆链路全链路落地与踩坑复盘.md | 117 | 核心 | 落地复盘 |
| docs/TencentDB Agent Memory .md | 209 | 核心 | 记忆机制深度总结 |
| docs/受控子代理并行层设计方案.md | 262 | 核心 | 并行子代理设计 |
| docs/后台Agent与客户Agent双管线拆分方案.md | 170 | 核心 | 双管线设计决策 |
| docs/可配置理解层与难度模型路由设计.md | 120 | 核心 | 理解层路由 |
| docs/长时运行 Agent 断点续跑设计方案.md | 1024 | 核心 | 断点续跑设计 |
| docs/数据流转与State流转.md | 319 | 核心 | 当前实现的 State 流转 |
| docs/渐进式披露RAG-三MCP设计方案.md | 187 | 核心 | **搜文件/看大纲/读文件三 MCP 设计，与本项目直接同构，重点参考** |

### 3.4 RAG / 知识库（核心）

| 文件 | 行数 | 分级 | 备注 |
|---|---|---|---|
| docs/KNOWLEDGE_AND_DATA_CATALOG_ARCHITECTURE.md | 438 | 核心 | 知识治理与数据目录架构 |
| docs/RAG_BM25_全链路复盘.md | 91 | 核心 | BM25 上线复盘 |
| docs/RAG_BM25_paradedb_runbook.md | 78 | 核心 | ParadeDB 迁移 Runbook |
| docs/AGENT_RAG_EVALUATION_GUIDE.md | 97 | 核心 | RAG 评测指南；**GBK 编码，摄取前转 UTF-8**（grep 误报二进制即此因） |
| docs/Agent & RAG 数据飞轮：从规划到落地.md | 225 | 核心 | 数据飞轮规划与落地 |
| docs/数据飞轮与意图识别评测.md | 232 | 核心 | 意图识别评测落地 |
| docs/OBSERVABILITY_IMPLEMENTATION_PLAN.md | 847 | 核心 | 可观测性实施计划 |

### 3.5 可靠性 / 性能 / 工程实践（核心）

| 文件 | 行数 | 分级 | 备注 |
|---|---|---|---|
| docs/任务可靠性改进方案.md | 341 | 核心 | 任务可靠性 |
| docs/依赖注入与中间件实现说明.md | 396 | 核心 | DI 与中间件 |
| docs/长链排查全记录-八层缺陷.md | 474 | 核心 | 排查方法论，含被证伪假设 |
| docs/并发冲突复盘_profile_me死锁与多worker启动seed死锁.md | 78 | 核心 | 并发问题复盘 |
| docs/性能压测报告_2026-08-28.md | 138 | 核心 | 压测数据 |
| docs/基于性能瓶颈洞察的架构修正建议.md | 161 | 核心 | 瓶颈驱动的架构修正 |
| docs/压测实施runbook_4c8g_p0.md | 79 | 核心 | 压测 Runbook |
| docs/WORKORDER_DESIGN.md | 214 | 核心 | 工单权限与最小闭环 |
| docs/从设计级到上线级差距清单.md | 124 | 核心 | 设计 vs 上线差距 |
| docs/系统接线现状与接线后预测.md | 197 | 核心 | 接线/死代码现状盘点 |
| docs/财富管理 AI 系统：业务方向验证与实施建议.md | 685 | 核心 | 业务方向验证 |
| docs/财富管理 AI 系统：业务能力差距分析与补齐计划.md | 211 | 核心 | 能力差距分析 |

### 3.6 运维与流程（核心）

| 文件 | 行数 | 分级 | 备注 |
|---|---|---|---|
| docs/CICD_SETUP.md | 66 | 核心 | CI/CD 搭建 |
| docs/DEVELOPMENT_WORKFLOW.md | 131 | 核心 | 开发门禁 |
| docs/RUNBOOK-演示与E2E验收.md | 79 | 核心 | 演示与验收 |
| docs/TEAM_ONBOARDING.md | 193 | 核心 | 团队上手 |
| 开发引导.md（根） | 328 | 核心 | 开发实施引导 |
| docs/P0_INFRASTRUCTURE.md | 82 | 核心 | 本地基础设施 |
| docs/P0_IMPLEMENTATION.md | 76 | 核心 | P0 落地笔记 |

### 3.7 业务知识（**整体排除** —— 2026-10-08 用户定位为技术博客，业务内容不入库）

| 文件 | 行数 | 备注 |
|---|---|---|
| 公司业务/ 个人理财产品手册、企业金融服务方案、高净值客户服务规范 | 1330 | 排除 |
| 公司信息/ 企业信息、公司新人指南 | 724 | 排除 |
| 金融政策/ 三篇合规手册 | 1518 | 排除 |
| 用户研判规则/ 三篇 | 1394 | 排除 |
| knowledge_corpus/ 六篇客户版文档 | 1416 | 排除 |
| docs/BUSINESS_KNOWLEDGE_COMPANY / POLICIES / PRODUCTS / RISK | 523 | 排除 |

### 3.8 参考级（M2 吸收观点，不单独成文）

| 文件 | 行数 | 分级 | 备注 |
|---|---|---|---|
| docs/_draft_agents.md | 189 | 参考 | 实现细节简报 |
| docs/_draft_memory_outbox.md | 221 | 参考 | **GBK 编码**，需转码 |
| docs/_draft_rag_nl2sql.md | 193 | 参考 | 实现细节简报 |
| docs/_draft_rbac.md | 209 | 参考 | 实现细节简报 |
| docs/_draft_trading.md | 193 | 参考 | 实现细节简报 |
| docs/DECISIONS.md | 2456 | 参考 | 文档版本与当前有效方案说明（重写时用于判断哪版为准） |
| docs/PLAN.md | 9887 | 参考 | 历史实施计划，过程性强 |
| docs/P0-P5_IMPLEMENTATION_PLAN.md | 729 | 参考 | 实施计划 v2 |
| docs/BUG_LOG.md（根） | 6533 | 参考 | 台账；方法论教训提炼进 M2 第 11 篇 |
| docs/BUG_LOG.md（docs/） | 15 | 排除 | 已合并标记 |
| docs/ISSUES.md | 6469 | 参考 | 台账 |
| docs/TESTS.md | 7994 | 参考 | 测试记录台账 |
| docs/CODE_CHANGELOG.md | 1869 | 参考 | 变更台账 |
| docs/AGENT_NEXT_STEPS_AND_PROGRESS_2026-08-14.md | 816 | 参考 | 进度快照 |
| docs/AGENT_STRATEGY_EVALUATION_AND_IMPLEMENTATION_ROADMAP_2026-08-14.md | 360 | 参考 | **GBK 编码** |
| docs/答辩面试实现细节手册.md | 426 | 参考 | 解释性内容吸收进主题文档 |
| docs/数据库答辩提纲.md | 104 | 参考 | 同上 |
| docs/Agent产品设计对照评估.md | 162 | 参考 | 产品对照评估 |
| docs/RUNBOOK 等 P0/P5 计划类 | - | 参考 | 已列 |
| docs/README.md / docs/目录类 | - | 参考 | 已列 |

### 3.9 排除级（不入库）

| 文件 | 理由 |
|---|---|
| docs/RESUME_PROJECTS.md、RESUME_PROJECTS_CONCISE.md、resume_optimized.md | 简历材料 |
| docs/叶绍康-AI应用开发工程师-项目更新.md | 简历更新 |
| 叶绍康-AI应用开发工程师.pdf / .docx、resume_copy.docx、project_docx_copy.docx | 简历文件 |
| docs/WL-面试问题分类汇总-V3.md（1239）、面试问答-与叶绍康相关.md（1034）、面试核心模块伪代码速写.md（363）、面试速记卡.md（127） | 面试材料 |
| 答辩须知.md（14） | 答辩材料 |
| DEMO_ACCOUNTS.txt、docs/DEMO_ACCOUNTS.example.txt | 凭据类，防泄漏 |
| 新建 文本文档.txt | 空临时文件 |
| docs/PROJECT_DOCUMENT_COMPLETE.md（188）、_DETAILED.md（232）、PROJECT_FEATURE_ARCHITECTURE_TRACEABILITY.md（188） | 同一文档旧版本，四版本取 FINAL4 |
| wealth_pgdata_20260903.tar.gz 等二进制/备份 | 非文档 |
| app/、frontend/ 等代码目录 | 代码不属本次文档库范围 |

**版本增殖组取证**：四篇头部均为"更新时间：2026-08-21 | 文档性质：功能与架构全景盘点"，同一日期同一性质；FINAL4（735 行）内容最全，**取 FINAL4 为准，其余三篇排除**。

## 4. 已发现的技术问题（摄取前必须处理）

1. **GBK 编码 1 篇**：`AGENT_RAG_EVALUATION_GUIDE.md`（Python 逐篇解码验证，其余 104 篇均为合法 UTF-8）。摄取管线仍统一做编码探测兜底。
2. 此前 bash 控制台显示的"乱码"（AGENT_STRATEGY_EVALUATION 等标题乱码、文件名乱码）为终端代码页显示问题，**文件本身编码正常**。

## 5. M2 重写主题映射（12 篇目标文档 —— 2026-10-08 修订：剔除业务类，定位技术博客）

| 目标文档 | 主要来源 |
|---|---|
| 01-系统架构总览 | ARCHITECTURE_OVERVIEW、DEFENSE_SYSTEM、README、架构全书 |
| 02-数据模型与数据库设计 | DATABASE_TABLE_REFERENCE、ARCHITECTURE_DATABASE_DRAFT |
| 03-API 接口与错误码体系 | API.md、ERROR_CODES.md |
| 04-Agent 编排与受限 ReAct | MULTI_AGENT_PARADIGM、AGENT_FUNCTIONS、数据流转、双管线、受控子代理、可配置理解层 |
| 05-多 Agent 记忆架构 | 共享记忆设计、记忆链路复盘、TencentDB Agent Memory、_draft_memory_outbox |
| 06-RAG 检索体系 | RAG_BM25 两篇、渐进式披露三 MCP、KNOWLEDGE_AND_DATA_CATALOG、评测指南 |
| 07-任务可靠性与断点续跑 | 任务可靠性、断点续跑设计、P0_INFRASTRUCTURE |
| 08-权限与安全 | RBAC 矩阵、WORKORDER、DATA_ANALYSIS_AGENT_SECURITY、_draft_rbac |
| 09-性能与压测 | 压测报告、runbook、瓶颈修正建议、并发冲突复盘 |
| 10-可观测性与数据飞轮 | OBSERVABILITY_PLAN、数据飞轮两篇 |
| 11-工程实践与排查方法论 | 长链排查八层缺陷、BUG_LOG 提炼、差距清单、接线现状、DECISIONS、依赖注入与中间件实现说明 |
| 12-运维与协作手册 | CICD、DEVELOPMENT_WORKFLOW、RUNBOOK、TEAM_ONBOARDING、开发引导 |

每篇头部带溯源块：`> 来源: <源文件列表（含章节）>`；重写原则：按主题重组、去版本噪声、保留原始数据与结论、不虚构未在源文档中出现的内容。
