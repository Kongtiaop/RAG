# 多 Agent 记忆架构

> 来源:
> - `多 Agent 共享记忆设计方案.md`（主设计：分层模型、数据模型扩展、统一写入/检索 API、聚合 Worker、作用域权限矩阵）
> - `记忆链路全链路落地与踩坑复盘.md`（落地现状：短期/长期/共享记忆接入链路、Outbox→Redis Streams→Worker 的 L3 摘要闭环、五个真实踩坑、已实现 vs 规划对照）
> - `TencentDB Agent Memory .md`（方法论参考：三代记忆架构演进、L0-L3 金字塔、冲突仲裁、遗忘策略、版本化）
> - `_draft_memory_outbox.md`（Outbox/Redis Streams/Worker 机制细节：表结构、消费组、幂等、死信、设计取舍）
>
> 说明: 由 wealth-manager 项目文档按主题重写，重写于 2026-10-08。源文档间存在新旧口径冲突，本文以较新的落地复盘（2026-09-04）为准：长期记忆已接入关键事实写入与跨会话回读（draft 中"长期记忆零接入"为过时表述）；记忆唯一索引实际为 `(customer_id, key, scope)` 三列（draft 中漏写 scope 为误记）。共享记忆设计方案为设计蓝图，落地时表结构有简化（如当前为覆盖更新而非 valid_from/valid_to 版本化），本文分别注明"设计"与"落地"口径。

---

## 1. 方法论基础：记忆系统与向量检索的区别

### 1.1 三代 Agent 记忆架构

| 代际 | 名称 | 核心机制 | 解决了什么 | 暴露了什么 |
|---|---|---|---|---|
| Gen1 | RAG 记忆 | 对话切块 → Embedding → Top-K 检索 | 跨会话"想得起来" | 无 update 语义、无冲突消解、无时间语义 |
| Gen2 | 结构化记忆 | LLM 抽取(主体, 属性, 值, 生效时间)，同 key 旧事实标记失效 | update、冲突消解、时间语义 | 事实是孤岛，跨实体多跳查询乏力 |
| Gen3 | 记忆图谱 | 实体+关系边+事件，向量召回+图遍历+事件相似度三路并发 | 多跳推理、关系追溯、可解释 | 需要图存储和抽取算力，工程复杂度高 |

**关键洞察**：每次换代都在把"生成层的负担"前移到"记忆层"——Gen1 把矛盾甩给模型现场判断；Gen2 在写入时就把矛盾消解掉；Gen3 更进一步，把实体关联在写入时建好。

核心定位：**RAG（向量库）是"记忆的素材库"，不是记忆本身。**

| 维度 | RAG（Gen1） | 结构化记忆（Gen2） |
|---|---|---|
| 存储单元 | 对话 Chunk | 结构化事实卡片 |
| 核心操作 | Insert + Search | 写入 → 提炼 → 检索 → 更新 |
| 冲突处理 | 无，矛盾甩给模型 | 冲突仲裁（新增/跳过/覆盖/合并） |
| 时间语义 | 无，余弦相似度不认时效 | 双时态（valid_from/valid_to） |
| 更新语义 | 新记录只是"多了一条" | 同 key 旧事实标记失效 |

### 1.2 选型决策链

| 判断问题 | 是 → | 否 → |
|---|---|---|
| 信息会被用户/环境更新吗？ | 需要记忆系统（至少 Gen2） | Gen1（知识库）够用 |
| 存在"新信息应覆盖旧信息"吗？ | Gen2+ | Gen1 够用 |
| 有跨实体关联查询需求吗？ | 考虑 Gen3 | Gen2 停住 |
| 日活对话量撑得起图谱抽取成本？ | Gen3 可行 | Gen2+ 向量兜底 |

本项目采纳边界：L0/L1 已实现，L2 场景档案与 Gen3 记忆图谱为规划项（P4/P5 后按真实需求评估）。

---

## 2. 分层记忆模型

### 2.1 L0-L3 记忆金字塔（方法论口径）

