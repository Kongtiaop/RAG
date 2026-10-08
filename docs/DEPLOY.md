# 服务器部署指南（2C2G · 47.107.167.9）

> 设计原则：**构建在 GitHub Actions，服务器只拉取启动**。2C2G 上不做 docker build（pip install + 前端编译会把它打爆）。
> 继承 wealth-manager 的经验：pg_search 需要 shared_preload（ParadeDB 镜像已含）、部署先看数据安全（本库可随时重灌，风险低）。

## 架构

```
GitHub push (main)
  → Actions: build backend/frontend 镜像 → push GHCR
  → SSH 到服务器：git pull → compose pull → up -d → 增量 ingest → 健康检查

服务器: nginx(80, 对外) → api(8000, 仅本机) → postgres(5432, 仅本机)
```

## 一、GitHub 仓库配置（一次性）

Settings → Secrets and variables → Actions，添加：

| Secret | 值 |
|---|---|
| `SERVER_HOST` | `47.107.167.9` |
| `SERVER_USER` | 通常是 `root` 或你的用户名 |
| `SERVER_SSH_KEY` | 私钥全文（本地 `ssh-keygen -t ed25519` 生成，公钥追加到服务器 `~/.ssh/authorized_keys`） |
| `SERVER_PORT` | SSH 端口（默认 22 可不填） |

## 二、服务器初始化（一次性，SSH 上去执行）

```bash
# 1. 装 Docker（阿里云机器可用官方脚本或 yum/apt 源）
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker

# 2. 拉代码
mkdir -p /opt/agentic_rag && cd /opt/agentic_rag
git clone https://github.com/Kongtiaop/RAG.git .

# 3. 写 .env（不会进 git）
cat > .env <<'EOF'
DASHSCOPE_API_KEY=sk-你的key
LLM_MODEL=qwen-plus
EMBEDDING_MODEL=text-embedding-v4
POSTGRES_PASSWORD=换一个强密码
EOF

# 4. GHCR 登录（拉私有镜像；仓库若是 public 可跳过）
#    用一个有 read:packages 权限的 PAT
echo "ghcr.io 的PAT" | docker login ghcr.io -u Kongtiaop --password-stdin

# 5. 首次启动（等 GitHub Actions 首次构建出镜像之后）
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml run --rm api python -m app.ingest
curl http://127.0.0.1:8000/health
```

浏览器访问 `http://47.107.167.9/` 即可使用。

## 三、日常更新 = git push

push 到 main → Actions 自动构建镜像 → 服务器拉取 + 增量摄取（内容没变的文档跳过 embedding）→ 健康检查。服务器上什么都不用做。

## 四、2C2G 专项

- PG 已按 256MB shared_buffers 压线配置（docker-compose.prod.yml）；
- API/PG 端口只绑 127.0.0.1，公网只暴露 80；
- 服务器上的增量 ingest 只对变更文档重新 embedding，日常 push 几乎零成本；
- 阿里云安全组：放行 80，**不要**放行 5432/8000/22 以外的管理端口按需。

## 五、排障速查

```bash
docker compose -f docker-compose.prod.yml logs -f api      # 后端日志
docker compose -f docker-compose.prod.yml ps               # 容器状态
docker compose -f docker-compose.prod.yml exec postgres psql -U agentic_rag -d agentic_rag \
  -c "SELECT count(*) FROM chunks;"                        # 语料是否入库
free -h && docker stats --no-stream                        # 内存水位（2C2G 重点盯）
```

- Actions 部署步骤失败：先看是 build（本地复现 frontend/backend build）还是 SSH（secrets/安全组）；
- 服务器拉镜像 401：GHCR 未登录或包是私有（见上一步 4）；
- 拉取慢：阿里云机器配镜像加速器（系统配置 `/etc/docker/daemon.json`）。
