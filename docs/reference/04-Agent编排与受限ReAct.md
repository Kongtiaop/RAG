# Agent 编排与受限 ReAct

> 来源:
> - `MULTI_AGENT_PARADIGM_AND_BOUNDED_REACT_2026-08-12.md`（多 Agent 范式、受限 ReAct、执行模式、目录驱动模板 SQL、审计与评估门禁）
> - `AGENT_FUNCTIONS_AND_BUSINESS_DESIGN.md`（Agent 总览、各 Agent 执行范式与边界、权限基础设施、设计原则）
> - `数据流转与State流转.md`（确定性管线与 LangGraph 双路径、AgentState 流转、开关体系）
> - `后台Agent与客户Agent双管线拆分方案.md`（客户向/员工向双管线拆分决策与落地）
> - `受控子代理并行层设计方案.md`（子代理级并行、边界矩阵、融合与降级）
> - `可配置理解层与难度模型路由设计.md`（理解层可配置、难度模型路由、安全固定轨道）
>
> 说明: 由 wealth-manager 项目文档按主题重写，重写于 2026-10-08。源文档间口径不一致处以较新、较完整的实现口径为准（如 ReAct 预算以落地实现的 3 轮/3 次工具调用为准，而非早期文档的 3~5 轮/5~8 次设想）。

---

## 1. 范式选型：为什么不是自由 ReAct

这套系统的整体范式是**权限感知的轻量规划多 Agent 编排**，而不是自由自治的 ReAct：

```text
用户请求
→ 权限与能力筛选（AgentCapabilityRegistry）
→ 轻量意图规划（CustomerIntentPlanner）
→ 受控任务路由与执行
→ 统一结果、审计、事件与人工接管
```

主 Agent 扮演 **Supervisor / Router + Lightweight Planner**，负责能力过滤、任务拆分、风险分级、分派、澄清和结果汇总。它**不直接持有高风险写操作能力**——最终业务事实、权限、金额、适当性、风控和状态转换都由后端确定性服务负责。

为什么先做能力过滤再做语义路由：

```text
用户角色/权限
→ available_agents / denied_agents
→ 只在可用 Agent 白名单中路由
```

这样可以减少无效调用、避免内部 Agent 暴露、集中权限决策，并让审计可以解释"为什么没有调用某个 Agent"。

### 1.1 执行模式三分层

主 Agent 的轻量 Plan 输出的每个任务都会标记 `execution_mode`，显式区分执行范式：

| 模式 | 适用场景 | 核心约束 |
|---|---|---|
| `bounded_react` | 低风险、只读、需要多跳检索或解释 | 轮数/工具数预算、工具白名单、必须带 evidence、失败澄清或转人工 |
| `controlled_workflow` | 数据分析执行、资金/订单/业务操作、风险处置、权限修改 | 权限→参数→规则→风险检查→确认/审批→状态机→幂等→审计/Outbox |
| `Plan + Rules` | 适当性判断、风险分级、产品匹配 | 模型只负责解释和组织证据，最终结论由规则/评分服务输出 |

任务到模式的映射规则：

```text
知识问答 / 政策 / 流程 / FAQ / 公司信息 / 公共风险说明 → bounded_react
资产、订单、工单、风控限制、数据分析、业务操作、人工接管 → controlled_workflow
```

`execution_mode` 已透出到意图规划 API 响应，并保存到短期记忆的 pending plan 和执行状态中，前端、审计和后续 Supervisor 都可据此区分受限推理任务与受控流程任务。

为什么高风险任务不采用自由 ReAct：受控工作流必须**可预测、可复现、可审批、可审计、可回滚**。

### 1.2 Agent 总览

| Agent | 主要职责 | 执行模式 | 禁止事项 |
|---|---|---|---|
| Supervisor / 主 Agent | 统一理解、权限过滤、轻量规划、路由、汇总 | Lightweight Plan | 不绕过权限调用内部 Agent；不直接写资金/业务事实 |
| CustomerServiceAgent | 客服问答、政策/流程/公司信息、客户只读事实、人工转接 | bounded_react + 受控只读 Tool | 不直接转账、赎回、下单、改库 |
| DataAnalysisAgent | 内部指标、批准模板、目录驱动分析 | controlled_workflow | 不执行自由 SQL、不查敏感字段、不越权 |
| AdvisorAgent | 投顾信息收集、产品解释、建议草案 | Plan + Rules / 受限只读推理 | 不替代适当性规则、不直接下单 |
| RiskAgent | 风险解释、告警查询、风险分级和处置辅助 | Plan + Rules / controlled_workflow | 不绕过规则直接改变风险事实 |
| BusinessAgent | 转账、赎回、申购、下单等业务草稿和确认 | controlled_workflow | 不在客服对话中直接执行资金操作 |
| AdminAgent | 后台管理、角色、权限和配置维护 | controlled_workflow | 普通用户不可用；不能无审计修改权限 |