| 层级 | 名称 | 内容 | 更新策略 | 类比 |
|---|---|---|---|---|
| L0 | 原始流水 | 对话原文，一字不改 | 实时落盘（毫秒级） | 录音笔/流水账 |
| L1 | 记忆卡片 | 结构化事实（偏好/事件/规则） | 异步提炼（约 6-10 秒） | 会议纪要便签 |
| L2 | 场景档案 | 同一情境下的卡片打包 | 按情境组织，不按日期 | 项目专属文件夹 |
| L3 | 人格摘要 | 稳定的用户画像 | 定时/事件触发（周/月级） | 用户简历 |

分层隔离、各自采用不同更新策略：L3 核心人格放 System Prompt（缓存友好），L2 场景摘要日级增量，L1 原子事实实时/事件触发，L0 实时写入。**Agent 推理流程：先看 L3 定基调，再查 L0/L1 做决策。**

### 2.2 设计蓝图：四层存储架构

共享记忆设计方案的分层模型：

```text
┌────────────────────────────────────────────────┐
│                Agent 执行层                     │
│   CustomerService / Advisor / Risk / Analysis  │
└────────────────────────────────────────────────┘
                      ↓
┌────────────────────────────────────────────────┐
│        内存层（会话级工作记忆）                   │
│   Redis：当前会话上下文、TaskPlan、临时状态      │
│   生命周期：会话结束即清除                       │
└────────────────────────────────────────────────┘
                      ↓
┌────────────────────────────────────────────────┐
│        缓存层（Agent 级短期记忆）                 │
│   Redis：高频访问记忆、近期检索结果，TTL 7 天    │
└────────────────────────────────────────────────┘
                      ↓
┌────────────────────────────────────────────────┐
│        I/O 层（持久化存储）                      │
│   PostgreSQL：所有记忆的持久化存储，按过期策略   │
└────────────────────────────────────────────────┘
                      ↓
┌────────────────────────────────────────────────┐
│        聚合层（组织级认知）                       │
│   离线 Worker：将个体观察聚合为组织级洞察        │
│   输出：组织级记忆（scope=organization）         │
└────────────────────────────────────────────────┘
```

### 2.3 落地口径：两层物理存储 + 一个共享语义层

实际落地是**两套物理存储 + 一个共享语义层**：

| 层 | 存储 | 表/接口 | 生命周期 | 角色 |
|---|---|---|---|---|
| 短期 | Redis JSON | key=`customer:memory:short:{customer_id}:{conversation_id}`，TTL 1800s | 随会话结束/转人工清理 | 澄清上下文、pending_plan、handoff 状态、clarification_count |
| 长期 | PostgreSQL | `customer_memory`（记忆卡片）+ `customer_memory_event`（事件审计） | 跨会话保留，status 软失效 | 客户事实卡片 |
| 共享语义层 | PostgreSQL | 基于 `customer_memory` 的 scope/agent_type 过滤 | 跨 Agent 复用 | 让一个 Agent 的观察可被其它 Agent 安全复用 |

Redis 与 PostgreSQL 的职责对比：

| 维度 | Redis 短期 | PostgreSQL 长期 |
|---|---|---|
| 内容 | 澄清上下文：`original_query`、`clarification`、`missing_parameter`、`clarification_count`、`pending_intent_plan`、`handoff`、`conversation_summary` | 只允许白名单低风险类型：`confirmed_parameter`（客户确认参数）、`service_preference`（服务偏好）、`conversation_fact`（非敏感会话事实） |
| 一致性 | 会话状态缓存，允许丢失 | 业务事实库；**业务事实表永远高于记忆**（风险/资产/持仓等不得以记忆为最终依据） |
| 降级 | `redis=None` 时读写为空操作（graceful） | 依赖 PG 事务 |

设计语义：Redis 是快速恢复上下文的缓存，不是长期事实库；客服转人工/会话结束/超时会清理短期记忆，PG 留档不丢。一个管"这一轮聊到哪"，一个管"这个客户已知什么"。

L0-L3 落地映射：L0 对应现有业务表（会话/消息/审计记录），不由模型改写；L1 对应 `CustomerMemory` 表+服务；L2 场景档案纯规划；L3 稳定摘要已通过异步提炼闭环实现（见 §6）。

---

## 3. 共享与隔离边界

### 3.1 作用域模型

记忆按三级作用域共享/隔离：

```text
private       仅写入 Agent 可见
shared        同客户的所有授权 Agent 可见
organization  所有 Agent 可见（组织级洞察，不绑定具体客户）
```

