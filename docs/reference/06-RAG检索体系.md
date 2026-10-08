# RAG 检索体系：数据模型、混合检索、渐进式披露与评测

> 来源：wealth-manager 项目文档 `docs/KNOWLEDGE_AND_DATA_CATALOG_ARCHITECTURE.md`（知识库分层/Scope/数据目录）、`docs/RAG_BM25_全链路复盘.md`（混合检索选型与三路评测）、`docs/RAG_BM25_paradedb_runbook.md`（pg_search 落地与 key_field 修正）、`docs/渐进式披露RAG-三MCP设计方案.md`（三 MCP 设计）、`docs/AGENT_RAG_EVALUATION_GUIDE.md`（评测指标体系）
> 说明：由 wealth-manager 项目文档按主题重写，重写于 2026-10-08。BM25 索引写法以 runbook 2026-09-14 修正版（`bm25(id, content)`）为准；目录/NL2SQL 部分保留其"未来演进设计"定位，仅收录最终设计结论。

---

## 1. 知识库数据模型与摄取管线

### 1.1 核心实体

基于 PostgreSQL / pgvector 的知识库底座，关键实体：

```text
KnowledgeBase
KnowledgeDocument
KnowledgeDocumentVersion
KnowledgeChunk
OutboxEvent
```

### 1.2 管理员上传摄取管线

```text
管理员后台上传 TXT / MD / DOCX
  → 保存至 uploads/knowledge
  → 创建 KnowledgeDocument（processing）
  → 写入 knowledge.document_created Outbox 事件
  → outbox-worker 发布到 Redis ingestion Stream
  → knowledge-worker 解析、切分、Embedding
  → 写入 knowledge_chunk.embedding（pgvector）
  → 文档状态 active / failed
```

上传界面的"公司信息、公司业务、FAQ、服务流程、金融政策、风险资料"等选项是 `KnowledgeDocument.category`，不是物理上彼此独立的向量库。文档默认进入同一个逻辑默认库（`default`），再按分类、可见范围和调用方 Scope 控制检索。

### 1.3 四层概念分层

```text
知识域（KnowledgeDomain）
  → 决定谁可上传、默认权限、审核策略、允许哪些分类。

逻辑知识库（KnowledgeBase）
  → 决定资料属于哪个大的业务治理边界。

分类（Category）
  → 决定同一逻辑库中的具体资料类型。

文档元数据（Metadata）
  → 决定具体文档关联对象、版本、生效期、审核状态、可见性等。
```

建议的逻辑知识库划分：

| 逻辑库代码 | 用途 | 典型检索方 |
|---|---|---|
| `customer_public` | 公司信息、业务、FAQ、流程、客户可见政策/风险资料 | 智能客服、客户中心 |
| `product_evidence` | 产品说明书、风险揭示、费率、流动性、产品条款证据 | 投顾、产品经理；客户仅限审核范围 |
| `advisor_internal` | 投顾内部话术、培训、服务方法 | 投顾、管理人员 |
| `compliance_internal` | AML、合规制度、内部风控手册 | 风控、合规、审计 |

**物理隔离原则**：不必为每个逻辑库建立不同 PostgreSQL 实例、不同 pgvector 集群、不同 Worker 或不同表；先共用现有知识库表和向量索引，仅通过 `knowledge_base_id`、`category`、`permission_level`、元数据和 Scope 实现逻辑隔离。只有出现强合规隔离、多租户物理隔离、量级/性能差异、不同 Embedding 模型、独立备份/审计或独立部署要求时，才考虑物理拆库。

### 1.4 摄取的轻量抽象

#### KnowledgeDomain 配置

集中定义：域代码、逻辑库代码、允许分类、可用可见范围、上传者角色/权限、默认审核状态、是否允许自动激活。例如：

```text
customer_public：允许 faq/workflow/policy，默认 public，自动激活。
product_evidence：允许 prospectus/risk_disclosure，默认 staff，需审核后激活。
```

#### 统一上传命令

```python
KnowledgeIngestionCommand(
    domain="customer_public",
    category="faq",
    file=...,
    permission_level="public",
    metadata={...},
)
```

统一由 `KnowledgeDocumentUploadService` 负责：上传者权限校验、Domain/Category 合法性校验、文件存储与 hash、文档与版本元数据、Outbox 事件、审计日志、队列状态返回。管理员后台、产品系统同步、批量脚本、CMS 接入都复用同一服务。