---

## 2. 受限 ReAct（Bounded ReAct）

### 2.1 设计动机

客服类问题经常需要多跳检索：

```text
检索政策
→ 发现缺少适用条件
→ 补充检索产品说明
→ 结合客户只读事实
→ 回答并提供证据
```

完全固定的单步路由难以覆盖这种场景，但自由 ReAct 会带来无限循环、工具越权和成本不可控。折中方案是**有预算的只读 ReAct**。

### 2.2 约束清单

受限 ReAct 的边界（以落地实现的口径为准）：

- 最大 3 轮；
- 最大 3 次工具调用；
- 工具白名单（仅 `search_customer_knowledge`）；
- 默认只读；
- 只有低置信结果允许一次查询精炼，非低置信失败不重试；
- 必须产出 evidence 状态；
- 失败时澄清或人工接管；
- 不记录模型私有推理文本，只记录受控工具调用与结果摘要。

### 2.3 执行语义

首个试点落在 `CustomerTaskExecutor` 的知识类意图中，范围仅限：`company_info`、`company_business`、`faq`、`workflow`、`policy`、`risk_public`（`REACT_INTENTS`）。

```text
retrieve（只读知识检索）
→ observe（仅保留工具结果状态与 evidence 摘要）
→ 对 low_confidence 最多精炼一次查询
→ retrieve
→ answer / clarification / handoff
```

### 2.4 审计与可观测性

执行包含 `bounded_react` 任务时，`CustomerAgentExecutionService` 写入一条 `audit_logs` 记录：

```text
action: customer_service.bounded_react_executed
resource_type: customer_service_conversation
resource_id: conversation_id
```

审计**只记录**：任务 ID、意图、结果状态、受控错误码、工具名、工具调用次数、查询长度、只读标志、"不记录私有推理"标志。

审计**不记录**：用户原始问题、检索内容、模型思维链、完整工具参数、客户业务数据。

这样可以统计 bounded ReAct 的调用次数、失败率、工具预算使用情况和转人工趋势，同时保持金融场景的最小化审计原则。

### 2.5 不适用自由 ReAct 的场景

以下必须保持受控工作流 / 状态机 / Command Handler：

```text
DataAnalysisAgent 的 SQL 模板执行
转账、赎回、申购、订单审核
风险预警处置与 AML 流程
管理员角色、权限和配置写操作
通知投递与外部系统写调用
```

特别是 DataAnalysisAgent："模板选择和参数澄清"可以作为极小范围受限推理，但 SQL 执行始终只能调用批准模板，**禁止模型自由生成或执行 SQL**。

---

## 3. 目录驱动的模板 SQL 执行（NL2SQL 安全边界）

系统没有做自由 NL2SQL，准确说是**目录检索增强的批准模板 SQL 执行**。

### 3.1 数据目录模型

```text
DataCatalogDomain
DataCatalogTable：物理表名、展示名、描述、业务用途、粒度、使用/禁用说明、角色、是否可查询、别名、向量
DataCatalogColumn：字段名、展示名、描述、业务含义、语义类型、单位、敏感性、是否可查询、聚合能力、别名、样例值、向量
DataCatalogRelation：表关系、字段关系、基数、连接说明
DataCatalogExampleQuery：批准问题、意图、目标表/字段、SQL 模板、角色、批准状态、向量
```

数据目录把技术数据库翻译成业务语义层，避免模型只看到物理表名而误用数据。

### 3.2 执行链路

`DataCatalogService.search` 按角色过滤目录，采用文本召回 + pgvector 向量混合召回：

```text
用户问题
→ DataCatalogService.search（角色过滤、文本/向量混合召回）
→ 获取候选表和其可查询、非敏感字段
→ 选择批准模板
→ SQL 实际引用表/字段必须同时通过：模板声明白名单 + 目录召回候选白名单
→ 参数边界、LIMIT、审计
```

### 3.3 安全边界汇总