记忆按**客户主体**分桶；员工读到的是"我正在服务/被点名的那位客户"的记忆（带授权范围）。应然的记忆规则：

1. **读 = 上下文**：服务客户时注入其 private/shared 记忆（风险偏好、活跃产品、目标等）；
2. **写受限 + 归因 + 审计**：仅当客户在服务会话中**亲口自述**低风险偏好时，由客服/投顾以 `actor_user_id` 写入 shared 供其它 Agent 复用；员工随手做的分析探针**绝不写客户记忆**；
3. 记忆只是建议，不绕过权限/风控/确认门禁。

### 3.2 作用域访问矩阵

| Agent | 可写作用域 | 可读作用域 |
|---|---|---|
| CustomerServiceAgent | private, shared | private, shared, organization |
| AdvisorAgent | private, shared | private, shared, organization |
| RiskAgent | private, shared | private, shared, organization |
| DataAnalysisAgent | shared | shared, organization |
| BusinessAgent | private | private, organization |
| aggregation（聚合 Worker） | organization | organization |

落地实现（`shared_memory_service.py` 的 `AGENT_MEMORY_PERMS`）：customer_service 与 advisor/risk 可写 shared；recommendation/risk/trade 只写 private；data_analysis 专用 shared/organization。`remember` 按 Agent 可写作用域校验，`recall` 按可读作用域过滤并写审计（`shared_memory.write`）。

### 3.3 权限校验实现

写入时强校验 + 读取时软过滤，处处生效。核心规则：

- `can_write(agent, scope, customer_id)`：先查 Agent 的可写作用域白名单；`shared` 作用域还需 `SubjectScopeService.has_access(agent, customer_id)` 客户授权；
- `can_read(agent, scope, customer_id)`：同理，读取时过滤 `valid_to IS NULL` 且 `expires_at > now()` 的当前有效记忆；
- 记录消费：检索命中的记忆把当前 Agent 追加进 `consumed_by`，实现消费追踪。

与现有权限框架的集成：`AgentCapabilityRegistry` 扩展 `MEMORY_PERMISSIONS` 做记忆权限前置；`PermissionScopedCache` 复用为记忆读取缓存；`SubjectScopeService` 复用为客户数据范围。

安全边界：只存白名单、低风险 memory_type 的观察；不共享模型私有推理链/原始敏感数据；任何一环 write/read 失败（embedding、LLM 摘要、shared.recall）都被 try/except 包裹，只降级、绝不影响主对话/转人工。

---

## 4. 数据模型

### 4.1 落地表结构

`customer_memory`（`app/models/memory.py`）：

| 字段 | 说明 |
|---|---|
| `id` | String(36) 主键 |
| `customer_id` | FK → `users.id`，CASCADE，索引 |
| `memory_type` | String(32)，默认 `conversation_fact`，索引 |
| `key` / `value` | 记忆键 / 内容 |
| `source` | String(32)，默认 `conversation` |
| `confidence` | float |
| `status` | String(24)，默认 `active`，索引（支持软失效） |
| `scope` | private / shared / organization |
| `agent_type` | 写入方 Agent |
| `last_confirmed_at` | 最近确认时间 |
| `expires_at` | 可空——预留过期能力 |
| `created_at` / `updated_at` | 审计 |

**关键约束——部分唯一索引 `uq_customer_memory_active_key(customer_id, key, scope) WHERE status='active'`**：同一客户**同一 key + 同一作用域**只允许一条 active 记忆。注意唯一键含 `scope`——相同 key 可分别以 private 与 shared 各存一份，这是"共享不覆盖私有"抽象的数据库层保障。

`customer_memory_event`：记录每次变更的来源事件（event_type / payload / conversation_id / memory_id），实现审计留档，与业务流水解耦。

### 4.2 设计蓝图中的扩展字段

共享记忆设计方案为 `CustomerMemory` 规划的字段（部分已落地，部分待版本化改造）：

- 来源追溯：`source_id`（conversation_id / task_id / work_order_id）、`source_type`（conversation | task | workorder | aml_batch）；
- 时间语义：`valid_from` / `valid_to`（None 表示当前有效）/ `expires_at`（硬过期）；
- 冲突关联：`superseded_by`（被哪条新记忆替代）、`conflict_with`（冲突的记忆 ID 列表）、`related_memory_ids`；
- 消费追踪：`consumed_by`（已消费此记忆的 Agent 列表）。