#### 检索端只依赖 Scope

检索方不关心文件如何上传，只声明受控检索范围：

```python
KnowledgeScope(
    knowledge_base_ids=(...),
    categories=(...),
    permission_levels=(...),
    metadata_filters={...},
)
```

业务模块应使用集中定义的固定 Scope，不能全库盲搜：

```text
CUSTOMER_PUBLIC_SCOPE
PRODUCT_EVIDENCE_SCOPE
ADVISOR_INTERNAL_SCOPE
COMPLIANCE_INTERNAL_SCOPE
```

### 1.5 产品资料的审核生效机制

产品文档可先在逻辑域下增加分类（`product_overview`、`prospectus`、`risk_disclosure`、`fee_rule`、`liquidity_rule`、`performance_note`），上传时默认员工/投顾可见。规模化治理后要求元数据：

```json
{
  "product_id": "...",
  "product_code": "...",
  "document_kind": "prospectus",
  "approval_status": "approved",
  "effective_date": "2026-08-06",
  "expires_at": null,
  "customer_visible": false,
  "source_system": "admin_upload"
}
```

生命周期：`上传 → 切分/向量化 → pending_review → 审核通过 → active`。

---

## 2. 向量 + BM25 混合检索

### 2.1 问题与选型

原方案文本腿用 PostgreSQL `to_tsvector + ts_rank_cd`（PG `simple` 配置），中文不切词 → ts_rank 多为 0 → 中文下文本腿常退空、实际近似纯向量检索。

候选方案对比：

| 方案 | 说明 | 结论 |
|---|---|---|
| A：pg_search / ParadeDB | 在同一个 PostgreSQL 库内提供 BM25，向量(pgvector)与关键词(BM25)共存 | **选定**，契合"pgvector 单库少运维"架构 |
| B：Elasticsearch/OpenSearch | 标准 BM25，但要加一个服务 + 运维 | 弃用——关键词腿只是辅助，向量腿才是主力，为它引独立引擎不值 |

### 2.2 代码层实现

- `app/core/settings.py`：新增 `fulltext_backend`（`tsvector` / `pg_search`）+ 校验，默认 `tsvector` 作安全兜底。
- `app/repositories/knowledge.py`：
  - `search_hybrid` 文本腿抽成 `_rank_text_branch`（按 fulltext_backend 分发）；
  - `_rank_text_tsvector`：保留原 ts_rank 逻辑（默认）；
  - `_rank_text_pg_search`：BM25（`content @@@ :q` + `paradedb.score(id)`），带 scoped/激活过滤，**独立连接事务隔离**；
  - `_extract_pg_search_terms`：中文拆词（剥停用词 + 长短语字 bigram），空格连接（pg_search 空格默认 OR）。
- compose：本地 + 生产 postgres 镜像 → `docker.m.daocloud.io/paradedb/paradedb:pg16`；api 默认 `FULLTEXT_BACKEND=pg_search`。
- 脚本 `scripts/enable_pg_search_bm25.sql` + 单测 `test_fulltext_backend_config.py`、`test_pg_search_term_extractor.py`。

### 2.3 三路召回评测

对比 **只向量 / 只关键词(BM25) / 双路(RRF)** 在真实知识库上的召回。方法：复用确定性指标（`gold_fragments` → fragment_recall / hit_rate，不依赖 LLM/RAGAS；RAGAS 因缺过时依赖弃用）。评测集从 16 条扩到 **64 条**（新增 48 条基于真实文档内容，gold 逐条校验存在于库中，不编造）。

结果（64 条，按 intent 分层）：

| 检索路径 | fragment_recall | hit_rate |
|---|---|---|
| vector | 99.2% | 100% |
| keyword (BM25) | 96.1% | 97% |
| hybrid (RRF) | 96.1% | **100%** |

结论：

- 向量腿在语义问答语料上是主力；关键词腿补精确词；hybrid hit_rate 最高（补 keyword 漏的 faq/company_info）。
- 样本不均衡时要按 intent 分层，整体汇总会掩盖差异。
- "双路 recall 略低于单路"是 RRF top_k 截断的评测假象，不是真退化。

### 2.4 关键 Bug 与教训

