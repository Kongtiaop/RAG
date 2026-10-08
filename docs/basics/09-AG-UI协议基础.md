# AG-UI 协议基础：让 Agent 后端和前端说同一种"事件语言"

> 类型: 通用基础知识（与项目无关）；基于 2026-10 公开资料整理

## 1. 是什么与解决什么问题

AG-UI（Agent-User Interaction Protocol）是 CopilotKit 主导的开源协议，用于**标准化 AI Agent 后端与用户侧前端之间的实时通信**。它于 2025 年底首次发布，2026 年 9 月底发布 **1.0 稳定规范**——这是第一个承诺"规范不再破坏性变更"的版本。

要理解它解决什么问题，先看 Agent 打破了什么传统假设：

- 传统 HTTP：一个请求返回一个完整响应。Agent 却是**流式**的：token 一段段吐出、中途调工具、甚至派出子 Agent。
- 前端因此需要：解析流、跟踪 Agent 当前状态（在打字？在调工具？在等确认？）、把这一切映射成 UI。
- 更糟的是，**每个 Agent 框架的流式输出格式都不一样**。LangGraph 的输出、CrewAI 的输出、自研框架的输出各不相同。如果你有 M 个框架、N 个前端界面，就要维护 M×N 套对接代码。

AG-UI 的答案很经典：在中间插入一层标准事件流，把 M×N 降为 **M+N**——每个框架写一个"桥接器"把自己原生输出翻译成 AG-UI 事件，每个前端实现一个 AG-UI 客户端即可。

在 2025-2026 年的 Agent 协议版图中，它的定位是：

- **MCP**：Agent ↔ 工具/资源（Agent 连接外部能力）
- **A2A**：Agent ↔ Agent（Agent 之间协作）
- **AG-UI**：Agent ↔ 用户界面（Agent 连接"人"）——补上此前缺失的一环

## 2. 核心概念与协议机制

### 2.1 一切皆事件

AG-UI 的全部内容就是一组**带类型的结构化事件**。Agent 运行过程中产出事件流，前端逐个消费并渲染。v1.0 规范用 JSON Schema 精确定义了每个事件的字段，TypeScript / Python / .NET 官方 SDK 都直接从这份 Schema 生成（Microsoft 还贡献了一等公民的 .NET SDK）。

所有事件继承自 `BaseEvent`（含 `type`、`timestamp` 等公共字段）。早期版本常被概括为"16 种核心事件"，v1.0 规范扩展到 **31 个事件、8 大类**，主要类别包括：

| 类别 | 代表事件 | 用途 |
|---|---|---|
| 生命周期 | `RUN_STARTED` / `RUN_FINISHED` / `RUN_ERROR` / `STEP_STARTED` / `STEP_FINISHED` | 标记一次 Agent 运行/步骤的开始与结束 |
| 文本消息 | `TEXT_MESSAGE_START` / `_CONTENT` / `_END` | 逐 token 流式输出对话文本 |
| 工具调用 | `TOOL_CALL_START` / `_ARGS` / `_END` | 流式传输工具调用（前端可渲染为可交互卡片） |
| 状态同步 | `STATE_SNAPSHOT` / `STATE_DELTA` / `MESSAGES_SNAPSHOT` | 双向共享结构化状态；增量更新用 JSON Patch（RFC 6902） |
| 特殊 | `RAW` / `CUSTOM` | 透传原生事件、自定义扩展 |

v1.0 还新增了若干能力：**子 Agent 支持**（subagent 事件）、**human-in-the-loop 中断**（interrupt 事件，Agent 暂停等用户批准后继续）、多模态工具结果、metadata 透传、token 用量上报等。

### 2.2 核心抽象

协议的核心接口极度克制，一个函数签名就说完：

```
run(input: RunAgentInput) -> Observable<BaseEvent>
```

输入 `RunAgentInput` 包含线程 ID（threadId）、运行 ID（runId）、消息历史、前端可用的工具定义、上下文等；输出是一个事件流的 Observable（响应式流）。HTTP 之外，协议**不绑定传输层**：SSE、WebSocket、二进制流、webhook 都可以。官方 `HttpAgent` 客户端默认支持 SSE 和二进制两种传输。

### 2.3 兼容性设计：务实而不强求

AG-UI 刻意做到"轻量、少主见"：

- **事件不必逐字匹配协议格式**，只需"AG-UI 兼容"——框架可以用中间件层把原生事件格式低成本适配过来。
- 内置中间件机制处理格式微调，这让 LangGraph、Mastra、Google ADK、OpenAI Agents SDK、Pydantic AI、Microsoft Agent Framework、Claude Managed Agents 等主流框架都能快速接入。

