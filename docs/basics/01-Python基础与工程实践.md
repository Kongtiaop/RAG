# Python 基础与工程实践

> 类型: 通用基础知识（与项目无关）

面向有一点编程经验、但 Python 用得不够"工程化"的读者。目标不是覆盖语法全集，而是把日常开发中最容易出问题、最影响效率的几件事讲清楚。

## 1. 它是什么，什么时候用

Python 是一门动态类型、解释执行的通用语言。适合：

- 脚本、自动化、胶水代码
- 数据处理与分析
- AI / LLM 应用开发（生态最全）
- Web 后端（FastAPI、Django）

不适合：对启动速度、单核性能极致敏感的场景（如高频交易核心路径）。

## 2. 环境管理：venv 与 uv

### 2.1 venv（标准库，永远可用）

```bash
# 创建虚拟环境（Python 3.11+ 也可以 python3 -m venv .venv）
python -m venv .venv

# 激活
source .venv/bin/activate        # Linux / macOS
.venv\Scripts\activate           # Windows PowerShell: .venv\Scripts\Activate.ps1

# 安装依赖并固化
pip install requests
pip freeze > requirements.txt
```

核心原则：**一个项目一个 `.venv`，不要往系统 Python 里装包**。

### 2.2 uv（2024 年后的事实新标准）

uv 是 Rust 写的 Python 包管理器，速度快一个数量级，逐渐替代 pip + venv + pip-tools 的组合：

```bash
# 初始化一个项目（生成 pyproject.toml）
uv init myproj && cd myproj

# 加依赖（自动创建虚拟环境、更新 uv.lock）
uv add requests

# 运行脚本（自动使用项目环境）
uv run python main.py
```

选择建议：个人新项目直接用 uv；老项目维护时继续 pip 也没问题，两者都基于 `pyproject.toml` 这份标准配置。

## 3. 类型注解

Python 3.9+ / 3.10+ 的类型注解已经是工程标配。它**不影响运行时**，价值在于 IDE 补全、静态检查（mypy / pyright）和接口文档化。

```python
# 内置泛型直接写，不需要从 typing 导入 List/Dict（3.9+）
def process(items: list[str], limit: int = 10) -> dict[str, int]:
    return {name: len(name) for name in items[:limit]}

# 3.10+ 联合类型用 |
def find_user(uid: int | str) -> str | None:
    return None

# TypedDict：给"字典的结构"加上类型
from typing import TypedDict

class User(TypedDict):
    name: str
    age: int
```

心智模型：注解是**给人和工具看的契约**，运行时不校验。想运行时强校验请用 pydantic。

## 4. async/await 心智模型

一句话：**asyncio 是单线程内的协作式调度**。只有遇到 `await` 时，控制权才会交出去；CPU 密集代码不会因为加了 async 就变快。

```python
import asyncio

async def fetch(name: str, delay: float) -> str:
    await asyncio.sleep(delay)          # 模拟 IO
    return f"{name} done"

async def main():
    # 并发跑三个任务（不是并行！是 IO 等待期间互相让路）
    results = await asyncio.gather(
        fetch("a", 1),
        fetch("b", 2),
        fetch("c", 1),
    )
    print(results)  # 总耗时约 2 秒，不是 4 秒

asyncio.run(main())
```

关键判断：

- **IO 密集、并发量大**（爬虫、API 聚合、LLM 调用）→ asyncio 收益大
- **CPU 密集** → 用多进程（`multiprocessing` / `concurrent.futures.ProcessPoolExecutor`）
- 在 async 函数里调用同步阻塞函数（如 `requests.get`、`time.sleep`）会**卡死整个事件循环**，必须换成对应的异步库（`httpx.AsyncClient`、`asyncio.sleep`）或用 `asyncio.to_thread()` 丢进线程

## 5. 装饰器与生成器速览

### 5.1 装饰器