1. **事务污染**：pg_search 失败把共享 session 事务 abort → 降级跑 tsvector 时 `InFailedSqlTransactionError`。→ pg_search 分支用独立连接隔离。
2. **中文整句 0 命中**：BM25 是词级检索，整句不分词不命中。→ 应用层中文拆词 + 字 bigram + OR。
3. **评测假象**：双路 RRF top_k 截断导致"双路 recall < 单路"假象。→ 按 intent 分层、调参，不下错误结论。
4. **镜像坑**：DaoCloud 加速源对某些仓库 403；`latest` 是 PG18，与 PG16 数据卷不兼容；需用 ParadeDB pg16 tag。
5. **shared_preload**：pg_search 需先在 `shared_preload_libraries` 加 `pg_search` 并重启，才能 `CREATE EXTENSION`。

### 2.5 方法论

- **可插拔 + 默认兜底**：新能力默认关闭/可回退，避免一换就崩（tsvector 兜底 + 降级）。
- **事务隔离**：黑盒/可选扩展的失败不应污染主事务。
- **评测样本均衡**：按 intent 分层看指标；gold 必须真实存在于语料。
- **部署先数据安全**：换镜像前先备份数据卷；确认 PGDATA 路径与镜像一致再重建。

---

## 3. ParadeDB / pg_search 落地要点

### 3.1 环境事实

| 项 | 值 |
|---|---|
| 目标镜像 | `docker.m.daocloud.io/paradedb/paradedb:pg16`（服务器可直连 Docker Hub 时用 `paradedb/paradedb:pg16`）|
| 镜像内容（实测） | PostgreSQL 16.15 + `vector` 0.8.4 + `pg_search` 0.25.6 |
| 镜像 PGDATA | `/var/lib/postgresql/data`（与 pgvector 相同 → 卷挂载路径不变）|
| 数据兼容 | PG 主版本一致(16)，同一 PGDATA 路径 → 原卷无缝换引擎 |
| 代码降级 | pg_search 异常自动回 tsvector，检索不崩 |

### 3.2 运行时启用步骤

```bash
# 1. 备份后再换镜像
docker run --rm -v wealth_pgdata:/data -v "${PWD}:/backup" alpine \
  tar czf /backup/wealth_pgdata_$(date +%Y%m%d).tar.gz -C /data .
docker compose -f docker-compose.p0.yml up -d --force-recreate postgres

# 2. 加载 pg_search（shared_preload）+ 建扩展
docker exec wealth-postgres psql -U wealth -d wealth_manager -c \
  "ALTER SYSTEM SET shared_preload_libraries = 'pg_search';"
docker restart wealth-postgres
docker exec wealth-postgres psql -U wealth -d wealth_manager -c \
  "CREATE EXTENSION IF NOT EXISTS pg_search;"

# 3. 建 BM25 索引（字段列表必须含 key_field 指名的列）
docker exec wealth-postgres psql -U wealth -d wealth_manager -c \
  "CREATE INDEX IF NOT EXISTS idx_knowledge_chunk_content_bm25 \
   ON knowledge_chunk USING bm25 (id, content) WITH (key_field='id');"
```

> ⚠️ **重大教训（key_field 阻塞写入）**：索引写法 `USING bm25(content) WITH (key_field='id')` 是错误的——该写法能建索引、能查询，但**任何 INSERT 都报 `No key field defined`**，即知识库所有写入失败（上传接口、worker、导入脚本），且不报错到检索侧，长期未被发现。正确写法必须把 key_field 指名的列写进字段列表：`bm25(id, content)`。该索引已纳入迁移 `migrations/versions/0025_knowledge_bm25_key_field.py`，新库按迁移建即可。
>
> 另：ParadeDB 限制**一表只能有一个 bm25 索引**，重建只能 `DROP` 后 `CREATE`，不能"先建新索引再切换"。

### 3.3 验证

```bash
# 单词精确命中
docker exec wealth-postgres psql -U wealth -d wealth_manager -c \
  "SELECT count(*) FROM knowledge_chunk WHERE content @@@ '适当性';"
# 应用代码路径（实测整句拆词召回 5 条，相关文档排前）
python scripts/debug_rag_retrieval.py --query "什么是适当性管理" --top-k 5
```

### 3.4 中文召回的关键认知

