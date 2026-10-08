# MCP 协议与 Agent Skills：给 AI 接上"手"和"说明书"

> 类型: 通用基础知识（与项目无关）；基于 2026-10 公开资料整理

## 一、是什么与解决什么问题

### 1.1 M×N 集成难题

在 MCP 出现之前，每个 AI 应用（Claude、ChatGPT、各种 Agent 框架）要接入外部工具和数据源，
都得自己写一遍集成代码。假设有 M 个 AI 应用、N 个工具/数据源，最坏需要 M×N 套胶水代码。

MCP（Model Context Protocol，模型上下文协议）由 Anthropic 于 2024 年 11 月提出并开源，
把 M×N 问题变成 M+N：应用实现一次 MCP Client，工具实现一次 MCP Server，双方按统一协议对话。

### 1.2 为什么成了事实标准

- 2025 年，OpenAI、Google、Microsoft 等相继宣布支持 MCP，它成为 LLM 工具调用的通用协议。
- 2025 年 12 月，Anthropic 将 MCP 捐献给 Linux 基金会旗下的 Agentic AI Foundation，
  正式成为中立的开源标准项目。
- 主流 IDE、Agent 框架、云平台都提供了 MCP 接入点，"给某个系统做一个 MCP Server"
  成为暴露能力给 AI 的常见做法。

一句话：**MCP 是 AI 应用与外部工具/数据之间的"USB-C 接口"**。

## 二、核心概念

### 2.1 架构：Host / Client / Server

```
┌─────────────────────────────┐
│  Host（宿主应用，如 IDE/聊天助手）  │
│  ┌────────┐  ┌────────┐     │
│  │Client A│  │Client B│     │   每个 Client 与一个 Server
│  └───┬────┘  └───┬────┘     │   保持 1:1 连接
└──────┼───────────┼──────────┘
       │           │
  ┌────▼────┐ ┌────▼────┐
  │Server A │ │Server B │    文件系统 / 数据库 / GitHub / ...
  └─────────┘ └─────────┘
```

- **Host**：用户使用的 AI 应用（如 Claude Desktop、Cursor），负责编排与安全策略。
- **Client**：Host 内部的连接器，与某个 Server 1:1 通信。
- **Server**：暴露具体能力的轻量服务（本地进程或远程服务）。

### 2.2 能力集（谁暴露什么，方向很重要）

MCP 的能力分为两类方向，这是初学者最常搞混的点：

| 方向 | 能力 | 含义 |
|------|------|------|
| Server → Client | **tools** | 模型可调用的工具/函数 |
| Server → Client | **resources** | 可读取的数据/文件/上下文（类 URI 资源） |
| Server → Client | **prompts** | 预置的提示词模板 |
| Client → Server | **sampling** | Server 反向请求 Client 侧的 LLM 补全 |
| Client → Server | **elicitation** | Server 请求用户补充输入（人工确认） |
| Client → Server | **roots** | 告知 Server 可访问的文件系统边界 |

记忆法：**tools/resources/prompts 是 Server 提供的"服务"；sampling/elicitation/roots
是 Client 授权给 Server 的"反向能力"**。把 sampling/elicitation 当成 Server 能力，
会导致访问控制设计错误。

### 2.3 传输层：stdio vs Streamable HTTP

| 传输方式 | 场景 | 特点 |
|----------|------|------|
| **stdio** | 本地进程，Host 负责拉起 Server | 标准输入输出传 JSON-RPC，简单、无网络开销，凭据走环境变量 |
| **Streamable HTTP** | 远程/云上 Server | 单个 HTTP POST 端点，响应可以是普通 JSON 或 SSE 流；支持鉴权、可水平扩展 |

历史演进：2024-11-05 版使用 HTTP+SSE 双端点传输 → 2025-03-26 引入 Streamable HTTP
→ 2025-11-25 版正式将旧 HTTP+SSE 标记为废弃 → 2026-07-28 版进一步**移除了传输层会话
（Mcp-Session-Id）与 initialize 握手，协议转为无状态**，每个请求自带协议版本与能力元数据。

### 2.4 规范版本速览（截至 2026-10）

