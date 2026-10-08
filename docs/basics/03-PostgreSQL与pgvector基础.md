# PostgreSQL 与 pgvector 基础

> 类型: 通用基础知识（与项目无关）

面向用过 MySQL、正在接触 PostgreSQL，或准备做向量检索（RAG、语义搜索）的工程师。重点讲"PG 差异在哪"和"pgvector 怎么用"，不重复关系库通识。

## 1. 它是什么，适用场景

PostgreSQL（简称 PG）是最先进的开源关系型数据库，现行主流版本 16/17。与 MySQL 相比，它更像一个"数据库平台"——通过扩展机制可以长出 JSON 文档库、全文检索、地理信息、向量检索等能力。

适合：

- 需要复杂数据类型（JSONB、数组、范围类型）的业务
- 复杂查询、CTE、窗口函数重度使用
- **AI 应用一站式存储**：业务表 + 向量（pgvector）放在同一个库里
- 想要"一个数据库从头用到尾"的中小团队

## 2. 与 MySQL 的关键差异

| 维度 | PostgreSQL | MySQL |
|---|---|---|
| 类型系统 | 严格，动态扩展（自定义类型、数组、JSONB） | 相对宽松 |
| 隐式类型转换 | 少而严格，类型不匹配直接报错 | 较多隐式转换（易踩坑） |
| JSON | JSONB 二进制存储，可建索引、有丰富操作符 | JSON 偏弱 |
| 全文检索 | 内置 tsvector/tsquery | 需 FULLTEXT，能力较弱 |
| 扩展机制 | 非常丰富（PostGIS、pgvector、CITUS…） | 较少 |
| 复杂查询 | CTE、窗口函数、并行查询成熟 | 8.0 后补齐 CTE/窗口 |
| 大小写 | 标识符默认折叠为小写（加引号才保留大写） | 表名大小写行为依平台而定 |
| MVCC 实现 | 旧版本行留在表内（需 VACUUM 清理） | undo log 回滚段 |

一个直观体感：PG 对类型很较真。`WHERE id = 'abc'`（id 是整数）在 PG 里直接报错，而 MySQL 可能默默转换。这既是优点也是"PG 怎么老报错"的第一来源。

## 3. 安装与连接

```bash
# Docker（推荐）
docker run -d --name pg17 -e POSTGRES_PASSWORD=123456 -p 5432:5432 pgvector/pgvector:pg17

# macOS
brew install postgresql@17 && brew services start postgresql@17
```

```bash
psql -h 127.0.0.1 -U postgres
```

常用 psql 元命令（不是 SQL，不带分号）：

```text
\l        列出数据库
\c mydb   切换数据库
\dt       列出表
\d users  查看表结构
\x        切换扩展显示（查宽表很方便）
\q        退出
```

## 4. 特色能力：JSONB / 数组 / CTE

### 4.1 JSONB

JSONB 是"已解析的二进制 JSON"，可查询、可索引，是 PG 的招牌能力。

```sql
CREATE TABLE products (
  id      SERIAL PRIMARY KEY,
  name    TEXT NOT NULL,
  attrs   JSONB NOT NULL DEFAULT '{}'
);

-- 插入
INSERT INTO products (name, attrs)
VALUES ('phone', '{"color": "black", "tags": ["5g", "oled"]}'::jsonb);

-- 查询操作符：-> 取 JSON，->> 取文本
SELECT attrs->>'color' AS color FROM products;
SELECT * FROM products WHERE attrs @> '{"color": "black"}';   -- 包含

-- GIN 索引让 @> 查询飞快
CREATE INDEX idx_attrs ON products USING gin (attrs);
```

什么时候用 JSONB：**字段 schema 多变、只读为主**的属性列（如商品扩展属性、LLM 的结构化输出）。核心业务字段（状态、金额、外键）仍然用普通列，这样才能建常规索引和外键约束。

### 4.2 数组

