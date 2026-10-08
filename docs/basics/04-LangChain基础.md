> 类型: 通用基础知识（与项目无关）

# LangChain 基础

> 版本说明：LangChain 已于 2025 年 10 月发布 1.0（此前长期停留在 0.x）。本文以 1.0 为主线，旧版差异单独标注。1.0 承诺 2.0 之前不再破坏性变更，可以放心入门。

## 一、它是什么，解决什么问题

直接调 LLM API 大概是这样：

```python
import openai

resp = openai.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "帮我总结这段文字：..."}],
)
```

能跑，但当需求变复杂时你会反复手写这些轮子：

- **换模型**：OpenAI 换成 Claude/Ollama/DeepSeek，参数和返回格式都不一样；
- **拼 Prompt**：模板、变量、few-shot 示例散落在字符串里；
- **接外部数据**：RAG 要自己管 embedding、向量库、检索、拼接上下文；
- **记忆与工具调用**：多轮对话历史管理、函数调用循环都要手搓。

LangChain 做的事就是把这些**标准化**：统一的模型抽象（provider 无关）、统一的 Prompt/输出结构、一堆现成的集成（向量库、文档加载器等）。它不提供智能，只提供"胶水层"。

**与直接调 API 的取舍**：

| | 直接调 API | LangChain |
|---|---|---|
| 学习成本 | 低 | 中（要懂它的抽象） |
| 换模型成本 | 高（改代码） | 低（改一个字符串） |
| 灵活性 | 完全可控 | 复杂逻辑会被框架牵着走 |
| 适合场景 | 单次调用、简单脚本 | RAG、Agent、多模型切换 |

一句话：**如果你的应用只有一个模型一次调用，别用 LangChain；一旦要做 RAG 或 Agent，它省的时间开始超过学习成本。**

## 二、模块全景（1.0 版）

1.0 做了大瘦身，核心包只剩这几块：

- **`langchain-core`**：所有抽象的地基。消息类型（HumanMessage/AIMessage）、PromptTemplate、OutputParser、Runnable（LCEL 的基础）、Retriever/VectorStore 接口。
- **`langchain`**：面向 Agent 的高层入口，核心是 `create_agent`（基于 LangGraph 运行时）。
- **`langchain-classic`**：旧版的 LLMChain、ConversationChain、旧 retrievers 等都搬到这里，只有老项目迁移才需要。
- **集成包**：`langchain-openai`、`langchain-anthropic`、`langchain-chroma` 等各自独立安装。

概念上可以按四个功能域理解（对应旧版教材里的经典划分）：

1. **Model I/O**：和模型打交道——Prompt 模板 → 调用 → 解析输出；
2. **Retrieval**：把外部知识喂给模型——加载 → 切分 → embedding → 存向量库 → 检索；
3. **Memory**：跨轮次记住对话历史（1.0 里这部分主要由 LangGraph 的 checkpointer 承担）;
4. **Agents**：让模型决定"下一步调什么工具"（1.0 的 `create_agent`）。

## 三、核心概念

### 3.1 模型统一入口：init_chat_model

```python
from langchain.chat_models import init_chat_model

# 换模型 = 换一个 "provider:model" 字符串，代码其余部分不变
llm = init_chat_model("openai:gpt-4o-mini")
# llm = init_chat_model("anthropic:claude-sonnet-4-5")
# llm = init_chat_model("ollama:qwen2.5")
```

### 3.2 PromptTemplate：把 Prompt 变成带变量的模板

```python
from langchain_core.prompts import ChatPromptTemplate

prompt = ChatPromptTemplate.from_messages([
    ("system", "你是一个{domain}领域的翻译助手。"),
    ("human", "把下面的句子翻译成{lang}：{text}"),
])

filled = prompt.invoke({"domain": "技术", "lang": "英文", "text": "向量数据库"})
# filled.messages[0].content == "你是一个技术领域的翻译助手。"
```

### 3.3 OutputParser / 结构化输出

1.0 首推的写法是 `.with_structured_output()`——直接给一个 Pydantic 类，框架搞定解析：

```python
from pydantic import BaseModel

class BookReview(BaseModel):
    title: str
    score: int      # 1-10
    summary: str

structured_llm = llm.with_structured_output(BookReview)
result = structured_llm.invoke("帮我评价一下《三体》")
print(result.score)  # 已经是对象，不用自己 parse JSON
```

传统的 `StrOutputParser`、`JsonOutputParser` 仍在 `langchain_core.output_parsers`，但多数场景用不上它们了。

### 3.4 LCEL：用 `|` 把组件串成管道

LCEL（LangChain Expression Language）是贯穿 LangChain 的核心思想：每个组件都是一个 `Runnable`，用 `|` 连接，上游输出自动变成下游输入：