- 客户不能调用 DataAnalysisAgent；
- 不执行用户直接提供的 SQL；
- 只允许 approved + active 模板（inactive、unapproved、non-queryable table、sensitive column 均被真实 HTTP 门禁验证拦截）；
- 表和字段必须通过模板白名单与目录白名单双重校验；
- 结果最多 100 行；
- 参数必须符合模板 `metadata_json.parameters` 声明式 schema：只有声明为 `natural_language` 的参数从问题文本解析；integer 和 date_range 必须满足模板边界；`authorized_scope_only` 不信任用户文本中的任意 subject ID，由后端授权上下文绑定（`SubjectScopeService` 按 `CustomerAdvisorAuthorization` 授权客户集合解析）；
- 记录受控审计，不记录原始敏感 SQL/参数值。

后续若扩展到受控 NL2SQL 生成，必须保持：仅从目录候选表和字段构造结构化查询计划、人工或策略批准后编译 SQL，禁止模型直接产出可执行 SQL。

### 3.4 策略共享与缓存失效

- `app/services/nl2sql_policy.py` 是不依赖 ORM、数据库、缓存、模型或 FastAPI 启动的纯策略模块，覆盖 SQL-shaped 输入拒绝、批准模板只读校验、固定指标关键词路由、角色允许判断和目录候选范围判断，被 DataAnalysisAgent 与离线评估共同复用，避免镜像逻辑。
- 权限敏感缓存依赖角色/权限指纹 + Redis 中的 `wm:permission-context-version:{user_id}`。管理员更新用户角色后递增该版本，下一次请求产生新 key，旧缓存保留至 TTL 到期但不会被新上下文命中；角色权限变更会递增该角色关联的**全部用户**的版本。这避免了 RBAC 更新后跨命名空间扫描删除的复杂度。

---

## 4. 双管线拆分：客户向与员工向

### 4.1 为什么要拆

后台"Agent 控制台"（员工/投顾/管理员）最初复用客户侧统一 Agent 的同一套执行管线，产生四类真实问题：

| 现象 | 根因 |
|---|---|
| 员工查客户数据被回答"知识库没有足够依据 → 转人工/建工单" | 员工请求被接进客户向的客服兜底，该语义只对真人客户成立 |
| 员工问个人资产问句查不到数据 | 管线按"当前登录者=客户"执行，员工用本人 id 查持仓 |
| 已批准的数据分析模板没跑起来 | 模板 `user_id` 属 `authorized_scope_only`，超管 subject_scope 为空时回退成管理员自身 id，查空后掉进客服兜底 |
| 记忆/身份语义混用 | 员工查询把结果/记忆写到"员工=客户"的桶里，污染客户档案归属 |

结论：不是某一句输入的问题，而是"员工向"和"客户向"共用一条 `意图→执行→兜底→记忆` 管线导致的架构缺陷。

### 4.2 决策与目标架构

决策：**拆分双管道**。备选的小修方案（员工调用时禁用转人工/建工单）改动小但仍是共线，记忆/兜底语义持续混用，被放弃。

**客户向**（保持现状）：

- 入口：客户气泡 / 智能客服（RAG）；
- 意图：客服问答、产品推荐、风控解释、本人申购草稿、本人资产/持仓/订单、转人工；
- 兜底：知识库不足 → 转人工客服 / 建工单（对真人客户合理）；
- 记忆：`customer_id = 客户本人`，写本人 short/long/shared 记忆。

**员工向**（独立执行路径）：

- 身份：登录者 = 员工（内部角色/权限），绝不把员工当客户；
- 查询主体：`target_customer`（正在服务/被点名的授权客户），或权限范围内跨客户聚合；
- 意图集合只保留四类：数据分析（批准模板 + 白名单只读指标）、代客下单草稿、查授权客户资产/持仓/现金、明确"不支持"；
- 兜底：**不接客服知识库、不建工单、不转人工客服**；
- 记忆：读——聚焦某客户时读取该客户 private/shared 记忆作上下文；写——**默认零写入**，仅当服务会话中客户亲口自述低风险偏好时，由客户向以 `actor_user_id` 写入 shared。

### 4.3 落地要点