| 版本 | 关键词 |
|------|--------|
| 2024-11-05 | 初版，stdio + HTTP+SSE |
| 2025-03-26 | 引入 Streamable HTTP、OAuth |
| 2025-06-18 | 细化授权（RFC 9728 等） |
| 2025-11-25 | 图标元数据、elicitation 枚举增强、实验性 tasks |
| **2026-07-28** | **无状态化**：移除会话/握手；引入 server/discover 能力探测；
  多轮往返请求（MRTR）替代 server 主动拉起请求；roots/sampling/logging 标记废弃；
  列表结果带 ttlMs 可缓存；远程 Server 生产化的重大重构 |

要点：2026 版把"每请求自包含"作为核心（`_meta` 携带协议版本/客户端能力），这让
Server 可以像普通 Web API 一样做负载均衡与缓存，是 MCP 走向生产级基础设施的关键一步。
新旧版本 SDK 行为差异较大，写代码前先确认所用 SDK 对应的规范版本。

### 2.5 与直接 function calling 的关系

- **Function calling** 是模型厂商 API 层的能力：模型输出"我要调用某函数"的结构化意图。
- **MCP 不替代它**，而是其上方的**分发层/生态层**：工具发现（tools/list）、统一描述、
  跨应用复用、鉴权、注册中心都由 MCP 承担。
- 打个比方：function calling 是"模型会说'请帮我调这个函数'"，MCP 是"这个函数从哪来、
  谁能调、怎么发现、怎么安全地调"。

## 三、最小示例：一个 stdio MCP Server（Python）

官方 Python SDK（`pip install "mcp[cli]"`）写一个工具 Server 大约 15 行：

```python
# server.py —— 用 Claude Desktop / Cursor 等配置后即可被调用
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("demo")

@mcp.tool()
def add(a: int, b: int) -> int:
    """计算两个整数的和"""
    return a + b

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

Host 侧配置示例（Claude Desktop 的 `claude_desktop_config.json`）：

```json
{
  "mcpServers": {
    "demo": {
      "command": "python",
      "args": ["C:/path/to/server.py"]
    }
  }
}
```

工作流程：Host 启动 → Client 与 Server 协商能力 → 模型看到 tools 列表 →
用户提问触发 `add` → Host 执行并回填结果给模型。

远程 Server 思路相同，把 `transport` 换成 streamable-http 并挂到 HTTP 服务上即可。

## 四、Agent Skills：给 AI 的"程序性知识"打包

### 4.1 是什么

Agent Skills 由 Anthropic 于 2025 年 10 月推出，**2025 年 12 月 18 日开放为跨平台标准**
（agentskills.io）。一个 Skill 就是一个文件夹，核心是一个 `SKILL.md`：

```
pdf-processing/
├── SKILL.md        # 必需：YAML 元数据 + 使用说明
├── scripts/        # 可选：可执行脚本（如填表单的 Python）
├── references/     # 可选：按需阅读的参考文档
└── assets/         # 可选：模板、素材
```

`SKILL.md` 开头是 YAML frontmatter，必填两个字段：

```markdown
---
name: pdf-processing      # ≤64 字符，小写字母/数字/连字符，须与目录名一致
description: 填写 PDF 表单并提取字段。当用户要求处理 PDF 表单时使用。
---