设计中的 `MemoryType` 枚举：`observation`（Agent 直接观察）、`inference`（Agent 推理得出）、`external_input`（外部输入）、`aggregated_insight`（聚合洞察）。

---

## 5. 写入、检索与衰减机制

### 5.1 统一写入 API

所有 Agent 通过统一入口写入记忆，确保权限校验和审计：

```text
写入流程：
1. 权限校验：该 Agent 是否有权写入该作用域
2. 冲突检测（scope=shared）：查找同主题活跃记忆，
   置信度更高的新记忆替代旧记忆（旧记忆 valid_to=now、superseded_by 指向新记忆）
3. 创建新记忆（带来源、时间、置信度）
4. 持久化
5. 审计（memory.write）
6. 异步 Embedding（复用现有知识库 Worker）
```

落地的长期写入语义（`CustomerMemoryService.remember`）：**upsert**——active key 已存在则更新 `value/source/confidence/last_confirmed_at`，不存在则插入；**同一事务内**追加一条 `CustomerMemoryEvent(event_type="upsert")`。便捷方法 `remember_confirmed_parameter` 对应"客户明确确认的参数"写入边界（confidence=1.0）。

已接入的真实写入点：

- `customer_agent_execution.py`：客户明确自述偏好持久化为 `conversation_fact`（source=customer_stated）；本轮活跃产品持久化供后续"那个产品"指代消解；
- `profile.py`：风险测评后写 `risk_preference`。

### 5.2 统一检索 API

```text
检索流程：
1. 构建过滤条件：可读作用域白名单、agent_type、客户授权校验、memory_type
2. 过期过滤：valid_to IS NULL 且 expires_at > now()
3. 检索：优先向量检索（pgvector），降级关键词检索
4. 记录消费：命中的记忆写入 consumed_by
```

方法论上的检索路径（TencentDB 口径）：关键词检索（BM25 字面匹配）+ 语义检索（向量）融合排序；语义指纹用于自然语言同义表达，混合检索为默认推荐。

读侧的接入：

- `load_long_term()` 只取白名单低风险键（`long_term_facts`），用于澄清补参与上下文组装；
- 员工/投顾 `GET /profile/staff/customer/{user_id}/memory-facts` 按授权只读被服务客户的共享记忆档案（advisor 的 observation 与客服侧 conversation_summary），授权规则：super_admin 任意，否则需 `customer:read_all` 或对该客户有效投顾授权；
- advisor workbench 与客户执行链路：推理时把客户共享的 `conversation_summary` 与 observation 作为上下文注入。

### 5.3 冲突仲裁与遗忘（方法论 + 落地）

冲突仲裁两阶段：候选召回（新卡片转语义指纹，找最近邻）→ 模型判断（新增/跳过/更新/合并）。**关键约束：模型只能看到召回到的候选，未召回的旧卡片等于不存在。**

"遗忘"的核心原则：**遗忘是检索降权，不是物理删除。**

| 策略 | 实现方式 |
|---|---|
| 存储层不遗忘 | L0 原始流水永不删除，按时间分区归档 |
| 检索层衰减 | `最终得分 = 相似度 × 时间衰减系数`（指数/对数衰减） |
| 场景层强制唤醒 | 风控、投诉、大额交易等场景绕过时间衰减，全量召回 |
| 关键数据永不丢 | L3 核心画像永久保留，L2 场景可汇总，L0/L1 可归档 |

防"旧政策/旧快照当事实"的落地做法是**职责分离 + 业务表优先**：订单/余额/持仓等权威事实永远从 PostgreSQL 业务表读，不走记忆；`conversation_summary` 等记忆只做上下文；`status='active'` 过滤保证取当前生效；软失效用于纠错。

版本化（覆盖的替代方案）：新记忆不覆盖旧记忆，而是为旧记录打"过去式"标签：

```sql
-- 不是 UPDATE，而是：
INSERT INTO customer_risk_assessment_history (user_id, risk_level, valid_from, valid_to)
VALUES
(123, 'R3', '2024-01-01', '2026-08-10'),  -- 旧记录标记失效
(123, 'R4', '2026-08-11', NULL);          -- 新记录生效
```