- 员工（非 customer）账号在数据分析未命中时不再调用 `CustomerAgentExecutionService`，改为返回明确的 `unsupported`；
- 请求带 `target_customer_id` 时，数据分析的 `authorized_subject_ids` 收敛为该目标客户，模板 `user_id` 绑定到被服务客户，而非对超管回退成管理员自己 id；
- 新增 `GET /profile/staff/customer/{user_id}/memory-facts`：员工/投顾按授权（super_admin 任意，否则需 `customer:read_all` 或对该客户有效投顾授权）只读某客户低风险偏好事实与最近会话摘要，仍只读不写；
- 新增 `POST /profile/staff/supervisor/advisor-ask`：把客户共享记忆（risk_preference / product_preference / investment_horizon_preference / active_product + conversation_summary）+ 风险测评等级 + 最新资产/现金组装成上下文，调 Qwen 生成只读、带风险提示、不触发交易、不编造的投顾说明，并支持 SSE 真流式；
- advisor-ask 配套**有界函数调用接地**：只读工具白名单 `{find_products, product_suitability}`，最多 3 轮 `request_tool_call`，工具名+参数落 `AuditLog(action="advisor_agent.tool_call")`，治愈"模型对具体产品凭空编档位/收益率"；采用智能进环——先轻量 `find_products` 探测，仅当题面命中库内在售产品才跑有界工具环，纯画像/开放类问句跳过工具环直接流式。

---

## 5. State 数据流转：两条执行路径

### 5.1 总入口与分流

```text
HTTP POST /api/v1/customer-service/...   或   WebSocket /ws/{conversation_id}
                ↓
    app/api/customer_service.py : _run_customer_agent
                ↓
    ┌────────────┴─────────────────┐
    │ AGENT_GRAPH_ENABLED ?         │
    ├─ false ──► 确定性管线 CustomerAgentExecutionService.execute()  ← 生产默认
    ├─ true  ──► LangGraph SupervisorGraph
    └─ shadow=true ─► 管线照常返回 + 图旁路跑一遍写审计对照
```

要点：

- WebSocket 与 HTTP 复用同一条执行路径，不是两套实现；
- `AGENT_GRAPH_SHADOW_ENABLED` 是对照模式：管线结果照常返回，图的结果用于逐字段比对。

### 5.2 确定性管线（生产默认）

```text
CustomerAgentExecutionService.execute()
│
├─ ① 装载上下文
│    load_short_term()          → 短时记忆（Redis）：clarification_count / pending_intent_plan / active_product
│    load_long_term()           → 长时记忆（PostgreSQL）：白名单事实
│    SharedMemoryService.recall() → 共享记忆：conversation_summary
│    extract_preference_statement() → 用户偏好自述 → memory.remember() 落库
│
├─ ② 规划（规则优先，模型仅兜底）
│    planner.plan(combined_query, context={active_product})
│    [可选，受开关控制] LLM 意图兜底 → IntentPolicyResolver.resolve → 白名单模板改写
│    → IntentPlan{ tasks[], clarification, requires_handoff }
│
├─ ③ 路由分支
│    if plan.clarification: 澄清计数 +1；>= 2 次 → 建工单转人工，否则回澄清
│
├─ ④ 执行（CustomerTaskExecutor.execute）
│    while pending:
│        ready = 依赖全部满足的 task        ← 依赖门控
│        batch = ready[:max_parallel_tasks]
│        asyncio.gather(_execute_one(...))  ← 同层并行
│    _execute_one 按 intent 顺序分派（顺序即优先级）：
│        greeting → human_handoff → REACT_INTENTS（知识类 bounded_react）
│        → business_operation → product_recommendation → unknown
│        → depends_on ∩ {workflow,faq,policy} → explain_* 工具 → 兜底查库工具
│
├─ ⑤ 收尾
│    summarize(results) → (overall_status, clarification, aggregate_answer)
│    if needs_handoff: 建工单/客服会话
│    save_short_term() + remember(active_product)
│    Outbox 入队 memory.summary_extract → memory_worker 异步提炼情景记忆
```

关键实现细节——**检索串与生成串必须分开**：`item.query` 在知识类 task 里是检索串（直接传给 `search_customer_knowledge`），把前序事实拼进它会被当作检索内容，实测 best_sim 从 0.4643 掉到 0.3753（BUG_LOG `DEP-CONTEXT-POLLUTES-RETRIEVAL`）。事实只拼进生成串：

```python
gen_query = item.query
if item.dependency_context:
    gen_query = f"{item.query}{item.dependency_context}"
generated = await CustomerRagAnswerService(...).generate(query=gen_query, result=rag_result)
```

### 5.3 LangGraph 真图（11 节点）