- BM25（pg_search）是**关键词精确/子串命中**，不是语义。中文整句不切分会 0 命中。
- 方案：代码层把整句 query 拆成中文关键词（剥停用词、长短语用字 bigram），空格连接走 pg_search 默认 OR；语义排序由**向量腿**承担，两腿 RRF 融合。
- 实测：`适当性` → 12 条命中；bigram OR 召回相关 chunk；整句 query 经代码 path 返回 5 条正确文档。
- 可选调优：若召回精度不理想，可引入真正的 jieba（Python 侧）或在索引侧配 jieba tokenizer，而非应用层字 bigram。

### 3.5 回退安全网

- 关 BM25：`FULLTEXT_BACKEND=tsvector` 重启 api（代码自动降级，无需动数据）。
- 完全回旧镜像：先恢复备份，compose 镜像换回 `pgvector/pgvector:pg16`。

---

## 4. 渐进式披露 RAG：三 MCP 设计（搜文件 / 看大纲 / 读文件）

### 4.1 核心思想

> **渐进式披露**：先用最便宜的手段把候选缩到最小，再逐层打开，最后才读真正相关的内容。让模型永远不把无关内容读进上下文。

链路：

```text
file_search（元数据/目录） → file_outline（结构/大纲） → file_read（正文片段）
  └─ 分库预筛（第一道过滤+权限）在前
```

三个 MCP 拆分的理由：**职责单一、接口顺序天然强制"先看目录再打开"**——比在提示词里写"先查目录再读"更可靠。原则：能用接口结构保证的，就别只靠提示词。

### 4.2 接口设计

#### MCP 1: `file_search`（搜文件——只查元数据，不读正文）

```jsonc
{
  "tool": "file_search",
  "args": { "query": "string", "knowledge_base_id?": "string", "category?": "string", "top_k": 10 },
  "returns": [{
    "file_id": "string",
    "title": "string",
    "summary": "string",        // 一句话摘要，要有检索价值（决定要不要打开）
    "category": "string",
    "source": "string",          // 库/分类/权限
    "size_bytes": "int",
    "structured": "bool"         // 预标记是否有结构（供 file_outline 判断）
  }]
}
```

- 只在元数据层检索（标题/摘要/别名/分类），**不读正文**。
- 摘要质量是核心：写"订单服务的幂等和重试"比写"订单模块"有用——模型靠它判断要不要打开。

#### MCP 2: `file_outline`（看大纲——结构感知，返回带位置指针的层级）

```jsonc
{
  "tool": "file_outline",
  "args": { "file_id": "string" },
  "returns": {
    "file_id": "string",
    "status": "structured" | "flat" | "skip",
    "headings": [
      { "level": 1, "title": "string", "page": 12, "start_char": 12345, "char_len": 2000 }
    ],
    "reason": "string"           // status=skip 时说明（字数太少/无结构）
  }
}
```

status 语义：

| status | 含义 | 后续行为 |
|---|---|---|
| `structured` | 可导航 | `file_read` 用位置指针跳转 |
| `flat` | 有文本但推断不出层级 | 走全文读取 |
| `skip` | 字数太少/无结构 | 直接 `file_read` 全文，跳过导航 |

位置指针用 **page + start_char 双保险**（PDF 用页，纯文本用字符偏移）。

#### MCP 3: `file_read`（读文件——按定位直读正文片段）

```jsonc
{
  "tool": "file_read",
  "args": { "file_id": "string", "page?": "int", "start_char?": "int", "end_char?": "int", "heading?": "string" },
  "returns": { "content": "string", "source": "string", "page": "int", "start_char": "int" }
}
```

### 4.3 大纲生成（file_outline 的核心）

大纲 = **章节层级 + 每章节的位置指针**。关键不是"有哪些标题"，而是**每个标题在第几页/哪个字符偏移**——没有位置指针的大纲只是目录，没法导航。

按文档类型的解析器（优先级从高到低）：

① **Markdown**——正则解析标题：

```python
import re
outline = []
for m in re.finditer(r'(?m)^(#{1,6})\s+(.*)$', text):
    outline.append({"level": len(m.group(1)), "title": m.group(2).strip(),
                    "start_char": m.start()})
```

② **DOCX**——用标题样式：

```python
import docx
doc = docx.Document(path)
for i, p in enumerate(doc.paragraphs):
    style = p.style.name
    if style.startswith("Heading"):            # "Heading 1" 等
        outline.append({"level": int(style.split()[-1]), "title": p.text,
                        "paragraph_index": i})
```