```python
chain = prompt | llm | output_parser
result = chain.invoke({"domain": "技术", "lang": "英文", "text": "..."})
```

等价于 `output_parser(llm(prompt(inputs)))`，但获得额外能力：`.stream()` 流式、`.batch()` 批量、自动异步（`.ainvoke`）、以及 LangSmith 全链路追踪。

除了 `|`，常用的组合子还有两个：

```python
from langchain_core.runnables import RunnableParallel, RunnablePassthrough

# 并行执行多个分支
branch = RunnableParallel(context=retriever, question=RunnablePassthrough())
```

## 四、最小可运行示例：RAG 链路

RAG = 检索增强生成，是 LangChain 最典型的使用场景。下面是一个能跑通的最小版（需要 `pip install langchain langchain-openai`）：

```python
from langchain.chat_models import init_chat_model
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_openai import OpenAIEmbeddings

# 1. 知识入库：切分 + embedding + 存储
docs = ["Milvus 是开源向量数据库。", "LangGraph 用于编排 Agent 工作流。"]
vectorstore = InMemoryVectorStore.from_texts(docs, embedding=OpenAIEmbeddings())
retriever = vectorstore.as_retriever(search_kwargs={"k": 1})

# 2. 组装 RAG 链
llm = init_chat_model("openai:gpt-4o-mini")
prompt = ChatPromptTemplate.from_messages([
    ("system", "仅根据以下资料回答问题，资料没有就说不确定：\n{context}"),
    ("human", "{question}"),
])

def format_docs(docs):
    return "\n".join(d.page_content for d in docs)

rag_chain = (
    {
        "context": retriever | format_docs,   # 检索并拼成字符串
        "question": lambda x: x["question"],  # 原样透传
    }
    | prompt
    | llm
)

# 3. 提问
answer = rag_chain.invoke({"question": "Milvus 是什么？"})
print(answer.content)
```

注意 `retriever | format_docs` 这种嵌套：管道里的每一环都可以是另一个小管道。

## 五、常用模式速查

```python
# 流式输出
for chunk in rag_chain.stream({"question": "..."}):
    print(chunk.content, end="", flush=True)

# 批量并发
results = rag_chain.batch([{"question": q1}, {"question": q2}])

# 绑定工具给模型（Agent 的底层动作）
from langchain_core.tools import tool

@tool
def get_weather(city: str) -> str:
    """查询指定城市的天气"""
    return f"{city} 晴，25 度"

llm_with_tools = llm.bind_tools([get_weather])

# 1.0 的标准 Agent 写法（替代旧版 AgentExecutor / create_react_agent）
from langchain.agents import create_agent

agent = create_agent(
    model="openai:gpt-4o-mini",
    tools=[get_weather],
    system_prompt="你是天气助手。",
)
result = agent.invoke({"messages": [{"role": "user", "content": "北京天气如何？"}]})
```

人工审核、历史摘要等横切需求，1.0 用 **middleware** 挂进 `create_agent`，不再需要自己包裹。

## 六、新手常踩的坑

1. **版本割裂是第一大坑**。网上教程一半是 0.x 的：`from langchain.chains import LLMChain`、`AgentExecutor`、`create_react_agent` 在 1.0 里要么进了 `langchain-classic`，要么已废弃。看到 `LLMChain`/`ConversationChain` 直接判定为过时教程。
2. **包名找错**。`PromptTemplate` 在 `langchain_core.prompts`，不在 `langchain.prompts`；集成都拆成独立包（用 Chroma 要装 `langchain-chroma`，不是装个 langchain 就全有）。
3. **过度抽象**。为一次简单的 API 调用套上模板、链、parser，代码反而更难读。两层以上的固定流程，直接写 Python 函数更清晰。
4. **什么时候不该用 LangChain**：
   - 逻辑完全固定、单模型单调用——直接调 SDK；
   - 需要精细控制每一步的复杂 Agent 流程——直接上 LangGraph（更低层但更可控）；
   - 团队没人维护框架知识——LangChain 抽象层一旦升级，维护成本不低。
5. **把 Memory 想得太魔法**。Memory 本质就是"把历史消息塞回 prompt"，1.0 里靠 LangGraph 的 checkpointer + `thread_id` 实现，没有自动的长期记忆，跨会话记忆要自己设计存储。
6. **忘了 `.invoke()` 与 `.run()` 的区别**。旧版 `.run()` 返回字符串，新版统一用 `.invoke()` 返回消息对象，取 `.content` 才是文本。

## 延伸阅读

- 官方文档（1.0 后全新站点）：https://docs.langchain.com
- 迁移指南：搜 "LangChain v1 migration guide"
- 下一步：学完本篇后，多步骤/带状态的流程直接看《LangGraph 基础》