落地现状：长期记忆目前是"覆盖更新"（无 valid_from/valid_to 版本化），`expires_at` 预留但尚无后台过期清理任务；若后续做版本化记忆卡片需补列与清理 worker。

---

## 6. Outbox 异步落库与 Worker 体系

### 6.1 为什么异步化

1. **主链路延迟**：LLM 摘要、embedding、通知等副作用慢且有外部依赖，同步会拖垮 HTTP 响应——"对话主链路优先返回，记忆提取通过 Redis Streams 异步处理"；
2. **可靠投递、不要分布式事务**：业务行与 outbox 行同本地事务原子提交 ⇒ 业务成功事件必达；避免跨 DB/跨 Redis 的 2PC；Redis Pub/Sub 不持久化会丢消息，Streams + 消费组才有持久化+重放+崩溃恢复；
3. **至少一次 + 幂等消费兜底**：重复不可避免（publish 与 mark 分事务），用业务幂等键 + 唯一索引把"恰好一次"降级为"至少一次 + 幂等"；
4. **解耦与独立伸缩**：每个 worker 独立进程、独立消费组、独立扩缩容；
5. **可审计、可重放、可人工干预**：outbox 表本身就是投递审计（status/attempt/error/published_at），admin 可查 dead 并人工重试。

### 6.2 Outbox 表与产出方

`outbox_event` 表：`id`(UUID)、`event_type`(索引)、`aggregate_type`、`aggregate_id`、`payload_json`(JSONB)、`status`(pending/published/dead，索引)、`attempt`(默认 0)、`error_message`、`published_at`、时间审计。

事务内写业务 + outbox 的产出方（业务与事件**同一个数据库事务** commit，保证"业务成功 ⇒ 事件必落库"）：任务创建（`task.created`）、客服消息通知（带 `idempotency_key=event_key`）、投顾授权失效（`authorization.subject_scope_invalidate`）、知识文档创建（`knowledge.document_created`）、目录 embedding 请求（`data_catalog.embedding_requested`），以及记忆链路的 `memory.summary_extract`。

### 6.3 outbox_worker：DB 轮询型搬运工

`OutboxPublisher.publish_once` 流程：

1. `SELECT ... WHERE status='pending' ORDER BY created_at LIMIT 20 FOR UPDATE SKIP_LOCKED`——行锁+跳过已锁行，多实例并发安全；
2. 先 `attempt += 1` 并 commit——把"认领"落库，崩溃后不重复计数错乱；
3. 逐个 `queue.publish(stream, payload)`，流按 `event_type` 前缀路由（`memory.`→memory、`risk.`→risk、`knowledge.`→ingestion、`notification.`→notifications 等，其他→tasks）；
4. 成功标记 published 并把 Redis `message_id` 写回 payload_json；
5. 失败：`attempt >= task_max_attempts(3)` → `status=dead`，否则回 `pending` 等待下轮重试；`error_message` 截断 4000 字符。

主循环无 pending 时 sleep 1s 再轮询——**outbox_worker 是全系统唯一的 DB 轮询型 worker**，其余 worker 全部走 Redis Streams 消费组。

### 6.4 Redis Streams 消费组

`RedisStreams`（`app/tasks/streams.py`）：

- `ensure_group`：`XGROUP CREATE stream group 0 MKSTREAM`，`BUSYGROUP` 幂等；
- `publish`：`XADD ... MAXLEN ~10000`（近似裁剪，控制内存）；
- `consume_once`：`XREADGROUP GROUP g CONSUMER c STREAMS s ">" COUNT 10 BLOCK 5000`——阻塞式消费，非空转轮询；
- `claim_pending`：`XPENDING_RANGE` + 对 `time_since_delivered >= 30000ms` 的消息 `XCLAIM`——崩溃消费者恢复机制：worker 挂掉后其未 ack 消息 30 秒后由同组其他消费者接管；
- 异常时不 ack，消息留在 PEL（pending entries list）等待 claim 重试。

流命名 `stream:wealth:{tasks|notifications|ingestion|authorization|risk|memory|catalog|dead-letter}`，消费组 `wealth-workers[-notifications|-knowledge|-authorization]`。

