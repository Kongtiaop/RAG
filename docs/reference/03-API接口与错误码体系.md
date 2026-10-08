# 03 API 接口与错误码体系

> 来源: `docs/API.md`（通用约定、认证/幂等、各分组端点清单、权限与安全边界、客服 RAG 与 Query Router、消息增量查询）；`docs/ERROR_CODES.md`（统一错误对象、HTTP 状态码语义、分段错误码表、前端错误处理规范、维护规则）
> 说明: 由 wealth-manager 项目文档按主题重写，重写于 2026-10-08。两份源文档在错误响应格式上存在新旧口径：`API.md` 仍以 `detail.code/message` 为主要示例，而 `ERROR_CODES.md`（2026-09-27）已统一为顶层 `error` 对象、`detail` 仅向后兼容保留——本文以较新的 `error` 对象口径为准。

## 1. 通用约定

### 1.1 前缀与契约

- API 前缀：`/api/v1`；端口以启动命令和环境变量为准。
- **权威契约**是运行中的 FastAPI OpenAPI（`/docs`、`/openapi.json`）；接口文档只说明稳定业务边界和常用请求。

### 1.2 认证

除健康检查、登录、注册和公开产品等接口外，携带：

```http
Authorization: Bearer <access_token>
X-Trace-Id: <uuid，可选，前端默认自动写入>
```

Access Token 失效后，前端使用 Refresh Token 轮换；刷新失败会清除本地会话并回到登录页。

### 1.3 统一成功响应

```json
{
  "success": true,
  "data": {},
  "error": null,
  "trace_id": "..."
}
```

成功**不使用统一的字符串「成功码」**：客户端以 2xx HTTP 状态 + `success=true` 判断成功，不同操作的成功事实由 `data.status`、`data.action_status` 或资源字段表达。

常见业务成功状态（出现在 `data` 中）：

```text
订单：pending_confirmation / pending_review / executed / rejected / cancelled
业务操作：pending_review / settled / rejected
风险预警：open / acknowledged / investigating / pending_customer / report_pending / resolved / dismissed
交易限制：none / restricted
工单：open / assigned / in_progress / pending_customer / resolved / closed / cancelled
AML 批次：running / completed / completed_with_errors / failed
Outbox：pending / published / dead
任务：queued / running / success / failed / dead / cancelled
```

### 1.4 统一错误对象