装饰器 = 接收函数、返回新函数的高阶函数。常用于日志、缓存、鉴权。

```python
import functools, time

def timed(fn):
    @functools.wraps(fn)          # 保留原函数的 __name__ 等元信息
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = fn(*args, **kwargs)
        print(f"{fn.__name__} 耗时 {time.perf_counter() - start:.3f}s")
        return result
    return wrapper

@timed
def heavy():
    time.sleep(0.5)
```

记住 `functools.wraps`，不写它调试时函数名会全变成 `wrapper`。

### 5.2 生成器

生成器用 `yield` 逐个产出值，**惰性求值、内存 O(1)**，适合流式处理大文件、大结果集。

```python
def read_large(path: str):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield line

# 只在内存里保留一行，几 GB 的文件也能处理
total = sum(1 for _ in read_large("huge.log"))
```

## 6. 项目结构约定

小到中型项目，一个足够熟悉的布局：

```
myproj/
├── pyproject.toml        # 依赖与元数据（现代标准）
├── README.md
├── src/
│   └── myproj/           # 源码包，避免"能跑是因为当前目录恰好在里面"
│       ├── __init__.py
│       ├── core.py
│       └── api.py
└── tests/
    └── test_core.py
```

要点：

- 源码放 `src/` 布局可强迫你正确安装包，避免导入歧义
- 配置用环境变量或 `.env`（`pydantic-settings` / `python-dotenv`），不要写死在代码里
- 测试用 pytest，命名 `test_*.py`，跑 `pytest` 即可

## 7. 新手常踩的坑

### 7.1 可变默认参数

默认值在函数定义时求值一次，之后所有调用共享同一个对象。

```python
def add_item(item, items=[]):      # 错！多次调用会累积
    items.append(item)
    return items

def add_item(item, items=None):    # 对
    if items is None:
        items = []
    items.append(item)
    return items
```

### 7.2 GIL 的实际影响

- CPython 的全局解释器锁（GIL）保证同一时刻只有一个线程执行 Python 字节码
- **多线程不能加速纯 Python CPU 计算**，但 IO 等待会释放 GIL，所以多线程做 IO 并发仍然有效
- Python 3.13 起提供 free-threaded（无 GIL）实验构建，但主流生态适配仍在进行，2025-2026 年写代码时按"GIL 存在"来设计
- 结论速查：IO 多 → 线程或 asyncio；CPU 多 → 多进程

### 7.3 异常吞掉

```python
try:
    do_something()
except Exception:      # 坑：静默吞掉，出了问题无从排查
    pass
```

正确姿势：至少记录日志；能精确就别用裸 `except Exception`；`finally`/`with` 负责资源释放，不要靠 except 顺手做。

```python
import logging
try:
    do_something()
except ValueError:
    logging.exception("处理失败")   # exception() 会带上堆栈
    raise                            # 常见选择：记日志后继续抛出
```

### 7.4 其他高频小坑

- `==` 比较、`is` 判同一性：判 `None` 用 `is None`
- 循环里修改正在遍历的列表/字典 → 先复制或收集后再删
- 字符串拼接用 `''.join(list)`，不要在循环里 `+=`（O(n²)）
- 深浅拷贝：`copy.copy` 是浅拷贝，嵌套结构要 `copy.deepcopy`

## 8. 一页速查

| 需求 | 用法 |
|---|---|
| 建环境 | `uv init` / `python -m venv .venv` |
| 并发 IO | `asyncio.gather` + 异步库 |
| CPU 并行 | `ProcessPoolExecutor` |
| 大文件处理 | 生成器 `yield` |
| 函数增强 | 装饰器 + `functools.wraps` |
| 配置管理 | `.env` + `pydantic-settings` |
| 静态检查 | mypy 或 pyright |

把"环境隔离、类型注解、分清 IO 与 CPU、不吞异常"这四条变成肌肉记忆，Python 项目的下限就已经很高了。
