> 类型: 通用基础知识（与项目无关）

# LangGraph 基础

> 版本说明：LangGraph 1.0（2025 年 10 月 GA）是独立包 `pip install langgraph`，与 LangChain 1.0 同期发布。核心 API（StateGraph/checkpointer/interrupt）在 0.2x → 1.0 保持兼容，放心食用。

## 一、为什么从 Chain 走到 Graph

LCEL 的 `prompt | llm | parser` 是**单向流水线**：数据从左到右流一遍就结束。但真实的 Agent 应用长这样：

- 需要**循环**：模型调工具 → 看结果 → 决定再调一次还是结束；
- 需要**分支**：判断情感是正面走 A 路线、负面走 B 路线；
- 需要**状态**：多轮执行中累积的信息（对话历史、中间结果）要共享；
- 需要**中断恢复**：流程跑到一半等人审批，过几小时接着跑。

这些用"链"表达会非常痛苦——你等于在 Python 里手写状态机。LangGraph 的思路是**直接把应用建模为图**：

- **Node（节点）**：一个函数，读 State、干活、返回对 State 的更新；
- **Edge（边）**：定义节点之间的流转；条件边可以动态决定下一步去哪；
- **State（状态）**：所有节点共享的一个数据结构，图的"内存"。

底层执行模型借鉴 Google 的 Pregel：按 super-step 离步执行，每步结束后统一合并状态更新，天然支持并行分支。

## 二、核心概念：StateGraph

### 2.1 State 用 TypedDict + reducer 定义

```python
from typing import Annotated, TypedDict
from langgraph.graph.message import add_messages

class State(TypedDict):
    # Annotated 的第二个参数是 reducer：决定新值怎么合并进旧值
    messages: Annotated[list, add_messages]  # 追加消息而不是覆盖
    docs: list[str]                          # 没有 reducer = 直接覆盖
```

**reducer 是 LangGraph 最重要又最容易被忽略的概念**：节点返回 `{"docs": [...]}` 时，有 reducer 就合并、没有就整个替换。`add_messages` 是内置的"按 ID 去重追加"。

### 2.2 节点与边

```python
from langchain.chat_models import init_chat_model
from langgraph.graph import StateGraph, START, END

llm = init_chat_model("openai:gpt-4o-mini")

def chatbot(state: State):
    # 返回的是"增量"，不是完整 State
    return {"messages": [llm.invoke(state["messages"])]}

builder = StateGraph(State)
builder.add_node("chatbot", chatbot)
builder.add_edge(START, "chatbot")
builder.add_edge("chatbot", END)

graph = builder.compile()
result = graph.invoke({"messages": [("user", "你好")]})
print(result["messages"][-1].content)
```

### 2.3 条件边：动态路由

```python
import operator
from typing import Annotated, TypedDict

class State(TypedDict):
    messages: list
    loop_count: Annotated[int, operator.add]  # 计数器

def should_continue(state: State) -> str:
    # 返回值 = 下一个节点的名字
    if state["loop_count"] >= 3:
        return END
    return "chatbot"

builder.add_conditional_edges("chatbot", should_continue,
                              ["chatbot", END])
```

1.0 还有更简洁的 **Command API**：节点直接返回 `Command(goto="next_node", update={...})`，把"更新状态"和"路由"合在一个节点里，不用再写单独的条件边函数。简单二选一用条件边，路由逻辑和节点业务强耦合时用 Command。

## 三、最小可运行示例：带工具循环的 Agent

```python
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode

@tool
def search(query: str) -> str:
    """搜索资料"""
    return "Milvus 是开源向量数据库。"

llm = init_chat_model("openai:gpt-4o-mini").bind_tools([search])

# MessagesState 是预置的 State：只有 messages 字段 + add_messages reducer
def agent(state: MessagesState):
    return {"messages": [llm.invoke(state["messages"])]}

builder = StateGraph(MessagesState)
builder.add_node("agent", agent)
builder.add_node("tools", ToolNode([search]))  # 预置的工具执行节点

builder.add_edge(START, "agent")
builder.add_conditional_edges(
    "agent",
    lambda s: "tools" if s["messages"][-1].tool_calls else END,
    ["tools", END],
)
builder.add_edge("tools", "agent")  # 工具结果回到 agent，形成循环

graph = builder.compile()
result = graph.invoke({"messages": [("user", "Milvus 是什么？")]})
```

这个"agent ↔ tools"循环就是 ReAct 模式的骨架，大量生产 Agent 都是它的变体。

## 四、Checkpointer：断点恢复与短期记忆

给 `compile()` 传一个 checkpointer，图就会在**每个 super-step 结束后自动保存 State 快照**（checkpoint）：