```text
START
  ↓
intent_plan_node              装载短时/长时/共享记忆 → planner.plan()
  ↓ _route_after_intent_plan
  ├─ preference_short_circuit ────────────────► persist_node
  └───────────────────────────────────────────► route_node
                                                    ↓ _route_after_plan
      ┌────────────┬────────────┬─────────────┬──────────────┬────────────┐
      │            │            │             │              │            │
 plan.clarification  ≥2 次澄清  模型工具可处理  只读知识类      其余
      ↓            ↓            ↓             ↓              ↓
 clarify_node  handoff_node  model_tool_node react_step_node execute_node
      │            │            │             │              │
      │            │   _route_after_model_tool │              │
      │            │     ├─ 有结果 → generate_node             │
      │            │     └─ 无结果 → react_step_node           │
      │            │                   ↓ _should_continue_react │
      │            │              继续回环 / react_done_node    │
      │            │                          ↓                 │
      │            │                     generate_node          │
      └────────────┴────────────────────► summarize_node
                                              ↓
                                         persist_node → END
```

路由判据（`_route_after_plan`，按序判断）：

1. `plan.clarification` → 澄清计数 +1，≥2 则 `handoff_node`，否则 `clarify_node`；
2. 模型工具轮启用且 plan 全部由 `MODEL_TOOL_INTENTS` 构成 → `model_tool_node`；
3. 注入了 `react_tool` 且 plan 全为只读知识类 → `react_step_node`；
4. 否则 → `execute_node`。

`model_tool_node` 按 `depends_on` 拓扑分层执行（`_task_layers`，循环/悬空依赖时剩余 task 并入最后一层不丢 task）；每层用 `CustomerModelToolLoop`（模型自主选工具，max_rounds 默认 4），白名单仅 `CUSTOMER_READ_TOOL_SCHEMAS`（8 个只读工具），范围约束为只能调用本层意图映射的工具，重复闸门禁止相同 (工具,参数) 重复执行，覆盖兜底补齐未覆盖意图。检索串保持用户原问句，前序事实以 `prior_facts` 形式只进提示块（"【前序查询结果…不要臆造】"）。

`generate_node` 逐 task 生成：只对 `status == "succeeded"` 且有 citations 的 task 生成；事实工具（无引用）跳过；`policy` / `risk_public` 的生成提示附带角色约束（`_RULE_INTENTS`），禁止对客户个人事实做断言（不得写"您有/您没有…"），因为这类 task 检索的是制度文本。

### 5.4 AgentState 流转规则（踩坑教训）

`AgentState` 共 49 个字段，各节点写入字段经实测导出（节选）：

| 节点 | 写入的 state 字段 |
|---|---|
| 入口 `state_from_request` | `request_id` `trace_id` `user_id` `customer_id` `role` `is_customer` `user_message` `conversation_id` |
| `intent_plan_node` | `plan` `combined_query` `conversation_context` `active_product` `long_term_facts` `pending_intent_plan` `clarification_count` |
| `route_node` | `route` `selected_agents` |
| `model_tool_node` | `model_tool_rounds` `model_tool_names` `model_tool_stopped_reason` `model_tool_decisions` `model_tool_layer_traces` `task_results` |
| `react_step_node` | `react_attempts` `seen_signatures` `seen_signatures_by_task` `react_results` `react_result` `react_query` |
| `summarize_node` | `overall_status` `clarification` `final_response` `needs_handoff` |
| `persist_node` | `persisted`（补建工单、回写短时记忆） |

两条必须知道的规则：

1. **LangGraph 只合并 `AgentState` 已声明的字段**。未声明的顶层键会被**静默丢弃**——不报错、不告警。实测代价：`model_tool_layer_traces` 漏声明时，节点写进去了、直接调节点的单元测试也通过，但经真实图执行后该键不存在。这个缺陷修了两次才发现是 state 未声明。**"节点返回了某键" ≠ "状态里能读到该键"。**
2. **`task_results` 内部的键不会被过滤**。它是自由形态的 dict 列表，内部键不经过 `AgentState` 字段校验，所以需要跨节点中转的数据（如 `data.prior_facts`、`data.layer`）放 `data` 里比放 state 顶层更安全。

### 5.5 overall_status 状态机的局限

| 值 | 含义 |
|---|---|
| `completed` | 全部 task 成功 |
| `partially_answered` | 全部已作答，但答案自述资料不足 |
| `partially_completed` | 部分 task 成功、部分失败/待澄清 |
| `needs_clarification` / `failed` / `handoff` / `blocked_by_human` | 其余分支 |