### 2.4 一次典型消息流

以"让 Agent 总结用户的 Notion 笔记"为例，事件序列大致是：

```
RUN_STARTED                ← Agent 开始运行
TOOL_CALL_START (notion)   ← 决定调用 Notion 工具
TOOL_CALL_ARGS             ← 流式传输工具参数
TOOL_CALL_RESULT           ← 拿回笔记内容
STATE_DELTA                ← 更新共享状态（如进度）
TEXT_MESSAGE_START         ← 开始输出总结
TEXT_MESSAGE_CONTENT ×N    ← token 逐个流出
TEXT_MESSAGE_END
RUN_FINISHED               ← 运行结束
```

前端根据这些事件分别渲染：进度指示器、工具调用卡片、打字机效果等。**同一份事件流可以喂给网页、移动端、终端或 Slack**——这正是"一次构建、多端渲染"的基础。

### 2.5 状态同步机制的细节

状态相关事件值得单独说明，因为它们是 Agent 与前端"协作"而非"广播"的关键：

- `STATE_SNAPSHOT`：某一时刻的**全量**共享状态。适合初次同步或状态大幅变化时。
- `STATE_DELTA`：基于 **JSON Patch（RFC 6902）** 的增量变更列表，例如 `[{"op": "replace", "path": "/draft/title", "value": "新标题"}]`。适合高频小步更新——用户改一个字段，Agent 侧立刻感知，反之亦然。
- `MESSAGES_SNAPSHOT`：完整的对话消息历史快照，用于客户端维护会话记录（线程恢复、多端同步都靠它）。

这套机制支撑的核心交互模式是"**人机共同编辑**"：Agent 起草一份方案写入共享状态，用户在前端直接修改表单，修改通过增量 patch 同步回 Agent 上下文——双方始终看到同一份数据。

### 2.6 human-in-the-loop 与工具调用

工具调用事件的另一个用途是**渲染交互组件**：Agent 声明要调一个前端工具（如 `show_flight_options`），前端把参数渲染成一排可选航班卡片，用户点击后把结果作为工具返回值送回 Agent。配合 1.0 的 interrupt 机制，Agent 可以在任何敏感操作前**暂停运行**，等用户批准（approve/reject/edit）后再继续。这是 Agent 产品落地时绕不开的模式——涉及花钱、发消息、删数据等操作时，代码里必须有这层闸门。

### 2.7 最小前端代码示例

用 TypeScript SDK 消费事件流大致长这样：

```ts
import { HttpAgent, EventType } from "@ag-ui/client";

const agent = new HttpAgent({
  url: "https://your-agent.example.com/agent",
  threadId: "thread-001",
});

agent.runAgent({ /* tools, context, messages */ }).subscribe({
  next: (event) => {
    switch (event.type) {
      case EventType.TEXT_MESSAGE_CONTENT:
        appendToken(event.delta);          // 打字机效果
        break;
      case EventType.TOOL_CALL_START:
        showToolCard(event.toolCallName);  // 工具调用卡片
        break;
      case EventType.STATE_DELTA:
        applyJsonPatch(event.delta);       // 增量更新共享状态
        break;
      case EventType.RUN_ERROR:
        showError(event.message);
        break;
    }
  },
});
```

后端侧（以 TS 为例）则是继承 `AbstractAgent` 并在 `run()` 中按序 emit 事件；Python / .NET SDK 的写法对称。框架集成则连这一步都省了——桥接器替你 emit。

## 3. 与后端框架的集成方式

接入一个已有 Agent 后端，通常三条路：

1. **框架官方集成（最省事）**：LangGraph、Mastra、Google ADK 等都有现成的 AG-UI 桥接包，几行配置就能把原生事件流翻成 AG-UI。例如 LangGraph 有 `ag-ui-langgraph` 这类适配层。
2. **用 SDK 手写 endpoint**：Python / TS / .NET SDK 提供基类（如 TS 的 `AbstractAgent`），你实现 `run()` 方法，在 Agent 执行过程中手动 `emit` 标准事件。适合自研框架。
3. **CopilotKit 全家桶**：CopilotKit 既是 AG-UI 的缔造者，也是其最完整的客户端实现（React / Vue / Angular / React Native），外加把 Agent 带进 Slack / Teams 等聊天渠道的 Channels SDK。