## 步骤
1. 先运行 scripts/extract_fields.py 获取字段列表
2. 表单填写细节参考 references/forms.md
...
```

### 4.2 核心机制：渐进式披露（Progressive Disclosure）

| 层级 | 内容 | 加载时机 | 成本 |
|------|------|----------|------|
| 1 | name + description | 启动时全部进系统提示词 | 每个技能约 100 token |
| 2 | SKILL.md 正文 | 判断相关后才读取 | 建议控制在 ~5000 token |
| 3 | 捆绑的文件/脚本 | 任务确实需要时才读/执行 | 几乎不占常驻上下文 |

效果：Agent 可以携带几十个技能，而常驻上下文开销近乎为零——重内容躺在磁盘上，
被任务"按需拉取"。

### 4.3 生态现状

开放标准发布后，OpenAI Codex、Google Gemini CLI、GitHub Copilot、Cursor、VS Code
等数十个工具宣布支持同一套 SKILL.md 规格；社区公共注册库中技能数量已达数万级。
写作成本极低（就是写 Markdown 文件夹）是它扩散快的重要原因。

### 4.4 Skills 与 MCP 怎么互补

| | MCP | Agent Skills |
|---|-----|--------------|
| 回答的问题 | "我能访问什么？"（连接） | "这件事该怎么做？"（方法） |
| 形态 | 线路协议 + 工具服务 | 文件夹 + Markdown 指令 |
| 成本 | 需要写并部署服务 | 几乎为零 |
| 典型用途 | 封装 API、数据库、SaaS | 封装工作流程、团队规范、领域技巧 |

组合用法：一个 Skill 的正文可以描述"分几步、调哪几个 MCP 工具、参数怎么填"，
MCP 负责实际的连接与执行。**Skills 教 Agent 用工具，MCP 提供工具**。

## 五、安全：必须认真对待的部分

1. **工具描述注入（Tool Poisoning）**：恶意 Server 可在工具 description 中藏指令，
   诱导模型泄露数据或执行危险操作。工具描述是"给模型看的"，不等于可信文本。
2. **混淆代理（Confused Deputy）**：Agent 拿着用户的授权去访问第三方资源时，
   可能被恶意 Server 利用。远程 MCP 的授权基于 OAuth 2.1（强制 PKCE S256），
   客户端必须校验 token 受众与签发方。
3. **审批机制**：好的 Host 应对敏感工具调用做人工确认（尤其是写操作、外发数据）；
   sampling/elicitation 这类"Server 反向请求用户"的能力本身就是人机协同的安全阀。
4. **技能包风险**：Skill 里可能捆绑可执行脚本。有研究统计社区技能中相当比例存在
   安全问题（如 XSS/注入类缺陷），引入第三方 Skill 前应审查其脚本与来源，
   生产环境建议建立技能白名单与权限分级。

## 六、实践清单

- [ ] 本地工具用 stdio，远程/共享工具用 Streamable HTTP
- [ ] 写 Server 时：工具描述写给模型看——说清"何时用、参数含义、返回结构"
- [ ] 工具粒度宁粗勿细：给模型 5 个含义清晰的工具好过 50 个易混工具
- [ ] 工具返回错误时返回可读的错误信息（让模型自我纠正），而不是抛异常断连
- [ ] 确认 SDK 与目标规范版本匹配（2026-07-28 无状态版行为差异大）
- [ ] 远程 Server 必做：OAuth 2.1 + Origin 校验 + TLS
- [ ] Skill 的 description 同时写"做什么"和"什么时候用"，否则永远不会被触发
- [ ] Skill 正文超 ~500 行就拆到 references/，脚本放 scripts/
- [ ] 第三方 Skill / Server 引入前人工审查，敏感操作保留人工审批

## 七、新手常踩的坑

1. **把 sampling/elicitation 当 Server 能力**：方向反了，安全边界设计会整个错掉。
2. **在 description 里只写"是什么"不写"何时用"**：模型不知道什么时候该调用，
   工具形同虚设；Skill 同理，description 是触发开关。
3. **stdio Server 里 print 调试**：stdout 是协议通道，print 会污染 JSON-RPC 流导致
   连接崩溃；调试日志请走 stderr。
4. **混淆 MCP 规范版本**：网上大量教程基于 2025-03/06 版（有会话、有握手），
   在 2026-07-28 无状态版 SDK 上可能直接跑不通；看文档先看版本日期。
5. **认为 MCP 工具越多越好**：工具列表膨胀会稀释模型注意力、拉高 token 成本，
   优先合并语义重复的工具。
6. **把 Skill 当成 MCP 的竞品**：二者层次不同，"连接"用 MCP，"方法论"用 Skill，
   好的 Agent 两者都用。
7. **信任工具返回内容**：工具结果属于不可信输入，Host 应做注入检测，
   不要把返回文本直接拼接进高权限指令。

## 延伸阅读

- MCP 官方规范与博客：modelcontextprotocol.io / blog.modelcontextprotocol.io
- Agent Skills 开放标准：agentskills.io
- Anthropic 工程博客《Equipping agents for the real world with Agent Skills》
