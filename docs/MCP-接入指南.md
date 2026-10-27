# 用 WorkBuddy 接入你的知识库 MCP

> 服务器端的 MCP 服务（`mcp` 容器，Streamable HTTP，端口 9001）随部署已就绪，
> nginx 在 `/mcp` 路径上挂了 `X-MCP-Token` 门禁。本文只讲**客户端怎么接**。
> 接入后，你可以在 WorkBuddy 的任何对话里调用 `search_docs` / `get_document` / `list_documents`
> 三个工具，随时检索自己的博客、基础知识库和开源日报。

## 一、拿到访问令牌（token）

token 在服务器的 `.env` 里（不会进 git）：

```bash
ssh root@47.107.167.9
grep MCP_TOKEN /opt/agentic_rag/.env
```

输出形如 `MCP_TOKEN=a1b2c3...`（32 位 hex）。复制 `=` 后面的部分。**这个 token
等价于你知识库的读取权限，不要发到聊天、截图或公开仓库里。**

## 二、配置 WorkBuddy

编辑（不存在则新建）`C:\Users\<你>\.workbuddy\mcp.json`：

```json
{
  "mcpServers": {
    "agentic-rag": {
      "url": "http://47.107.167.9/mcp",
      "headers": {
        "X-MCP-Token": "刚才复制的token"
      }
    }
  }
}
```

两个必须注意的格式细节：

1. **URL 末尾不要带斜杠**——写成 `/mcp`，不要写 `/mcp/`。FastMCP 对带尾斜杠的
   路径会回 307 重定向，部分 MCP 客户端拒绝跟随重定向，导致握手失败；
2. `headers` 里的键名必须是 `X-MCP-Token`，与 nginx 门禁校验的头一致。

保存后**完全退出并重启 WorkBuddy**（mcp.json 只在启动时读取）。

## 三、信任并启用

WorkBuddy 左下角「+」→ 连接器管理 → 页面**右上角「自定义连接器」**入口 →
列表里找到 `agentic-rag` → 点**信任**。

## 四、验证

三层验证，从外到内：

```bash
# 1. 门禁拒绝：无 token 应返回 403
curl -s -o NUL -w "%{http_code}" http://47.107.167.9/mcp/
# 期望输出：403

# 2. 门禁放行：带 token 应返回 200 或 307/406（FastMCP 对 GET 的正常响应）
curl -s -o NUL -w "%{http_code}" -H "X-MCP-Token: 你的token" http://47.107.167.9/mcp
```

3. 在 WorkBuddy 新开一个对话，问：**「帮我查查我博客里受限 ReAct 的设计动因」**——
   看到先调用 `search_docs` 再回答，即为全链路贯通（本配置已实测：
   `search_docs("受限 ReAct 的设计动因")` top1 命中 blog-01，score 0.80）。

## 五、接入其他 MCP 客户端

任何支持 Streamable HTTP 传输的 MCP 客户端（Claude Desktop、Cline 等）配置方式
同构——关键是三要素：**URL（无尾斜杠）+ 自定义头 `X-MCP-Token` + MCP 协议版本
与客户端实现兼容**。Claude Desktop 若只支持 stdio，可用 `mcp-remote` 桥接：

```json
{
  "mcpServers": {
    "agentic-rag": {
      "command": "npx",
      "args": ["mcp-remote", "http://47.107.167.9/mcp",
               "--header", "X-MCP-Token: 你的token"]
    }
  }
}
```

## 六、故障排查

| 症状 | 原因 | 处理 |
|---|---|---|
| 全部请求 403 | token 错误 / `.env` 里 MCP_TOKEN 为空 / 改了 token 没重建容器 | 核对 `.env`；改过 token 需 `docker compose -f docker-compose.prod.yml up -d` 重建 frontend |
| 请求返回 index.html（200） | 打到了旧版 nginx（无 /mcp 路由） | 确认 deploy 已完成、frontend 容器已重建 |
| 307 重定向报错 | URL 带了尾斜杠 | mcp.json 里改成无尾斜杠的 `/mcp` |
| 握手超时 | 服务器 GHCR/网络抖动，mcp 容器未正常启动 | SSH 上去 `docker compose -f docker-compose.prod.yml ps` 查看 mcp 状态 |
| 工具能列出但检索结果为空 | 语料还没摄取 | 检查 `/api/health` 的 documents 数，push 后等 CI 摄取完成 |

## 七、token 轮换

token 怀疑泄露时：

```bash
# 服务器上换新值
ssh root@47.107.167.9
cd /opt/agentic_rag
sed -i "s/^MCP_TOKEN=.*/MCP_TOKEN=$(openssl rand -hex 16)/" .env
grep MCP_TOKEN .env                      # 复制新值
docker compose -f docker-compose.prod.yml up -d   # 重建 frontend 使新值生效
```

然后同步更新 WorkBuddy 的 `mcp.json`。旧 token 立即失效。