所有错误通道（`AppException` / FastAPI `HTTPException` / 参数校验 / 未预期异常）统一输出同一个结构：

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "INSUFFICIENT_BALANCE",
    "message": "insufficient available balance",
    "user_message": "账户可用余额不足，本次操作没有执行。",
    "severity": "warning",
    "retryable": false,
    "suggestion": "先确认可用余额（在途资金通常不算可用），再调整金额重新提交。",
    "details": {}
  },
  "trace_id": "27fdd2c2-4de3-4069-add3-11fe2378128e"
}
```

字段语义按读者区分：

| 字段 | 读者 | 说明 |
|---|---|---|
| `code` | 前端分支、测试 | 稳定枚举，**不要靠文案分支** |
| `message` | 员工 / 日志 | **技术原文**，禁止直接展示给客户 |
| `user_message` | 客户 | 中文人话，由后端翻译 |
| `severity` | 前端样式 | `info` / `warning` / `error` / `critical` |
| `retryable` | 前端交互 | 是否值得重试；决定要不要给「重试」按钮 |
| `suggestion` | 客户 | 恢复建议（下一步该做什么），可为 `null` |
| `trace_id` | 客户 → 客服 | 页面上以「问题编号 XXXXXXXX」（前 8 位）展示，供客服串联日志 |

四种触发通道的差异：

| 触发 | HTTP | `code` |
|---|---|---|
| `AppException` 及其子类 | 由异常自带 | 异常自带的 `code` |
| `HTTPException`（有业务码） | 由异常自带 | `detail.code` |
| `HTTPException`（裸字符串 detail） | 由异常自带 | 按状态码推导（`FORBIDDEN` / `NOT_FOUND` / …） |
| 参数校验失败 | 422 | `VALIDATION_ERROR`（技术细节在 `details.errors`） |
| 未预期异常（兜底） | 500 | `INTERNAL_ERROR`，**异常详情只进日志，绝不进响应体** |

### 1.5 HTTP 状态码语义

| 状态码 | 语义 | 处理原则 |
|---|---|---|
| `200` | 查询/更新成功 | 刷新当前资源或列表 |
| `201` | 资源创建成功 | 展示创建结果，保留返回的资源 ID |
| `202` | 异步任务已受理 | 不代表完成；轮询任务状态或等待通知 |
| `204` | 无响应体的成功 | 仅在确有 204 契约时刷新列表，不要尝试解析 JSON |
| `400` | 参数组合不合法或缺少业务必填条件 | 提示补齐参数，不要盲目重试 |
| `401` | 未登录、Token 失效 | 尝试一次 Token 刷新；失败则清会话并登录 |
| `403` | 身份、权限、授权或数据范围不足 | 不重试；后端拒绝是最终边界 |
| `404` | 资源不存在或不可见 | 刷新列表、确认资源 ID 与数据范围 |
| `409` | 幂等冲突、重复审核、非法状态、风控阻断 | 回读资源最新状态；不得自动重复提交 |
| `413` | 附件过大 | 提示压缩或更换文件 |
| `415` | 附件类型不支持 | 仅允许 JPG/PNG/PDF |
| `422` | Schema 或业务字段校验失败 | 按 `details.errors` 字段补全 |

### 1.6 幂等与分页

- 订单、赎回、转账等写操作支持 `idempotency_key`：客户端网络重试必须复用同一个键；业务后端、数据库唯一约束和状态机共同防止重复资金副作用。
- 列表接口统一使用 `limit/offset` 分页（非法范围返回 `INVALID_PAGING` / `INVALID_LIMIT`），并普遍支持过滤参数（如 `status`、`customer_type`、`operation_type`）。

## 2. API 分组总览

| 分组 | 职责 | 代表端点 |
|---|---|---|
| `/health` | 健康检查 | `GET /health`（PG/pgvector、Redis、模型/Embedding 状态） |
| `/auth` | 认证与会话 | login / refresh / logout / me / register |
| `/profile` | 画像、产品、投顾授权、企业认证 | `/profile/me`、`/profile/staff/*` |
| `/trading` | 订单与模拟交易 | `/trading/orders` 全生命周期 |
| `/operations` | 赎回、转账与业务操作 | `/operations/redeem|transfer`、staff 代办与审核 |
| `/risk-alerts` | 风险、AML 与交易限制 | 预警处置、日批扫描、调度器状态 |
| `/workorders` `/notifications` | 工单、附件与通知 | 创建/分派/补件/附件鉴权下载 |
| `/knowledge` `/tasks` | 知识库与异步任务 | 文档导入、检索、任务提交查询 |
| `/admin` | 用户/角色/权限/审计/企业认证审核 | 用户与角色管理、回收站 |
| `/customer-rag` `/customer-service` | 客服 RAG、事实路由与会话消息 | answer / route / messages |

## 3. 核心端点

### 3.1 认证 `/auth`

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/auth/login` | 登录，返回 Access/Refresh Token |
| `POST` | `/auth/refresh` | 使用 Refresh Token 获取轮换后的 Token |
| `POST` | `/auth/logout` | 撤销 Refresh Token 会话 |
| `GET` | `/auth/me` | 当前用户、角色、权限和超级管理员标识 |
| `POST` | `/auth/register` | 注册客户或员工；员工注册需要公司码 |

### 3.2 画像与投顾 `/profile`

客户本人：

- `GET/PUT /profile/me`：客户画像、最新资产、持仓、当前风险操作状态；更新可编辑画像。
- `GET/POST /profile/me/risk-assessment`：查询/提交风险测评。
- `GET/POST /profile/me/enterprise-verification`：查询/提交企业认证。
- `GET /profile/me/recommendations`：当前客户适当性推荐与排除原因。
- `GET/POST /profile/me/advisor-authorizations`、`DELETE .../{authorization_id}`：创建/撤销投顾授权。
- `POST /profile/me/operation-drafts/{draft_id}/confirm|reject|submit-order`：确认/拒绝投顾草稿、将确认草稿提交为订单。

工作人员（带权限与数据范围）：

- `GET /profile/staff/customers`：需 `customer:read_all`，支持 `q/tier/customer_type/limit/offset`。
- `GET /profile/staff/advisor-customers`：仅当前投顾的 active 授权客户。
- `POST /profile/staff/operation-drafts`：投顾创建操作草稿，**不直接扣款**。
- `GET/POST /profile/staff/products`、`PUT/DELETE /profile/staff/products/{product_id}`、`PUT .../restore`：产品管理与软删除/恢复。

### 3.3 订单与模拟交易 `/trading`

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/trading/orders` | 创建客户待确认订单 |
| `POST` | `/trading/orders/{order_id}/confirm` | 客户确认订单，进入 `pending_review` |
| `POST` | `/trading/orders/{order_id}/cancel` | 取消可取消订单 |
| `GET` | `/trading/orders/pending` | 工作人员待审核订单 |
| `POST` | `/trading/orders/{order_id}/review` | 审核通过并执行；**会再次进行风险门禁** |
| `POST` | `/trading/orders/{order_id}/reject` | 审核拒绝 |
| `GET` | `/trading/trades/me` | 当前客户成交记录 |

创建订单请求：

```json
{
  "product_id": "<product_id>",
  "amount": "1000.00",
  "idempotency_key": "customer-order-uuid"
}
```

审核前若发现未结案风险预警或交易限制，返回 `409 RISK_CONTROL_BLOCKED`。订单、资金、持仓和审计由确定性交易 Service 在事务中处理；前端或 Agent 不可绕过。

### 3.4 赎回、转账与业务操作 `/operations`

客户本人：

- `POST /operations/redeem` / `POST /operations/transfer`：提交赎回/转账申请，均带 `idempotency_key`。
- `GET /operations/me`、`GET /operations/me/{operation_id}`：查询本人操作。

工作人员代办与审核：

- `POST /operations/staff/redeem|transfer`：为**已授权且已确认**的客户代办；额外校验授权动作、额度、风险、余额/持仓和幂等。
- `POST /operations/redeem|transfer/{operation_id}/review`：审核通过/拒绝；结算时仍再次检查状态和风险。
- `GET /operations/audit-logs`：业务操作审计，按角色隔离可见范围。

状态语义与结算事务：

```text
pending_review → settled / rejected
转账：同一事务内完成双方余额 + transfer/out + transfer/in 流水 + 审计
赎回：同一事务内完成持仓减少 + 余额增加 + redeem/in 流水 + 审计
```

### 3.5 风险、AML 与交易限制 `/risk-alerts`

| 方法 | 路径 | 权限/说明 |
|---|---|---|
| `GET` | `/risk-alerts`、`/risk-alerts/{alert_id}` | `risk:alert_read`；状态/等级/客户过滤 |
| `POST` | `/risk-alerts/scan` | `risk:scan_execute`；手工扫描指定客户窗口 |
| `GET` | `/risk-alerts/batches`、`.../alerts` | AML 日批列表与批次预警 |
| `POST` | `/risk-alerts/{alert_id}/handle` | `risk:alert_handle`；接单、调查、补件、评估、结案 |
| `POST` | `/risk-alerts/{alert_id}/action` | `risk:alert_action`；执行动作 |
| `GET` | `/risk-alerts/scheduler-status` | 调度器心跳状态；`running` 依据 `max(3 * AML_SCHEDULER_POLL_SECONDS, 180)` 秒内是否有心跳，只表示 Worker 存活 |
| `POST` | `/risk-alerts/batches/{batch_id}/retry` | 仅允许 `failed`/`completed_with_errors` 批次；按失败客户创建独立补跑批次，原批次不修改 |
| `POST` | `/risk-alerts/batches/{batch_id}/late-rescan` | 已完成窗口补扫迟到流水；批次键 `late_rescan:{source_batch_id}` |

处置请求关键字段：

```json
{
  "status": "investigating",
  "assessment_result": "confirmed_risk",
  "customer_consulted": false,
  "disposition_code": "RESTRICT_TRADING"
}
```

常用动作：

```text
HOLD_ORDER / REJECT_ORDER / RESTRICT_TRADING / RELEASE_RESTRICTION
REQUEST_MATERIALS / CREATE_INVESTIGATION / CREATE_REPORT_DRAFT / ESCALATE
```

解除交易限制的正确顺序：

```text
confirmed_risk + RESTRICT_TRADING
→ investigating / restricted
→ cleared_after_review 或 false_positive + 复核证据
→ RELEASE_RESTRICTION
→ restriction_status = none
→ resolved / dismissed
```

### 3.6 工单与通知 `/workorders` `/notifications`

- `POST /workorders` 创建；`GET /workorders` 列表（`scope/status/category/priority/limit/offset`）。
- `POST /workorders/{id}/assign|handle|supplements|close`：分派、处理、客户补件、关闭。
- `GET/POST /workorders/{id}/attachments`、`GET .../download`：附件上传与**带 JWT 的鉴权下载**。

工单状态机：

```text
open → assigned → in_progress → pending_customer → resolved → closed
```

客户只能读取本人工单、在 `pending_customer` 时补件；工作人员默认只能处理分派给自己的工单。风险补件、工单分派、客户补充和结案均可生成站内通知。

### 3.7 知识库、异步任务与管理 `/knowledge` `/tasks` `/admin`

- `/knowledge`：知识库默认库、文档创建/导入/检索、版本与 Chunk 生命周期。文档创建后通过 Outbox + Redis Streams + Knowledge Worker **异步**切分、Embedding 和激活版本；主检索为 PostgreSQL + pgvector。
- `/tasks`：提交和查询异步任务，受理返回 `202`；状态、重试、失败原因和结果由 AsyncTask 记录。
- `/admin` 典型端点：

```text
GET  /admin/users | roles | permissions
PUT  /admin/users/{user_id}/roles | status
DELETE /admin/users/{user_id} | PUT /admin/users/{user_id}/restore
GET  /admin/recycle-bin | audit-logs | enterprise-verifications
POST /admin/enterprise-verifications/{verification_id}/review
```

### 3.8 客服 RAG 与受控事实查询 `/customer-rag`

`POST /customer-rag/answer`：客服 RAG 只返回**引用型回答**，不执行交易。

- `intent`：`company_info`、`company_business`、`faq`、`workflow`、`policy`、`risk_public`、`product_recommendation`。
- 非产品意图按客服公开 Scope 检索知识库，低于阈值返回 `low_confidence` 和 `handoff_required=true`。
- `product_recommendation` 返回 `database_recommendation`，由产品/画像/适当性流程处理。

`POST /customer-rag/route`（Query Router MVP）：对首批已批准的客户本人实时事实做**确定性路由**，不调用 RAG、不创建工单、不执行业务操作。

| route | 权威来源 | 客户数据范围 |
|---|---|---|
| `workorder_status` | `work_order` | 仅 `customer_id = 当前用户` |
| `order_status` | `orders` + `product` | 仅 `orders.user_id = 当前用户` |
| `risk_restriction` | `account` + 当前风险预警 | 仅 `account.user_id = 当前用户` |
| `asset_summary` | 最近资产快照 + 有效持仓 | 仅 `user_id = 当前用户` |
| `product_status` | `product` 实时状态 | 仅按明确产品名称查询，不推荐 |

响应 `source_type` 三态：`business_fact`（已返回实时业务事实）、`rag_explanation`（可继续调 `/customer-rag/answer`）、`handoff`（预留）。路由优先级：**实时业务事实优先，RAG 只用于流程、条款和背景解释**，不能覆盖实时状态或执行受控操作。

### 3.9 客服会话消息增量查询

```http
GET /customer-service/sessions/{session_id}/messages?after={last_message_id}
```

- `after` 游标：传入最后一条已消费消息 ID，仅返回其后消息；不传则返回快照。
- 结果按 `created_at ASC, id ASC` 排序，单次最多 200 条；`after` 只缩小读取范围，**不改变权限校验**（客户仅限本人会话，坐席仅限已接入会话）。

前端恢复约定：更新 `lastMessageId` → 合并前按消息 ID 去重 → WebSocket `error`/`close` 时执行一次 `after` 查询 → 固定轮询作为降级 → 会话终态后停止轮询并清理缓存。WebSocket/PubSub 是低延迟通知通道，HTTP 增量查询和 PostgreSQL 才是断线恢复的事实链路。

## 4. 错误码体系设计原则

1. **code / message / user_message 三层分离**：`code` 是前端与测试依赖的稳定枚举；`message` 是技术原文仅供排障；`user_message` 是面向客户的中文文案，由后端统一翻译。
2. **severity + retryable 驱动交互**：错误分级决定样式；`retryable=true` 才提供重试入口——对状态冲突类错误给「重试」会诱导重复提交，正确动作是刷新后回读最新状态。
3. **trace_id 贯穿排障链路**：页面展示前 8 位「问题编号」，是用户报障时唯一能提供的定位凭据。
4. **四通道统一出口**：`AppException`、带业务码的 `HTTPException`、裸 detail、参数校验、未预期异常全部收敛到同一个 `error` 对象；未预期异常一律转 `INTERNAL_ERROR`，异常详情只进日志。
5. **不透出驱动异常**：数据库驱动异常必须映射为稳定业务错误语义，不直接进 API 响应。
6. **文案兜底机制**：新增错误码不需要维护中文文案映射——`app/common/exceptions/user_copy.py` 的默认层按 HTTP 状态码自动兜底；只有客户侧高频、默认文案会误解后果（尤其涉及资金）、或有明确下一步动作的错误码才需要进白名单。
7. **命名纪律**：全大写下划线，语义稳定，不因页面文案变化改名；新增业务错误码需同步更新后端接口、HTTP 回归和两份文档。
8. **handler 注册守卫**：新增 handler 必须在 `app/main.py` 注册，有守卫测试断言四个 handler 都在。

## 5. 错误码分段与代表示例

### 5.1 认证、管理员与通用权限

| 错误码 | HTTP | 触发条件 |
|---|---:|---|
| `VALIDATION_ERROR` | 422 | 请求不符合 Pydantic Schema |
| `ADMIN_PERMISSION_REQUIRED` | 403 | 无管理员权限调用管理接口 |
| `STAFF_REQUIRED` | 403 | 客户身份调用工作人员审核/代办接口 |
| `SUPER_ADMIN_PERMISSIONS_FIXED` | 409 | 尝试修改超级管理员固定权限 |
| `SELF_SUPER_ADMIN_ROLE_FORBIDDEN` | 409 | 超级管理员尝试移除自己的超管角色 |
| `SELF_ACCOUNT_DISABLE_FORBIDDEN` / `SELF_ACCOUNT_DELETE_FORBIDDEN` | 409 | 自禁用/自删除账号 |

### 5.2 客户、画像、产品与企业认证

| 错误码 | HTTP | 触发条件 |
|---|---:|---|
| `CUSTOMER_ACCOUNT_REQUIRED` | 403 | 非客户调用客户本人业务接口 |
| `PRODUCT_NOT_FOUND` | 404 | 产品不存在、已删除或不可用 |
| `ALREADY_ENTERPRISE_CUSTOMER` | 409 | 已是企业客户仍重复提交企业认证 |
| `VERIFICATION_ALREADY_APPROVED` | 409 | 已通过的认证再次按通过处理 |

### 5.3 投顾授权与操作草稿

授权校验是代办链路的核心分段：

| 错误码 | HTTP | 触发条件 |
|---|---:|---|
| `ADVISOR_AUTHORIZATION_REQUIRED` | 403 | 无 active 授权即读取/代办 |
| `ADVISOR_AUTHORIZATION_EXPIRED` | 403 | 授权已到期 |
| `AUTHORIZED_ACTION_REQUIRED` | 403 | 授权范围不含 redeem/transfer |
| `AUTHORIZATION_RISK_LIMIT_EXCEEDED` | 403 | 产品风险超授权上限 |
| `AUTHORIZATION_SINGLE_LIMIT_EXCEEDED` / `AUTHORIZATION_DAILY_LIMIT_EXCEEDED` | 409 | 超 单笔/当日 额度 |
| `CUSTOMER_CONFIRMATION_REQUIRED` | 409 | 代办但未提供客户确认 |
| `DRAFT_STATE_CONFLICT` | 409 | 草稿状态不允许确认/拒绝/提交 |
| `DRAFT_ORDER_SUBMISSION_FAILED` | 409 | 草稿转订单失败（授权/余额/风险/适当性/状态） |

### 5.4 订单、赎回、转账与资金

| 错误码 | HTTP | 触发条件 |
|---|---:|---|
| `SELF_TRANSFER_FORBIDDEN` | 409 | 源账户与目标账户相同 |
| `INVALID_AMOUNT` | 422 | 金额非正、格式非法或超规则 |
| `INSUFFICIENT_BALANCE` | 409 | 可用余额不足或冻结状态不一致 |
| `INSUFFICIENT_HOLDING` | 409 | 可赎回持仓不足 |
| `SECOND_CONFIRMATION_REQUIRED` | 409 | 高额转账缺少二次确认 |
| `IDEMPOTENCY_CONFLICT` | 409 | 幂等键并发竞争或唯一约束冲突 |
| `ORDER_STATE_CONFLICT` | 409 | 订单状态不允许当前动作或重复审核 |
| `OPERATION_STATE_CONFLICT` | 409 | 业务操作重复审核或状态不允许结算 |
| `RISK_CONTROL_BLOCKED` | 409 | 未结案风险预警/交易限制阻断订单或业务操作，**不得绕过** |

### 5.5 风险、AML 与交易限制

这一段大量使用 422 表达「业务动作缺少前置证据」：

| 错误码 | HTTP | 触发条件 |
|---|---:|---|
| `RISK_ALERT_STATE_CONFLICT` | 409 | 已关闭预警再次处理 |
| `RISK_PENDING_CUSTOMER_REQUIRES_INSUFFICIENT_INFO` | 422 | 转 `pending_customer` 但结论不是 `insufficient_information` |
| `RISK_MATERIAL_REQUEST_NOTE_REQUIRED` | 422 | 要求补件但缺评估说明或资料清单 |
| `DISPOSITION_REQUIRED` | 422 | `confirmed_risk` 但没有处置动作 |
| `RISK_CANNOT_CLOSE_CONFIRMED` | 422 | 确认风险后直接结案 |
| `REVIEW_EVIDENCE_REQUIRED` | 422 | 「评估后通过」缺评估依据/客户沟通/沟通记录 |
| `RISK_RESTRICTION_MUST_BE_RELEASED` | 422 | 账户仍 restricted 时尝试结案 |

### 5.6 工单、附件、知识库与任务

| 错误码 | HTTP | 触发条件 |
|---|---:|---|
| `WORKORDER_CUSTOMER_SCOPE` | 403 | 工单操作超出本人范围 |
| `WORKORDER_ASSIGNEE_REQUIRED` | 403 | 非分派处理人处理/关闭工单 |
| `WORKORDER_STATE_CONFLICT` | 409 | 状态不允许补件/分派/处理/关闭 |
| `WORKORDER_ATTACHMENT_TYPE` | 415 | 文件不是 JPG/PNG/PDF |
| `WORKORDER_ATTACHMENT_TOO_LARGE` | 413 | 超附件大小上限 |
| `WORKORDER_ATTACHMENT_FILE_MISSING` | 404 | 元数据存在但受控存储文件丢失 |
| `KNOWLEDGE_DOCUMENT_NOT_FOUND` | 404 | 文档不存在/已删除/不可见 |
| `TASK_NOT_FOUND` | 404 | 异步任务不存在 |

## 6. 前端错误处理规范

历史教训：早期前端只读 `detail`，而 `/auth/*`、`/admin/*` 返回 `error` 对象——连中文 message 都收不到，退化成 axios 的 `Request failed with status code 400`。现在两条通道在前端 `frontend/src/api/http.ts` 统一读取。

规范要点：

1. **统一入口**：所有展示走 `frontend/src/utils/errors.ts` 的 `formatError`，禁止视图内各自拼接错误文案。
2. **展示用 `user_message`，不用 `message`**：后者是技术原文，只适合排障。
3. **禁止 `new Error(detailObject)`**，也禁止把 `data.detail`（对象）直接赋给错误提示——页面会渲染出 JSON 或 `[object Object]`。
4. **按 `code` 分支，不按文案分支**。
5. **必须展示 `trace_id` 前 8 位**（「问题编号」）。
6. **`retryable=true` 时才提供重试入口**；状态冲突类错误的正确动作是刷新回读。
7. `401` 仅尝试一次 Refresh Token 轮换，失败后清理本地 Token。
8. 文件下载错误需通过带 JWT 的 Axios Blob 请求读取，不能依赖裸链接。

标准写法：

```vue
<!-- 视图 -->
<ErrorNotice v-if="error" :error="error" />
```

```ts
// 视图的 catch
catch (e) { error.value = formatError(e, '订单加载失败，请稍后重试。') }
```

`ErrorNotice` 渲染三段：**发生了什么 → 该怎么办 → 问题编号**。

## 7. 权限与安全边界

1. 前端按钮和菜单不是安全边界，所有接口由后端 RBAC + 资源数据范围校验。
2. 客户不能读取工作人员客户管理、审核、风险动作或管理员接口。
3. 工作人员代办不等于可无限操作客户资金，必须满足客户授权、确认、额度、风险和审计约束。
4. 风险限制由后端业务入口检查，不能通过直接调用 API 绕过。
5. RAG/Agent 只能检索、分析、生成建议或草稿；不能直接修改余额、持仓、订单状态、权限或风险限制。
6. 受保护附件使用带 JWT 的 API 下载，不使用裸静态 URL。
7. 涉及资金、风险状态、订单或权限时，优先通过 API/Service 操作并保留审计；不为演示直接修改数据库关键状态。