> 前提是文档用了 Word"标题样式"；若用了大纲级别，用 `p.paragraph_format.outline_level` 更准。

③ **PDF 有内嵌书签**（最简单最准）——直接读 outline：

```python
import fitz  # PyMuPDF
doc = fitz.open(path)
toc = doc.get_toc(simple=True)   # [[level, title, page], ...]
```

④ **PDF 无书签但有文本（生 PDF）**——字体/字号推断标题：

```python
import fitz
doc = fitz.open(path)
for page in doc:
    d = page.get_text("dict")
    for block in d["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text, size, flags = span["text"].strip(), span["size"], span["flags"]
                bold = flags & 16
                if text and (size > 正文阈值 or bold):
                    outline.append({"level": 按字号/加粗分级, "title": text,
                                    "page": page.number + 1})
```

⑤ **扫描件 / 无结构 PDF**——OCR 后推断或 LLM 兜底：扫描件先用 **MinerU**（版面分析+OCR）输出结构化 Markdown 再走 ①；实在没结构，把文本喂 LLM 返回结构化大纲 JSON。

处理顺序与兜底：

```text
Markdown标题 → DOCX标题样式 → PDF内嵌书签(get_toc) → 字体字号推断 → (扫描件)MinerU/OCR → LLM兜底
```

先试"免费且精确"的原生结构，解析不到才降级到推断/LLM。每类解析器输出统一 `{level, title, page, start_char, char_len}`。

### 4.4 自适应规则

| 条件 | 行为 |
|---|---|
| 文档字数 < 阈值（如 2000） | `status=skip`，`file_read` 直接读全文，省一跳 |
| 推断不出层级（纯文本/表格堆叠） | `status=flat`，走全文读取 |
| 有清晰层级 | `status=structured`，按位置读片段 |

判断依据 = 字数/结构复杂度阈值，运行时动态决定，不是死板流程。

### 4.5 安全与边界

1. **分库预筛在前**：`file_search` 只在该问题对应的库/分类内搜（第一道过滤 + 权限边界）。
2. **只读强制**：三个 MCP 全部只读，不碰任何写操作。
3. **权限**：每个 MCP 校验 RBAC 权限码 + `KnowledgeScope`；`file_read` 返回内容前二次校验文件权限。
4. **溯源**：`file_read` 返回 source/page/start_char，答案绑定 文档→章节→页码，可审计。
5. **低置信/失败降级**：搜不到 → 澄清；读不到 → 转人工（复用 `customer_rag_handoff`）。

### 4.6 落地优先级

| 阶段 | 内容 | 说明 |
|---|---|---|
| P0 | Markdown + DOCX + PDF 书签三类解析器 + `file_outline` 统一输出 | 覆盖大部分结构化制度/产品文档，最准、最好做 |
| P1 | PDF 字体字号推断（无书签生 PDF） | 可选，扩展覆盖 |
| P2 | MinerU/OCR（扫描件）+ LLM 兜底 | 成本高，作降级 |
| P3 | 三个 MCP 接入 Agent 执行链路 + 评测 | 验收命中率/引用正确率 |

### 4.7 验收标准

- `file_search` 只在元数据层检索、不读正文；`file_outline` 返回带位置指针的层级；`file_read` 能按位置跳转直读原文。
- 短文档/无结构文档正确 `skip`/`flat`，不强制走导航。
- 分库/权限隔离生效：无权文件搜不到、读不到。
- 命中率/引用正确率/低置信转人工率在评测集上有数据。

---

## 5. RAG 评测方法

### 5.1 评测分层

1. **硬安全门禁**：零越权、零未经确认交易、零自由 SQL、零知识 Scope 泄露。
2. **Agent 行为评测**：路由、任务拆解、工具、参数、约束、澄清、人工转接和任务完成。
3. **RAG 检索与生成评测**：先测是否找对证据，再测答案是否忠实和完整。
4. **综合系统评测**：真实 HTTP、数据库、Redis、Worker、前端 E2E、并发、延迟和成本。

### 5.2 RAG Golden Dataset

建议 `tests/fixtures/rag_eval_cases.json` + `scripts/run_rag_eval.py`。每条样本标注：query、intent、允许 Scope、期望文档、期望 Chunk、必需事实、是否可回答、是否应转人工、当前生效版本和禁止知识域。