```sql
SELECT * FROM products WHERE '5g' = ANY (attrs->'tags');
CREATE TABLE articles (id int, tags text[]);
CREATE INDEX ON articles USING gin (tags);
SELECT * FROM articles WHERE tags @> ARRAY['db'];
```

### 4.3 CTE（WITH 查询）

复杂查询拆成有名子的中间步骤，可读性大幅提升：

```sql
WITH hot AS (
  SELECT product_id, sum(amount) AS total
  FROM orders WHERE created_at >= now() - interval '30 days'
  GROUP BY product_id
), top10 AS (
  SELECT * FROM hot ORDER BY total DESC LIMIT 10
)
SELECT p.name, t.total
FROM top10 t JOIN products p ON p.id = t.product_id;
```

## 5. 常用操作速查

```sql
-- 自增主键用 GENERATED 或 SERIAL（两者皆可，新代码推荐前者）
CREATE TABLE t (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()   -- 时间一律用 TIMESTAMPTZ
);

-- UPSERT（MySQL 的 ON DUPLICATE KEY UPDATE 等价物）
INSERT INTO t (id, name) VALUES (1, 'a')
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name;

-- 分页
SELECT * FROM t ORDER BY id LIMIT 20 OFFSET 40;

-- UPSERT 之外：INSERT ... RETURNING 拿回生成的主键（很常用）
INSERT INTO t (name) VALUES ('b') RETURNING id;
```

时间相关注意：PG 没有单数的 `DATETIME`，用 `TIMESTAMP`（无时区）或 `TIMESTAMPTZ`（带时区，推荐默认）。

## 6. 扩展机制

PG 的能力可以按需"插拔"，安装扩展通常是 `CREATE EXTENSION` 一句话：

```sql
CREATE EXTENSION IF NOT EXISTS vector;      -- pgvector 向量检索
CREATE EXTENSION IF NOT EXISTS "uuid-ossp"; -- UUID 生成
SELECT * FROM pg_available_extensions;      -- 看本机有哪些可用
```

云托管（RDS、Supabase、Neon 等）一般内置了常用扩展的安装开关。pgvector 的 Docker 镜像 `pgvector/pgvector` 自带扩展，本地试装最快。

## 7. pgvector：向量检索入门

### 7.1 核心概念

- **向量**：文本/图片经 embedding 模型转成的定长浮点数组（如 1536 维）
- **相似度**：常用距离算子三种
  - `<->` L2 距离（欧氏距离）
  - `<=>` 余弦距离（文本检索最常用）
  - `<#>` 负内积
- 需要保证向量维度与 embedding 模型输出一致

### 7.2 最小示例

```sql
-- 启用扩展
CREATE EXTENSION IF NOT EXISTS vector;

-- 向量列：vector(1536) 表示固定 1536 维
CREATE TABLE docs (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  content    TEXT NOT NULL,
  metadata   JSONB DEFAULT '{}',
  embedding  vector(1536) NOT NULL
);

-- 插入（真实场景 embedding 由代码调用模型生成后传入）
INSERT INTO docs (content, embedding)
VALUES ('什么是向量检索', '[0.1, 0.2, ... /* 1536 个数 */]');

-- 最近邻查询：找与给定向量余弦距离最近的 5 条
SELECT id, content, embedding <=> '[...]' AS distance
FROM docs
ORDER BY embedding <=> '[...]'
LIMIT 5;
```

### 7.3 索引：IVFFlat vs HNSW

数据量小（几万行以内）可以不建索引，精确暴力扫描也够快；数据量大后按需二选一：

| | IVFFlat | HNSW |
|---|---|---|
| 原理 | 先聚类分桶，查询时只搜最近的几个桶 | 多层跳表式图结构 |
| 速度 | 快 | 更快、高并发下表现更好 |
| 召回率 | 依赖列表数与 probes 参数 | 通常更高 |
| 建索引速度 | 快 | 慢、内存占用大 |
| 建议 | 简单场景、数据更新不频繁 | **新项目默认选它** |