局限：`CustomerTaskExecutor.summarize()` 的输入只有每个 task 的 `status` 字段，关键分支是 `if succeeded == len(results): status = "completed"`。它只表达**完成度**，不表达**一致性**——两个 task 都成功但答案互相矛盾（如"未显示风险限制"与"是的您有风险限制"并存）仍会判 `completed`。这属于维度缺失，不是判定错误（BUG_LOG `STATUS-MACHINE-LACKS-CONSISTENCY-DIMENSION`）。

### 5.6 两条路径差异对照

| 维度 | 确定性管线 | LangGraph 真图 |
|---|---|---|
| 执行单位 | 每 task 一次 `_execute_one` | `model_tool_node` 按层产出结果 |
| 依赖处理 | `depends_on` 调度门控 | `_task_layers` 拓扑分层 |
| 事实传递 | `_dependency_context` → `gen_query` | `prior_facts`（提示层）+ `data.prior_facts`（生成层） |
| 工具选择 | `TOOL_BY_INTENT` 硬编码 | 模型自主选（白名单内） |
| 知识 task 执行 | `_bounded_react_knowledge` | 复用同名方法 |
| 答案生成 | 内联在 `_execute_one` | 独立 `generate_node` |
| 状态机 | `CustomerTaskExecutor.summarize` | 同一个 `summarize`（复用） |

共享的底层：`CustomerIntentPlanner`、`CustomerRagAnswerService`、`CustomerTaskExecutor.summarize`、记忆读写、`CustomerRagHandoffService`。**两条路径差异在编排方式，不在能力实现。**

### 5.7 渐进式开关

| 开关 | 代码默认 | compose 部署默认 | 作用 |
|---|---|---|---|
| `AGENT_GRAPH_ENABLED` | `False` | `false` | 图作为权威路径（替换管线） |
| `AGENT_GRAPH_SHADOW_ENABLED` | `False` | `false` | 管线返回 + 图旁路对照写审计 |
| `AGENT_CHECKPOINT_ENABLED` | `False` | `false` | Postgres 断点续跑（`thread_id=conversation_id`） |
| `AGENT_MODEL_TOOL_SELECTION_ENABLED` | **`True`** | **`false`** | 只读查询的模型自主工具调度 |

注意最后一行不一致：代码默认 `True`、compose 覆盖 `false`——本地直跑会启用模型工具轮，容器内默认关闭，排查时容易误判。

---

## 6. 受控子代理并行层

### 6.1 定位与边界

现有 `CustomerTaskExecutor` 已实现**任务级并行**（`asyncio.gather` + `max_parallel_tasks=4`）。缺的是"子代理并行"：派多个独立的 LLM 子代理（每个有自己的推理循环 + 工具预算 + 只读范围）并发跑，各自返回结构化结果，由 Supervisor 用确定性规则融合。

核心原则一句话：**"部分领域可以并行，严格场景必须确定性。"** 判定依据是子任务是否会改变业务事实/触发写操作/产出高风险结论。

### 6.2 并行边界矩阵

| 子任务类别 | 可并行? | 原因 / 约束 |
|---|---|---|
| 风控事实分析 | ✅ | 只读；子代理只出"分析"，不出"处置结论" |
| 产品/适当性解释、推荐说明 | ✅ | 只读；最终适当性由 `SuitabilityService` 裁决 |
| RAG 多路检索/多问题评测 | ✅ | 只读；天然可分片 |
| 客户画像/持仓只读分析 | ✅ | 只读 + SubjectScope 限定 |
| 订单创建/确认/冻结 | ❌ 绝不 | 写操作，走确定性 `trading_service` |
| 资金/赎回/转账 | ❌ 绝不 | 写操作 + 幂等 + 人工 |
| 风控最终结论/限制解除 | ❌ 绝不 | 高风险，走 `risk_alert` 状态机 + 人工 |
| 任何跨库/跨客户聚合写回 | ❌ 绝不 | 权限边界 |

子代理并行层只暴露只读工具（`CustomerReadTools` 只读子集 + `DataAnalysisAgent` 只读模板/指标），写工具不注册给子代理。

### 6.3 组件设计

架构位置：

```text
api/customer_service.py
 → CustomerAgentExecutionService（Supervisor）
   ├─ [现状] CustomerTaskExecutor（任务级并行，确定性 handler）
   └─ [新增] SubagentExecutor（子代理级并行，只读领域分析）
          ├─ 子代理 A（风控只读分析）
          ├─ 子代理 B（产品/适当性解释）  ← asyncio.gather 并行
          └─ 子代理 C（RAG 检索解释）
          └─ 确定性融合（Supervisor 裁决） → 聚合回答
```