### 6.5 L3 稳定摘要：记忆链路的异步闭环

这是记忆体系中最典型的 Outbox 应用——对话摘要的递进提炼全链路：

```text
对话执行完成
→ 每轮入队 memory.summary_extract（写 outbox，同事务 commit）
   payload: customer_id / conversation_id / 本轮诉求 / 结果 / active_product / 低置信转人工原因
   入队失败不阻塞主流程
→ outbox_worker 搬运到 Redis :memory stream
→ memory_worker 消费（消费组 wealth-workers-memory，claim_pending + consume_once 崩溃可接管）
→ 受控 Qwen 生成结构化 JSON 摘要（仅 concern/resolved/pending/preference_hint，
   禁止敏感明细与编造；读取已有 summary 做合并更新——递进提炼）
→ 落 shared 记忆（conversation_summary）
```

可靠性设计要点：

- **注册入队可靠性**：入队走 outbox（业务同事务），保证"对话处理成功 ⇒ 摘要事件必落库"；
- **至少一次 + 幂等**：摘要重复投递安全（upsert 语义），重复提炼只有轻量重复；
- **异常安全**：LLM 摘要生成失败则跳过，**绝不阻塞转人工**；
- **生成失败降级**：任何一环失败都被 try/except 包裹，只降级不影响主对话。

### 6.6 死信与人工干预

- Outbox 层：dead 终态事件可在 `/admin/outbox-events?status=dead` 查询并人工 `retry`（写审计 `outbox_event_retry`）；
- 任务层：`AsyncTask` 状态机 `queued → running → success`；`running → failed`（attempt < max_attempts 可重试）→ `running → dead`（终态），终态时把 `{task_id, task_type, error}` 发布到 `stream:wealth:dead-letter` 死信流；
- 幂等消费双层兜底：先查后插（按 `user_id + idempotency_key` 查已存在则跳过）+ 数据库部分唯一索引兜底（并发重复插入触发 `IntegrityError` → rollback）。

---

## 7. 聚合机制：个体观察 → 组织级认知

多个 Agent 的零散观察经离线 Worker 聚合为组织级洞察（scope=organization）：

```text
客服 Agent：这类客户总问同一个问题
技术 Agent：同一类 bug 反复出现
风险 Agent：同一类资金模式频繁触发预警
        ↓ 聚合层
组织级洞察：这类用户的使用场景存在系统性缺陷，建议产品改进
```

`MemoryAggregationWorker` 流程：

1. 读取最近 7 天的共享记忆（scope=shared、memory_type=observation），样本 < 5 条则跳过；
2. 按主题关键词 + 客户类型聚类；
3. 每个聚类（≥3 条样本）用 LLM 生成洞察摘要（共同主题 / 可能原因 / 建议行动，不超过 200 字）；
4. 写入组织级记忆：`user_id=None`（不绑定具体客户）、`memory_type=aggregated_insight`、`scope=organization`、`source_id` 记录来源观察 ID 列表、TTL 90 天、confidence=0.7。

调度：每天凌晨 2 点 cron 运行；独立 aggregation-worker 进程（compose profile 隔离）。

---

## 8. 踩坑复盘要点

五个真实踩坑（均钉到代码/git 历史/ISSUES）：

### 坑 1：长期记忆长期"服务就绪、Agent 零接入"（低估接线工作量）

记忆服务层（表/upsert/事件）最早就有，但长期记忆的 `remember()` 与 `load_long_term()` 在业务链路里一度没有任何调用方。根因：记忆"模块写完"与"在客服统一问答收口前把事实读进/写进对话"是两件事——接入需要身份为主体的 read/write 契约、确认边界、白名单键、幂等，早期只接了短期记忆，长期记忆被"设计完成"掩盖为"落地完成"。

启示：分辨"某某 layer 建了表/写了 service"与"某某链路真正把记忆用起来了"。

### 坑 2：员工/投顾分析一度也往"客户记忆/工单/转人工"里写（角色边界混淆）

迭代早期，员工向的处理结果沿客户向客服逻辑"落客服知识库断言 / 转人工 / 建工单 / 写客户记忆"，内部员工分析被误当作客户会话侧写。修复：员工分析与客户向拆开（员工分析未命中返回 unsupported）；gate customer memory to customers only，给员工/投顾加 subject-scope 授权，投顾只能按授权被服务客户只读共享档案。

