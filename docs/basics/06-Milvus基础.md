> 类型: 通用基础知识（与项目无关）

# Milvus 基础

> 版本说明：以 Milvus 2.5+ / pymilvus 2.5+ 的 `MilvusClient` 新 API 为准（旧代码里大量 `connections.connect` + `Collection` 的 ORM 写法已不推荐）。

## 一、是什么，解决什么问题

Milvus 是开源**向量数据库**：存 embedding 向量，按"相似度"而不是"精确匹配"来查询。解决的核心问题是——

> 当你有几百万、几十亿条文本/图片的向量，如何毫秒级找出"与这条查询向量最相似的 topK"？

暴力比对是 O(N)，数据量大了完全不可行。Milvus 用 ANN（近似最近邻）索引把查询降到亚线性，并补齐了数据库该有的东西：持久化、标量过滤、分区、水平扩展。典型场景是 RAG 的检索层、以图搜图、推荐召回。

**和 FAISS 的区别**：FAISS 只是算法库，不管持久化和并发，适合单机实验；Milvus 是完整数据库，适合服务化部署。Chroma 则胜在极简本地开发——数据量小（十万级以内）Chroma 够用，量大了或要生产化，Milvus 是主流选择。

## 二、三种部署形态

| 形态 | 资源需求 | 适用场景 |
|---|---|---|
| **Milvus Lite** | pip 安装即可，数据存本地一个 `.db` 文件 | 本地开发、原型、单元测试（百万级以下向量） |
| **Standalone** | 单机 Docker，几 GB 内存 | 小团队生产、单机服务 |
| **Distributed** | K8s 多组件集群，可水平扩展 | 亿级向量、高并发生产 |

选型一句话：**开发用 Lite，小规模生产用 Standalone，规模真上去了才上 Distributed**。三者 API 完全一致，代码可以无缝迁移。

⚠️ **Milvus Lite 只支持 Ubuntu >= 20.04 和 macOS >= 11.0，不支持 Windows**（Windows 用户走 WSL 或 Docker）。这也是很多新手第一次安装就报错的原因。

```bash
pip install -U pymilvus              # 核心SDK，自带 Lite 能力
pip install "pymilvus[milvus_lite]"  # 明确装上 Lite 依赖
```

Standalone 用 Docker 一行起服务：

```bash
docker run -d --name milvus -p 19530:19530 -p 9091:9091 milvusdb/milvus:latest milvus run standalone
```

## 三、核心概念

- **Collection**：相当于关系库里的"表"，存向量的容器。
- **Schema**：表结构。每个 collection 必须有一个**主键字段**和至少一个**向量字段**（2.5 起也支持多向量字段做混合检索），外加任意标量字段（int/str/bool/JSON）。
- **Partition**：collection 内的逻辑分区。按租户/日期等分区后，检索可以只扫一部分数据，提高效率。
- **Consistency Level（一致性级别）**：读写一致性的取舍，四档从强到弱：
  - `Strong`：读到最新写入，延迟最高；
  - `Bounded`：允许一小段时间的旧数据（默认，多数场景够用）；
  - `Session`：同一会话内读到自己的写入；
  - `Eventually`：最终一致，延迟最低。
- **Metric（距离度量）**：`COSINE`（余弦，文本 embedding 最常用）、`L2`（欧氏）、`IP`（内积）。**必须和 embedding 模型的训练度量匹配**。

## 四、最小可运行示例

建表 → 插入 → 检索，十行以内能跑通（Lite 形态，需要 `pip install pymilvus`）：

```python
from pymilvus import MilvusClient

# 传本地文件路径 = Milvus Lite；传 uri = 连接服务器
client = MilvusClient("./demo.db")
# client = MilvusClient(uri="http://localhost:19530")

# 1. 建表：简化模式，一个主键 + 一个向量字段 + 自动生成 schema
client.create_collection(collection_name="docs", dimension=4)

# 2. 插入
client.insert(
    collection_name="docs",
    data=[
        {"id": 1, "vector": [0.1, 0.2, 0.3, 0.4], "text": "Milvus 是向量数据库"},
        {"id": 2, "vector": [0.9, 0.8, 0.7, 0.6], "text": "LangGraph 编排 Agent"},
    ],
)

# 3. 检索：找与查询向量最近的 2 条
results = client.search(
    collection_name="docs",
    data=[[0.1, 0.2, 0.3, 0.35]],
    limit=2,
    output_fields=["text"],
)
for hit in results[0]:
    print(hit["id"], hit["distance"], hit["entity"]["text"])
```

生产上一般不用简化模式，而是显式定义 schema，把标量字段带上：

```python
from pymilvus import CollectionSchema, DataType

schema = client.create_schema(auto_id=True)
schema.add_field("id", DataType.INT64, is_primary=True)
schema.add_field("vector", DataType.FLOAT_VECTOR, dim=768)
schema.add_field("text", DataType.VARCHAR, max_length=1024)
schema.add_field("source", DataType.VARCHAR, max_length=256)

index_params = client.prepare_index_params()
index_params.add_index(field_name="vector", index_type="HNSW",
                       metric_type="COSINE", params={"M": 16, "efConstruction": 200})

client.create_collection(collection_name="docs2", schema=schema, index_params=index_params)
```