三层职责划分（各司其职，互不越界）：

| 模块 | 职责 | 不负责 |
|---|---|---|
| `subagent_planner.py` | 请模型决策"拆几个只读子任务、能不能并行"；解析/收敛越界输入 | 不执行工具、不碰 DB 数据 |
| `subagent_runner.py` | `read_only_capability` → `CustomerReadTools` 的真实映射 + 答案生成 | 不决定拆几个、不管并发 |
| `subagent_executor.py` | 并发/超时/降级/融合/审计 | 不知道 capability 对应哪个工具 |

关键设计决策（每条有实测依据）：

1. **单一工具 + enum capability**：只声明 `dispatch_read_tasks`，模型不选工具（无从越界），只决定拆几个/能否并行；capability 值域直接取 `READ_ONLY_CAPABILITIES`，模型物理上无法编造写操作能力名。
2. **模式以 `depends_on` 为准，不采信模型自报的 `mode`**：实测模型在"先查限制再解释"用例上正确填了 `depends_on` 却把 mode 写成 parallel；只信 mode 会把有依赖的子任务并发跑，结果错误。
3. **串行模式必须拓扑排序下发**：`Semaphore` 只限流不排序，模型返回的列表可能倒序。
4. **知识类子任务必须接 answer generator**：工具返回"引用 + 占位串"，不接生成会得到"状态 success、内容为空"的假成功。
5. **超时预算按真实工作量定**：知识类 = 检索 + 生成，实测 11.5s，故 `DEFAULT_PER_TASK_TIMEOUT_S=20.0`（初版 8.0 必然超时）。
6. **并行模式不注入前序事实**：并行子任务互不依赖，注入会引入非确定性。

### 6.4 并发控制、融合与降级

- 并发控制：`asyncio.Semaphore` 限制 `max_concurrent`（默认 2-3），每个子代理独立超时（`asyncio.wait_for`）+ 全局超时；
- 融合：**确定性规则**——按任务类型选择合并策略（并集/最相关/冲突裁决）；多个子代理结论冲突时不以"多数票"定论，标注冲突交人工/确定性规则裁决；业务事实结论一律以确定性 Service 为准；
- 降级：子代理超时/失败 → 该子任务标 `partial` / `failed`，其余结果保留；影响整体回答时降级为确定性兜底或转人工，不让失败子代理拖垮整个请求；
- 审计：`AuditLog(action="subagent.ran")` 记录子代理名、task_id、tool_call_count、`private_reasoning_logged: False`、只读标记；
- 安全边界已验证：模型返回 `create_order` / `transfer_money` 时不会发生任何对应工具调用；`customer_id` 由服务端注入并覆盖模型提供的值（防越权读他人数据）。

### 6.5 开关与实测收益

开关 `AGENT_SUBAGENT_FANOUT_ENABLED`（代码与部署默认均为 `false`）：

- 关闭时：`run_read_only_fanout` 不调用模型决策，直接退化为串行单任务，`source=disabled`；
- 开启时：请模型决策拆分与并行性（`source=model`；模型未给可用任务时 `fallback_serial`）；
- 三种 source 值互相可区分，避免"开关关着"看起来像"模型又失败了"。

该入口目前只被显式调用，既有 `execute()` 管线与 LangGraph 图均未改为走此入口，开关打开也不会改变线上会话行为。

实测收益（3 个独立知识检索子任务）：

| 模式 | 耗时 |
|---|---|
| 串行 `max_concurrent=1` | 8969 ms |
| 并行 `max_concurrent=3` | 2469 ms |
| **收益** | **降低 72.5%（3.63x）** |

验收标准：可并行场景总延迟显著低于串行；越权/写操作 = 0；子代理失败不拖垮整体；每个子代理结果可审计、可溯源、可恢复；严格场景确定性流程行为不变。

一句话总结这套设计：**并行的是"分析"，不是"决策权"。**

---

## 7. 理解层可配置与难度模型路由

### 7.1 一句话架构

> 模型负责理解，规则负责执行。理解层的所有旋钮（提示词、few-shot、top_k、知识文档、意图映射、难度模型路由）都做成运行时配置、可被模型自调；执行层的闸门（权限/风控/确认/幂等/审计/写操作）锁死在固定轨道，任何配置/模型都改不了。