启示：记忆的"写方是谁、读方是谁、可读哪个 subject/作用域"必须在接入时就按角色收紧，否则会把内部角色上下文污染进客户记忆，也会让越权成为隐患。

### 坑 3：记忆注入入口的并发死锁

对 `/profile/me`（记忆事实 + 风评 + 持仓的读取合成接口）做 50 并发压测出现 500。根因：派生估值在客户当日无快照分支触发 `revalue_user`，对持仓行逐条 `SELECT … FOR UPDATE` 再 update，同一客户多并发首读同进该分支互相等待 → Postgres 死锁。修复：给重估段加 per-user advisory xact lock 串行化；多 worker 启动 seed/schema 加全局 advisory lock。

启示：记忆注入读的是"客户总览"，它依赖的派生估值重算把"读合成"变成"会写行的重估"——要么给读口喂已物化的无锁数据，要么用 advisory lock 串行化同客户。

### 坑 4：唯一索引语义误写（漏 scope）

文档曾把唯一约束写为 `(customer_id, key)`，暗示"同一客户一 key 唯一"。实际索引是 `(customer_id, key, scope)`——唯一性是 (客户, key, 作用域)。若漏 scope，private 与 shared 想各留一条会因唯一冲突互相顶掉，违背"共享不覆盖私有"的抽象。

启示：共享记忆加了 scope，唯一键必须同步扩维。

### 坑 5：记忆检索要防"旧政策/旧快照当事实"

金融场景下"模型拿过期当事实"是行业通病。落地做法是职责分离 + 业务表优先（见 §5.3）。剩余注意：长期记忆目前是覆盖更新（无版本化），`expires_at` 预留但尚无后台过期清理任务。

---

## 9. 已实现 vs 规划对照

| 能力 | 状态 | 一句话证据 |
|---|---|---|
| 短期记忆读写 + 客户链路接入 | ✅ 已接入 | customer_service.py / customer_agent_execution.py |
| 长期记忆表 + 服务 | ✅ 已实现 | memory.py / memory_service.py |
| 长期记忆写关键事实（偏好/活跃产品/风险） | ✅ 已接入 | customer_agent_execution.py、profile.py 风险测评写入 |
| 长期记忆跨会话回读 | ✅ 已接入 | profile.py / customer_task_executor.py |
| 共享记忆 MVP（scope + Agent 权限 + 审计） | ✅ 已落地 | shared_memory_service.py |
| 员工/投顾按授权只读共享档案 | ✅ 已接入 | profile.py /staff/.../memory-facts |
| L3 稳定摘要（每轮异步提炼 → shared） | ✅ 已闭环 | customer_agent_execution.py 入队 + memory_worker |
| Outbox（memory.summary_extract）→ Redis Stream 消费 | ✅ 已闭环 | conversation_summary 入队 + memory_worker |
| 组织级聚合 Worker | 设计完成（设计蓝图含调度与验收） | memory_aggregation_worker |
| L2 场景档案 | ❌ 规划 | ARCHITECTURE_OVERVIEW 采纳边界 |
| Gen3 记忆图谱 | ❌ 规划 | ARCHITECTURE_OVERVIEW 采纳边界 |
| 版本化记忆卡片（valid_from/valid_to + 清理） | ⏳ 覆盖更新，待版本化 | 目前仅 expires_at 预留 |
| 长期记忆过期清理 worker | ❌ 待补 | 消费 expires_at，否则其空转 |

## 10. 核心设计原则

1. **安全第一**：共享记忆首先是安全问题，其次才是功能问题；
2. **作用域标签是基础**：写入时打标签，读取时按标签组合过滤；唯一索引同步带 scope；
3. **端到端权限校验**：写入时强校验 + 读取时软过滤，处处生效；
4. **来源可追溯**：每条记忆有来源、有时间、有作用域、有事件审计；
5. **业务事实表永远高于记忆**：风险/资产/持仓等不得以记忆为最终依据，记忆只做上下文补充；
6. **遗忘是检索降权，不是物理删除**：日常自然沉底，关键场景强制唤醒；关键数据的"证据链"永远保留；
7. **渐进式演进**：私有 → 共享 → 组织级认知，不急于求成。