## 五、索引类型对比

索引决定"精度换速度"的权衡，新建 collection 时选一个：

| 索引 | 原理 | 精度 | 速度 | 内存 | 适用 |
|---|---|---|---|---|---|
| **FLAT** | 暴力全扫 | 100%（精确） | 慢 | 低 | 数据量 < 几万；做召回率基准 |
| **IVF 系列** | 先聚类分桶，查询只搜最近的几个桶 | 中 | 快 | 中 | 中等数据量，内存紧张 |
| **HNSW** | 多层跳表式图结构 | 高 | 很快 | **高** | 追求低延迟高召回，内存够 |

经验法则：**内存管够直接 HNSW；内存紧张或数据特大规模用 IVF 系列；要精确结果才用 FLAT**。参数方面，IVF 调 `nprobe`（搜几个桶），HNSW 调 `ef`（搜索时的候选队列长度），都是"越大越准越慢"。

## 六、混合检索与标量过滤

### 6.1 标量过滤：向量搜索 + where 条件

```python
results = client.search(
    collection_name="docs2",
    data=[[0.1] * 768],
    filter='source == "wiki" and id > 100',  # 类 SQL 的过滤表达式
    limit=5,
    output_fields=["text", "source"],
)

# 纯标量查询（不走向量）用 query
rows = client.query(collection_name="docs2", filter='source == "wiki"',
                    output_fields=["text"], limit=10)
```

先过滤再算相似度——这是向量库区别于纯 ANN 库的关键能力，也是"按租户/时间检索"的基础。

### 6.2 混合检索：稠密 + 稀疏向量

稠密向量（embedding）擅长语义，稀疏向量（BM25/SPLADE 类）擅长关键词精确匹配。两者各召回一路，再做融合（通常 RRF），就是 hybrid search。Milvus 原生支持多向量字段：

```python
# schema 里同时定义 dense 向量和 sparse 向量两个字段，分别建索引
# 检索时用 hybrid_search，一次请求两路召回 + 内置 rerank 融合
from pymilvus import AnnSearchRequest, RRFRanker

req_dense = AnnSearchRequest(data=[dense_vec], anns_field="dense", limit=10)
req_sparse = AnnSearchRequest(data=[sparse_vec], anns_field="sparse", limit=10)
results = client.hybrid_search(
    collection_name="docs2",
    reqs=[req_dense, req_sparse],
    ranker=RRFRanker(k=60),
    limit=5,
    output_fields=["text"],
)
```

## 七、新手常踩的坑

1. **Windows 上装 Lite 失败**。`MilvusClient("x.db")` 报 `milvus-lite is required`，因为 Lite 不支持 Windows。解法：WSL2、Docker 跑 Standalone，或干脆换 Zilliz Cloud 免费额度。
2. **embedding 维度不匹配**。建表时 `dimension=768`，插入的向量却是 1536 维（换了 embedding 模型忘改 schema），直接报错或静默错乱。**schema 的 dim 必须等于 embedding 模型的输出维度**，换模型 = 重建表 + 全量重灌。
3. **metric_type 和模型不匹配**。用 COSINE 训练的模型拿 L2 查，结果排序会错。OpenAI/BGE 等主流文本模型一般用 COSINE，别随手填 L2。
4. **内存占用超出预期**。HNSW + 原始向量常驻内存，千万级 768 维 float32 裸向量就 30GB。解法：标量字段少放、用标量索引（默认有）、大集合按 partition 拆、或升级到支持 mmap/磁盘索引的部署形态。
5. **插入后立刻搜，搜不到**。Milvus 写入是近实时的，数据先在增长段里。Lite/Standalone 一般间隔很小，但 `Strong` 一致性 + 刷新逻辑没对上时会踩到。必要时 `client.flush(collection_name)`，或检索端用 `Strong` 一致性。
6. **auto_id 模式下自己传 id 报错**。schema 设了 `auto_id=True`，插入数据就不能带 id 字段；主键返回值在 insert 结果里拿。
7. **忘了 load**。某些操作路径下 collection 需要 load 到内存才能检索（老 API 需要显式 `collection.load()`），`MilvusClient` 的 `search` 遇到未加载的集合会报 "not loaded"，`client.load_collection("docs")` 解决。
8. **用旧 ORM API 对照新教程**。网上旧代码全是 `connections.connect` + `Collection(...)` 写法，新项目统一用 `MilvusClient`，两套 API 混用容易把 schema 状态搞乱。

## 延伸阅读

- 官方文档：https://milvus.io/docs
- 实操组合：Milvus（检索层）+ LangChain/LangGraph（编排层）搭完整 RAG，参考同目录《LangChain 基础》《LangGraph 基础》