前端侧则用 AG-UI 客户端 SDK（或 CopilotKit 组件）订阅事件流，事件会先经过 spec 校验再交给 UI 层。

以 LangGraph 为例的典型链路：

```
React 前端 (CopilotKit / @ag-ui/client)
   │  POST RunAgentInput
   ▼
AG-UI endpoint（langgraph 桥接包提供的 HTTP 服务）
   │  桥接器把 LangGraph 原生 stream events 翻译成 AG-UI 事件
   ▼
SSE 事件流返回前端 → 客户端校验并分发到 UI
```

CrewAI、Mastra、Pydantic AI 等框架的接法结构完全相同，区别只在桥接包的名字与配置项。**这意味着换框架时前端代码一行不用动**——这是协议带来的实际工程收益。

## 4. 与"直接 WebSocket 自定义协议"相比

自己写一套 WebSocket 协议当然可行，AG-UI 换来的是：

| 维度 | 自定义 WebSocket | AG-UI |
|---|---|---|
| 消息设计成本 | 每个项目从零设计消息格式 | 31 个现成事件，覆盖绝大多数场景 |
| 框架接入 | 每接一个框架重写对接层 | 现成桥接器，M+N 而非 M×N |
| 生态工具 | 自己写调试工具 | Inspector 等 DevTools 可直接查看事件流 |
| 互操作性 | 前后端强耦合 | 同一 Agent 可跑在任意 AG-UI 客户端 |
| 传输层 | 绑死 WebSocket | SSE / WebSocket / 二进制皆可 |

反过来说，如果你的场景极其简单（纯文本流式问答、单一框架单一前端），自定义流确实更轻，引入协议反而是负担。

## 5. 适用场景

- **多框架多前端的矩阵**：这是协议最大的收益区。
- **需要人在回路**：审批、确认、用户中途修改输入——1.0 的 interrupt 事件就是为此设计的。
- **共享状态的双向协作**：Agent 与用户共同编辑一份草稿/表格（`STATE_DELTA` 增量同步）。
- **一次构建多端部署**：同一 Agent 同时服务 Web、Slack、Teams、移动端。

不太适用的场景：纯批处理（无交互）、后端内部 Agent 通信（那是 A2A 的地盘）、极简单轮问答。

## 6. 生态与替代方案

- **采用方**：据 CopilotKit 官方口径，1.0 已获 Google、Microsoft、Amazon、Oracle 等采用；核心包 `@ag-ui/core` 周下载量超过 200 万。注意这些数字来自主导方宣传，参考即可。
- **CopilotKit**：AG-UI 之上的产品化前端栈，含预置组件、线程持久化、观测能力。协议免费开源，CopilotKit 部分智能功能是商业产品——用纯协议层不锁定。
- **A2UI**：Google 主导的"Agent 生成 UI"声明式格式（见本系列下一节），可**跑在 AG-UI 传输之上**，两者是互补而非竞争关系。
- **替代方案**：Vercel AI SDK 的流式协议（React 生态常用）、各框架自带前端（如 LangGraph 的专有流格式）、OpenAI Realtime 等。AG-UI 优势在于跨框架中立。

## 7. 常见坑

1. **版本资料混乱**：网上大量资料写"16 种事件"，那是 1.0 之前的口径；以 v1.0 规范（31 事件 / 8 类）和官方 JSON Schema 为准。查资料时注意文章日期。
2. **事件顺序约束**：`TEXT_MESSAGE_END` 之前不能开新消息、工具调用的 START→ARGS→END 有严格次序。规范明确了 producer/consumer 各自的义务，违反时是**实现有 bug**——不要靠猜，直接对着规范查。
3. **状态同步滥用**：`STATE_SNAPSHOT` 是全量、`STATE_DELTA` 是增量。高频大对象用全量快照会打爆带宽，应设计精简的共享状态并用增量 patch。
4. **把 AG-UI 当传输层**：它不规定 SSE 还是 WebSocket、不规定鉴权方式，这些仍需你自己决策。
5. **规范与 Schema 冲突时**：官方明确以 JSON Schema 为准。
6. **前端工具注入面**：`RunAgentInput` 中前端可以把工具定义传给 Agent，注意不要把后端敏感操作暴露成前端可调用的工具，做好服务端鉴权。

## 延伸阅读

- 官网与规范：docs.ag-ui.com 与 copilotkit.ai/blog（AG-UI 1.0 发布公告，2026-09）
- GitHub：ag-ui-protocol 组织（含 TypeScript / Python / .NET SDK）
- AG-UI Dojo：30+ 个可运行集成示例
