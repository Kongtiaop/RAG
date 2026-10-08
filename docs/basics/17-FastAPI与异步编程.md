# FastAPI 与异步编程：Python Web 服务入门

> 类型: 通用基础知识（与项目无关）；基于 2026-10 公开资料整理

## 一、是什么与为什么流行

FastAPI 是基于 **Starlette（ASGI 框架）+ Pydantic（数据校验）** 的现代 Python Web
框架。它流行的三个核心原因：

1. **类型即校验**：用 Pydantic 模型声明请求/响应结构，类型错误自动返回 422，
   不用手写参数校验。
2. **OpenAPI 自动文档**：自动生成 `/docs`（Swagger UI）和 `/redoc`，接口即文档。
3. **异步原生**：基于 ASGI，天然支持 `async def` 与高并发 IO，且同步函数也能混写。

对 LLM 应用尤其友好：流式输出（SSE）、长耗时调用、并发请求外部 API 都是常态，
正好是异步模型的主场。

### 心智模型：ASGI 与事件循环

- **WSGI（同步老世界）**：一个请求占一个线程/进程，并发数 ≈ 线程数。
- **ASGI（异步新世界）**：单线程内的事件循环调度成千上万个协程，遇到 IO 等待
  （网络请求、读文件）就切去干别的活。
- 关键认知：**异步加速的是"等待"，不是"计算"**。CPU 密集任务不会因为 `async` 变快。

## 二、最小应用

```python
# pip install "fastapi[standard]"
from fastapi import FastAPI

app = FastAPI()

@app.get("/hello/{name}")
def hello(name: str):
    return {"message": f"你好, {name}"}

@app.get("/items")
async def list_items(q: str | None = None, skip: int = 0, limit: int = 10):
    return {"q": q, "skip": skip, "limit": limit}

# 启动: fastapi dev main.py（开发）或 uvicorn main:app --port 8000
# 文档: http://127.0.0.1:8000/docs
```

类型注解直接变成校验规则：`skip: int = 0` 意味着 `?skip=abc` 会自动返回 422 错误。

## 三、Pydantic 模型与请求/响应

```python
from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI()

class ItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    price: float = Field(gt=0, description="单价，必须为正")
    tags: list[str] = []

class ItemOut(ItemIn):
    id: int

@app.post("/items", response_model=ItemOut)
def create_item(item: ItemIn):
    # 走到这里时 item 一定通过了校验
    return {"id": 1, **item.model_dump()}
```

要点：

- 请求体用 Pydantic 模型声明，响应体用 `response_model` 声明——它会**过滤多余字段**
  （防止内部字段意外泄露）并做序列化。
- **Pydantic v2 与 v1 差异很大**：v2 核心用 Rust 重写（性能提升数倍），API 改名
  （`.dict()` → `.model_dump()`，`@validator` → `@field_validator`，`Field(...)`
  约束写法变化）。新项目一律用 v2，读旧代码时注意区分。

## 四、依赖注入：Depends 的价值

`Depends` 是 FastAPI 的灵魂特性：把"请求前置逻辑"声明为可复用的依赖，
框架负责解析与缓存。

```python
from fastapi import Depends, HTTPException, Query
from fastapi.security import OAuth2PasswordBearer

app = FastAPI()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    if token != "secret":
        raise HTTPException(status_code=401, detail="无效凭证")
    return {"user": "alice"}

@app.get("/me")
def read_me(user: dict = Depends(get_current_user)):
    return user

# 分页参数也是依赖：多个接口共享同一套校验
def pagination(skip: int = 0, limit: int = Query(default=20, le=100)):
    return {"skip": skip, "limit": limit}

@app.get("/orders")
def list_orders(page: dict = Depends(pagination), user=Depends(get_current_user)):
    return {"user": user, **page}
```

价值在于：

- **复用**：鉴权、数据库会话、分页逻辑写一次，到处声明。
- **可测试**：测试时用 `app.dependency_overrides[get_current_user] = fake_user`
  一行替换真实依赖。
- **依赖树自动解析**：依赖还可以依赖别的依赖，框架递归处理；
  同一请求内相同依赖默认只执行一次（缓存）。

## 五、SSE 流式响应：LLM 应用刚需

LLM 逐 token 生成，等全部生成完再返回体验极差。SSE（Server-Sent Events）是最常用的
流式方案：