```text
理解层（可配置、模型可自调）
  提示词 / few-shot / 意图映射 / 工具schema / 检索参数(top_k) / 知识文档范围 / 难度模型路由
        ↓ 模型自调（auto-repair 改配置，人工门控+灰度+回滚）
执行层（固定轨道、模型不可改）
  权限 / SubjectScope / 适当性 / 风控 / 确认令牌 / 幂等 / 审计 / 写操作
```

### 7.2 理解层可配置项

| 配置项 | 示例 | 影响 | 模型能否自调 |
|---|---|---|---|
| 系统提示词 | 意图解析 prompt | 该 Agent 所有推理 | ✅ |
| few-shot 示例 | 多意图/否定示例 | 对齐意图体系 | ✅ |
| 意图映射 | `INTENT_ALIASES` / `INTENT_KEYWORDS` / `INTENT_TO_TEMPLATE` | 模型输出→规范码 | ✅ |
| 工具 Schema | `INTENT_TOOL_SCHEMA` | 结构化输出约束 | ✅ |
| 检索参数 | `top_k`、RRF k、相似度阈值 | RAG 召回 | ✅ |
| 知识文档范围 | 某意图检索哪个库/分类 | 召回命中 | ✅ |
| 难度模型路由 | 简单→小模型，复杂→大模型 | 成本/质量 | ✅ |

全部运行时读取，改配置即生效，不需改代码/部署。存储于 `config/understanding.yaml`（或 DB），支持热刷新、版本化快照与一键回滚。

### 7.3 难度模型路由

不是所有请求都要最强模型：简单意图用小模型（快、省、稳），复杂/多意图/模糊用大模型（准）。

| 难度 | 判定 | 模型 |
|---|---|---|
| S（简单） | 规则置信度高、单意图、明确 | `qwen-turbo` |
| M（中等） | 多意图、需检索、略模糊 | `qwen-plus` |
| L（复杂） | 否定/指代/歧义/对抗/长句 | `qwen-max` |

判定信号（可配置权重）：规则置信度（`_patterns` 的 confidence）、意图数量（单/多意图）、是否含否定/歧义/连词（正则标记）、是否有缺参需澄清。

路由配置外部化：

```yaml
model_routing:
  default: qwen-plus
  tiers:
    - {max: "S", model: "qwen-turbo"}
    - {max: "M", model: "qwen-plus"}
    - {max: "L", model: "qwen-max"}
```

### 7.4 模型自改路径与安全边界

模型自调闭环（飞轮）：

```text
评测集 → 失败案例 → auto_repair 生成修复候选(Diff) → 写入 config/understanding.yaml
       → 校验(结构/白名单/不越界) → 人工门控 → 灰度 → 回滚 → 重跑评测
```

- 校验：模型写的配置必须过 schema 校验 + 白名单，不能引入非法值/越界；
- 门控：关键变更（模型路由、提示词大改）需人工审批，小变更（关键词增补）可自动；
- 灰度 + 回滚：先小流量，异常即回滚。

执行层闸门为什么模型不可改：

| 执行层闸门 | 原因 |
|---|---|
| 权限 / RBAC / SubjectScope | 模型改了就=越权 |
| 适当性 / 风控 / 确认令牌 / 幂等 | 模型改了就=绕过合规 |
| 审计 / 日志 | 模型改了就=掩盖 |
| 写操作 / 资金 / 订单 | 模型改了就=直接动钱 |
| `ILLEGAL_MUTATION` / 交易永不升级 / `must_not_submit` | 模型改了就=削弱防注入/防越权 |

实现保障：执行层闸门硬编码在代码里，且不在模型可写的配置域内。配置系统只开放理解层域，执行层配置不可被 auto-repair 写入（写白名单限制）。

---

## 8. 设计原则总结

1. 权限先于 Agent 路由；
2. 低风险解释可以使用 bounded ReAct；
3. 高风险业务使用 controlled workflow；
4. 模型负责理解、规划和解释，不负责自行改变业务事实；
5. 数据目录是 NL2SQL 的语义和权限边界；
6. 缓存也必须权限感知；
7. 拒答、澄清、延迟和安全事故都必须可评估（P2 六维评估：语法正确率、语义准确率、拒答率、澄清触发率、P95 延迟、安全事故数）；
8. 理解层开放、执行层封闭——模型能优化自己怎么理解，但永远改不了自己能不能执行。