```sql
-- HNSW：lists 是每个节点的最大连接数，一般默认即可
CREATE INDEX ON docs USING hnsw (embedding vector_cosine_ops);

-- IVFFlat：lists 建议约等于 行数/1000，且需先有数据再建
CREATE INDEX ON docs USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
-- 查询时可调 probes 换召回率：桶搜得越多越准越慢
SET ivfflat.probes = 10;
```

注意：算子与索引算子类要配对——用 `<=>` 就建 `vector_cosine_ops`，用 `<->` 就建 `vector_l2_ops`。

### 7.4 与关系数据混合查询

pgvector 最大的价值是**向量与普通 SQL 在一个事务里自由组合**：

```sql
-- 语义搜索 + 元数据过滤：这是 RAG 的标准查询形态
SELECT id, content, metadata->>'source' AS source,
       embedding <=> '[...]' AS distance
FROM docs
WHERE metadata->>'category' = 'finance'    -- 普通条件过滤
  AND created_at >= '2025-01-01'
ORDER BY embedding <=> '[...]'             -- 向量相似度排序
LIMIT 5;
```

给过滤字段建普通 B-tree/GIN 索引，与向量索引互不冲突。相比"向量库 + 业务库"两套系统，单库方案少了数据同步、双写一致性和跨系统事务的复杂度。

## 8. 容量与内存粗略估算心智

- **向量大小** ≈ 维度 × 4 字节。1536 维约 6 KB/行，100 万行 ≈ 6 GB 纯向量数据
- HNSW 索引还要占 1~2 倍于向量数据的内存才能发挥性能，所以 100 万条 1536 维向量，规划 10~20 GB 可用内存是合理起点
- 经验分界：**百万级以下** pgvector 非常从容；千万级开始要认真做分库/分区、降低维度（如换 512/768 维模型）或评估专用向量引擎
- 看实际占用：

```sql
SELECT pg_size_pretty(pg_total_relation_size('docs'));  -- 表+索引总大小
```

## 9. 新手常踩的坑

- **索引建了却没走**：向量索引只对 `ORDER BY embedding <=> ... LIMIT k` 这种模式生效；加了过滤条件后优化器可能仍走索引，但"先过滤后排序"在大数据量下召回可能受限——数据量大时关注"过滤后检索"（filtered search）问题
- **`=>` 与 `->` 混淆**：JSONB 取值是 `->` / `->>`；`=>` 不是 JSON 操作符
- **大小写敏感**：PG 里 `'Tom' <> 'tom'`，模糊匹配需要 `ILIKE` 或 `lower()` 处理
- **忘了 VACUUM**：频繁 UPDATE/DELETE 的表会产生死元组，靠 autovacuum 自动清理；表的"膨胀"会拖慢查询，别关闭它
- **IVFFlat 先建索引后插数据**：聚类中心基于建索引时的数据，空表建索引效果很差；IVFFlat 应在导入数据后再建
- **维度不匹配**：模型输出 1536 维，列定义 768 维会直接插入失败；升级 embedding 模型通常意味着重建表/列

## 10. 一页速查

| 需求 | 关键点 |
|---|---|
| 时间字段 | `TIMESTAMPTZ` + `now()` |
| 半结构化数据 | JSONB + GIN 索引 |
| 复杂分析查询 | CTE + 窗口函数 |
| 冲突即更新 | `ON CONFLICT ... DO UPDATE` |
| 向量列 | `vector(维度)`，先 `CREATE EXTENSION vector` |
| 相似度 | 文本检索默认用余弦 `<=>` |
| 向量索引 | 新项目默认 HNSW |
| RAG 查询 | 向量排序 + JSONB/普通列过滤混合 |
| 容量估算 | 维度×4B×行数，HNSW 再留 1~2 倍内存 |

记住三句话：PG 把"一个库干所有事"做到了可用性很高的程度；pgvector 的价值在于向量与关系数据同库混合查询；规模到百万行级之前，它几乎是 AI 应用存储的最省心选择。