```python
import asyncio
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()

async def token_stream(prompt: str):
    # 真实场景：async for chunk in llm_client.stream(prompt): ...
    for word in f"你好，这是对「{prompt}」的流式回复".split("，"):
        yield f"data: {word}\n\n"      # SSE 格式: 每条消息 data: ... 空行结尾
        await asyncio.sleep(0.2)
    yield "data: [DONE]\n\n"

@app.get("/chat")
def chat(prompt: str):
    return StreamingResponse(
        token_stream(prompt),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

注意事项：

- `media_type` 必须是 `text/event-stream`；经过 Nginx 等反代时要**关缓冲**
  （`X-Accel-Buffering: no`），否则前端会"卡住"等一次性吐出。
- 生成器函数里每一步 yield 之间都不要有长阻塞，否则流会断顿。
- 前端用原生 `EventSource` 或 `fetch` + ReadableStream 消费。

## 六、中间件与生命周期

```python
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时: 加载模型、建连接池
    app.state.db = await create_db_pool()
    yield
    # 关闭时: 释放资源
    await app.state.db.close()

app = FastAPI(lifespan=lifespan)

@app.middleware("http")
async def add_timing(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Process-Time"] = f"{time.perf_counter() - start:.3f}s"
    return response
```

- **lifespan** 管应用全局资源（模型、连接池），比旧的 `@app.on_event` 更推荐。
- **中间件**包裹每个请求，适合计时、CORS、日志、全局限流。
- 全局异常用异常处理器：`@app.exception_handler(CustomError)`，返回统一错误结构。

## 七、异步 Web 的心智模型：什么时候 async，什么时候 def

这是 FastAPI 最重要的一课。框架的行为规则：

| 你写的函数 | 框架如何运行 | 适用场景 |
|-----------|-------------|----------|
| `async def` | 在事件循环里直接跑 | 内部只做异步 IO（httpx 异步客户端、异步驱动、await 别的协程） |
| `def`（同步） | **自动扔进线程池**，不阻塞事件循环 | 内部是同步阻塞库（requests、SQLAlchemy 传统用法） |

两条铁律：

1. **`async def` 里绝不能出现长阻塞调用**（同步 requests、`time.sleep`、同步 DB
   驱动、重 CPU 计算）。事件循环是单线程的，一处阻塞全服务卡死。
2. **拿不准就用 `def`**。框架会开线程池兜底，代价小；而"伪异步"（async def 包同步
   阻塞代码）是灾难。

```python
import asyncio, time

@app.get("/bad")
async def bad():
    time.sleep(5)            # 灾难：同步 sleep 阻塞整个事件循环

@app.get("/good1")
async def good1():
    await asyncio.sleep(5)   # 异步等待，循环可以调度其他请求

@app.get("/good2")
def good2():
    time.sleep(5)            # 框架自动放线程池，不阻塞循环
```

CPU 密集任务（大文件解析、模型推理）既不适合 async 也不适合默认线程池，
用 `run_in_executor` 进程池或独立任务队列（Celery/ARQ）。

## 八、新手常踩的坑

1. **在 `async def` 里调同步阻塞库**（坑中之王）：全服务所有请求一起卡死，
   且本地单测看不出来，只有并发压测才暴露。排查方法：压测时看时延是否随并发线性恶化。
2. **以为 `async def` = 更快**：如果函数体内全是 CPU 计算，async 毫无收益还增加
   复杂度。先判断瓶颈是 IO 还是计算。
3. **Pydantic v1/v2 混淆**：网上教程一半是 v1 写法（`.dict()`、`@validator`、
   `schema()`），v2 下会报错或行为不同。看报错先确认版本：`pydantic.VERSION`。
4. **依赖注入滥用**：把普通工具函数硬包成 Depends、在依赖里做重计算但不加缓存，
   依赖树越来越深难调试。原则：**与请求生命周期相关的东西才做依赖**
   （鉴权、会话、参数），纯逻辑直接 import。
5. **`response_model` 忘写**：内部模型直接返回，敏感字段（密码哈希、内部 ID）
   泄露到响应里。响应模型要显式声明，宁可多写几行。
6. **SSE 被 Nginx 缓冲**：流式接口在测试环境正常、上线后变成"等很久一次性出结果"，
   九成是反代缓冲没关。
7. **在中间件/依赖里吞异常**：异常被 `try/except` 吃掉后全局错误统计和告警失效，
   记得 raise 或重新抛出。
8. **用 `uvicorn --reload` 上生产**：开发选项不要进生产；生产用
   `uvicorn main:app --workers N` 或 gunicorn 管理 uvicorn worker。

## 延伸阅读

- FastAPI 官方文档（中文版可用），尤其是 Concurrency and async/await 一节
- Pydantic v2 迁移指南
- Starlette 文档（了解 ASGI 底层：Application、Middleware、Responses）