```python
from langgraph.checkpoint.memory import InMemorySaver

checkpointer = InMemorySaver()
graph = builder.compile(checkpointer=checkpointer)

# 必须指定 thread_id，同一 thread_id 的多次调用共享状态
config = {"configurable": {"thread_id": "conv-1"}}
graph.invoke({"messages": [("user", "我叫小明")]}, config)
graph.invoke({"messages": [("user", "我叫什么？")]}, config)  # 它记得
```

这一层带来三个能力：

1. **多轮记忆**：同 thread_id 的对话自动接续（短期记忆的实现方式）；
2. **容错恢复**：进程崩了，从最近 checkpoint 重新 invoke 即可续跑；
3. **时间旅行**：`get_state_history(config)` 拿到所有历史快照，可以回放、可以从任意一步分叉重跑，调试利器。

生产环境把 `InMemorySaver` 换成 `SqliteSaver` / `PostgresSaver`（各自的独立包），代码其余部分不变。

## 五、interrupt 与 Human-in-the-Loop

危险操作前让人把关。核心是 `interrupt()` 函数：执行到它就暂停，恢复时**它的返回值就是人工给的输入**：

```python
from langgraph.types import interrupt, Command

def approve(state: MessagesState):
    # 图在这里暂停，payload 发给前端展示
    decision = interrupt({"question": "要发送这条消息，确认吗？",
                          "content": state["messages"][-1].content})
    if decision == "yes":
        return Command(goto="send")
    return Command(goto=END)

# 恢复执行：传入人工决定
from langgraph.types import Command
graph.invoke(Command(resume="yes"), config)
```

三个必要条件：必须有 checkpointer（不然暂停后无从恢复）、必须指定 thread_id、恢复时用 `Command(resume=...)`。旧版还有编译时静态中断 `interrupt_before=["node"]`，现在动态 `interrupt()` 更灵活，是推荐写法。

## 六、多 Agent 编排模式

LangGraph 没有强制的多 Agent 框架，常见三种模式：

1. **Supervisor（主管模式）**：一个调度节点读共享 State，决定把任务交给哪个专家节点；专家干完回到 supervisor，直到它判断完成。这是最常用的入门模式。
2. **共享 State 协作**：多个 Agent 读写同一个 State 的不同字段（比如一个负责写文档、一个负责审查），靠边的拓扑约定协作顺序。
3. **Network（自由交接）**：Agent 之间通过 `Command(goto=...)` 互相移除控制权，灵活但难调试，慎用。

Supervisor 骨架：

```python
builder = StateGraph(State)
builder.add_node("supervisor", supervisor_node)  # LLM 决定下一步给谁
builder.add_node("researcher", researcher_node)
builder.add_node("writer", writer_node)
builder.add_edge("researcher", "supervisor")     # 专家干完回报主管
builder.add_edge("writer", "supervisor")
builder.add_conditional_edges("supervisor", route_to_worker,
                              ["researcher", "writer", END])
```

关键设计点：**专家之间不直接通信，全部通过共享 State 交换信息**。State 就是你手里握着的全局上下文。

## 七、新手常踩的坑

1. **State 更新覆盖 vs 合并分不清**。最大的坑：字段没写 reducer，节点 B 返回的 `{"docs": [...]}` 会把节点 A 写的整个覆盖掉。经验法则——"累积型"字段（消息、日志、收集的结果）一律加 reducer（`add_messages` / `operator.add`），"当前值型"字段才用覆盖。
2. **循环失控没有递归上限**。图的默认递归上限是 25 步，Agent 循环写得不好会直接抛 `GraphRecursionError`。给 `invoke` 传 `config={"recursion_limit": 50}` 调大，但**根治方法是在条件边里写终止条件**（如计数器、超时判断）。
3. **interrupt 忘配 checkpointer 或 thread_id**。运行到 `interrupt()` 直接报错或状态丢失。三者缺一不可：checkpointer、thread_id、`Command(resume=...)`。
4. **节点函数里直接改 state 不会生效**。必须通过返回值声明更新（`return {...}`），LangGraph 靠返回值做合并和持久化。原地修改传入的 dict 是无效的。
5. **`add_node` 传的字符串名和条件边返回的名字不一致**。条件边返回的节点名拼错不会立即报错，运行到才炸，建议用常量或枚举。
6. **InMemorySaver 拿去做"生产持久化"**。它只活在进程内存里，重启全丢。想持久化换 Sqlite/Postgres saver，一行都不用改别的代码。
7. **把 LangGraph 当 LangChain 的进阶必选项**。线性流程用 LCEL 更简单；只有真正需要循环、分支、状态、人审时才上 LangGraph，图建模本身有维护成本。

## 延伸阅读

- 官方文档：https://docs.langchain.com（oss/python/langgraph 部分）
- 下一步：结合《Milvus 基础》搭一个带持久化的 RAG Agent