数据集必须覆盖：正向问题、无答案问题、旧版本问题、跨 Scope 问题、问候问题、Embedding 降级问题和文档更新问题。

### 5.3 检索层指标

| 指标 | 定义 |
|---|---|
| Recall at K | Top K 是否包含正确证据，客服场景重点看 Recall at 5 |
| Precision at K | Top K 中相关 Chunk 的比例 |
| MRR | 第一个正确证据排名倒数的平均值 |
| NDCG at K | 多证据和分级相关性排序质量 |
| active_version_hit_rate | 当前生效版本 Chunk 占返回结果的比例 |
| scope_leak_rate | 返回未授权知识的请求数 ÷ 总请求数，**目标为零** |

### 5.4 生成层指标

| 指标 | 定义 |
|---|---|
| faithfulness | 答案中被证据支持的事实数 ÷ 答案事实总数 |
| answer_relevance | 是否直接回答用户问题且没有无关扩展 |
| completeness | 覆盖必需事实数 ÷ 必需事实总数 |
| citation_precision | 有效引用数 ÷ 总引用数 |
| citation_recall | 带有效引用的关键事实数 ÷ 应引用关键事实数 |
| correct_abstention_rate | 无答案问题上正确拒答或转人工的比例 |

### 5.5 硬安全发布门槛

以下指标不应用平均值掩盖，应作为发布门槛（任一不满足时，不应扩大 fallback、共享记忆或自动化业务能力）：

```text
security_incident_count = 0
forbidden_tool_call_rate = 0
scope_leak_rate = 0
unverified_trade_submission_count = 0
free_sql_execution_count = 0
unsupported_high_risk_answer_rate = 0
```

### 5.6 已实现链路中的评测点

- **问候分流**：`CustomerRagService.greeting_message` 应避免对"你好、你是谁、谢谢、再见"等问题触发检索或工单。
- **查询归一化**：`normalize_customer_query` 将客户规模、客服电话等表达扩展为同义检索词，应通过 A/B 比较扩展前后的 Recall at 5、MRR 和额外延迟。
- **Embedding 降级**：有向量时走 hybrid search，无向量时走 text search；需要比较正常路径和降级路径的成功率、延迟、答案质量和转人工率。

### 5.7 三路召回评测方法（确定性指标）

除 LLM 评测外，项目用确定性召回评测验证检索链路（见 §2.3）：以 `gold_fragments` 为基准计算 fragment_recall / hit_rate，不依赖 LLM/RAGAS。核心纪律：

- gold 必须逐条校验真实存在于语料中，不编造；
- 按 intent 分层报告指标，整体汇总会掩盖差异；
- 警惕 RRF top_k 截断造成的"双路不如单路"评测假象。

---

## 6. 多来源路由与权威来源（架构边界）

知识文档、实时业务表、规则服务和操作接口可能描述同一业务主题，但职责不同。系统不采用"RAG 与数据库二选一"或"由模型自行选择来源"，而采用：

```text
事实 → 业务 API / PostgreSQL
决策 → 适当性、授权、风控、账户等业务服务
解释 → RAG 文档与引用
操作 → 受控业务 API、确认、状态机和审计
```

| 类型 | 示例 | 首要来源 | 返回策略 |
|---|---|---|---|
| 纯知识 | 公司名称、FAQ、服务流程、公开政策 | RAG | 引用回答；不足时转人工 |
| 纯事实 | 订单状态、账户余额、持仓、产品实时可售状态 | 业务 API | 直接返回实时事实；不让 RAG 推断 |
| 事实+解释 | 为什么订单审核中、为什么不能赎回 | 业务 API + RAG | 先事实，再用 RAG 解释规则/下一步 |
| 受控建议/操作 | 产品推荐、下单、赎回、转账 | 业务服务/API | 业务服务决定；RAG 只提供条款与证据 |

优先级：实时数据 > 已审核生效文档 > 普通文档 > 模型生成内容。业务事实必须先返回；RAG 解释慢、失败或无依据时，只降级解释，不得隐藏或延迟已授权的实时事实。Router 先用轻量规则/实体识别分流（问候直接回复、订单/账户走业务 API、FAQ 走 RAG），避免每个问题都触发 Embedding/模型调用。
