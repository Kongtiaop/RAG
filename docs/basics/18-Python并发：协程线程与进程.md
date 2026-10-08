# Python 并发：协程、线程与进程

> 类型: 通用基础知识（与项目无关）

## 一、是什么与解决什么问题

并发要解决的问题是：**当程序有多件事要做时，怎么让整体更快、更高效地完成**。Python 提供三条路线，它们的本质区别在于"谁在调度、能否利用多核"：

- **asyncio（协程）**：单线程内的事件循环并发。由程序自己调度，切换点由 `await` 显式标出。适合 I/O 密集。
- **threading（线程）**：操作系统调度的真线程，但在 CPython 中受 GIL（全局解释器锁）限制，同一时刻只有一个线程执行 Python 字节码。
- **multiprocessing（进程）**：每个进程有独立的解释器和 GIL，可以真正并行用满多核，代价是内存隔离和序列化开销。

一句话记忆：**协程是"一个厨师轮流看几口锅"，线程是"几个厨师共用一个灶台（灶台一次只让一人用）"，进程是"几个厨师各有各的厨房"。**

## 二、核心概念

### 2.1 I/O 密集 vs CPU 密集

| 类型 | 特征 | 例子 |
|---|---|---|
| I/O 密集 | 时间花在等待网络/磁盘/数据库返回 | 爬虫、API 调用、批量下载 |
| CPU 密集 | 时间花在计算上 | 数值计算、图像处理、解析大文件 |

### 2.2 GIL 的真实影响

- GIL 保证同一时刻**只有一个线程执行 Python 字节码**，因此多线程无法加速纯 CPU 计算。
- 但线程在执行 I/O（网络、文件、`time.sleep`）时会**释放 GIL**，所以多线程对 I/O 密集任务依然有效。
- 调用 numpy、hashlib 等大型 C 扩展时，C 层计算常常会释放 GIL，此时多线程也可能有并行收益。
- 现状：Python 3.13 开始提供 free-threading（无 GIL）构建作为实验特性，未来可能改变这一格局，但当前主流发行版仍默认带 GIL，写代码时仍按"多线程不并行执行字节码"来假设。

### 2.3 决策表：怎么选

| 场景 | 推荐 | 原因 |
|---|---|---|
| 大量网络/磁盘等待，任务数成百上千 | asyncio | 单线程即可轻松挂起上万协程，切换开销极小 |
| 少量 I/O 任务（几十个以内），或依赖库是阻塞式 | threading | 简单直接，不用全链路异步改造 |
| 纯 CPU 计算 | multiprocessing / 进程池 | 唯一能真正用上多核的方式 |
| 混合型（既有 CPU 又有 I/O） | 组合：进程池跑 CPU，协程/线程跑 I/O | 各取所长 |

补充原则：

- 用 asyncio 的前提是**整条调用链都是异步的**（异步 HTTP 客户端、异步 DB 驱动）；只要中间塞进一个阻塞函数，整个事件循环都会被卡住。
- 任务量少（比如就 3 个请求）时，引入 asyncio 的复杂度不划算，开几个线程即可。
- 进程数一般设为 `os.cpu_count()` 左右，多了反而因上下文切换和内存复制变慢。

## 三、最小示例

### 3.1 asyncio：并发抓取多个 URL

```python
import asyncio
import aiohttp  # pip install aiohttp

async def fetch(session, url):
    async with session.get(url) as resp:
        return url, resp.status

async def main():
    urls = [f"https://httpbin.org/delay/1" for _ in range(10)]
    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(*(fetch(session, u) for u in urls))
    for url, status in results:
        print(url, status)

asyncio.run(main())
# 10 个各耗时 1s 的请求，总耗时约 1s 而不是 10s
```

### 3.2 threading：并发执行阻塞式任务

```python
from concurrent.futures import ThreadPoolExecutor
import requests  # 同步库

urls = ["https://httpbin.org/delay/1"] * 10

def fetch(url):
    return url, requests.get(url).status_code

with ThreadPoolExecutor(max_workers=10) as pool:
    for url, status in pool.map(fetch, urls):
        print(url, status)
```

### 3.3 multiprocessing：CPU 密集真并行

```python
from concurrent.futures import ProcessPoolExecutor
import time

def heavy(n: int) -> int:
    total = 0
    for i in range(n):
        total += i * i
    return total

if __name__ == "__main__":
    start = time.perf_counter()
    with ProcessPoolExecutor() as pool:
        results = list(pool.map(heavy, [10_000_000] * 8))
    print(f"耗时 {time.perf_counter() - start:.2f}s")
    # 8 个 CPU 任务在多核机器上接近 8 倍加速（对比单线程）
```

注意 `if __name__ == "__main__":` 保护——Windows 上进程池用 spawn 方式启动，子进程会重新 import 主模块，没有这个保护会无限递归创建进程。

## 四、并发原语速查

| 需求 | asyncio | threading/multiprocessing |
|---|---|---|
| 并发跑一批任务并收集结果 | `asyncio.gather` | `concurrent.futures`（Executor.map/submit） |
| 限制同时进行的数量 | `asyncio.Semaphore` | 线程池/进程池的 `max_workers` |
| 保护共享状态 | 通常不需要（单线程）；跨 await 的读改写仍需 `asyncio.Lock` | `threading.Lock` / `multiprocessing.Lock` |
| 任务间传递数据 | `asyncio.Queue` | `queue.Queue` / `multiprocessing.Queue` |
| 结构化并发、自动取消子任务 | `asyncio.TaskGroup`（3.11+） | Executor 上下文管理器 |

```python
# TaskGroup 示例（推荐替代裸 gather）：任一任务抛异常时，其余任务被自动取消
async def main():
    async with asyncio.TaskGroup() as tg:
        t1 = tg.create_task(fetch_one())
        t2 = tg.create_task(fetch_two())
    # t1.result() / t2.result() 在此可用
```

信号量限流示例：

```python
sem = asyncio.Semaphore(5)  # 最多同时 5 个

async def bounded_fetch(session, url):
    async with sem:
        return await fetch(session, url)
```

## 五、实践清单

- [ ] 先判断任务是 I/O 密集还是 CPU 密集，再选方案，不要凭习惯。
- [ ] asyncio 项目里，HTTP/DB/文件操作全部使用异步库（aiohttp、httpx.AsyncClient、asyncpg、aiofiles 等）。
- [ ] 确实要在协程里调阻塞函数时，用 `await asyncio.to_thread(blocking_fn)` 扔到线程池，别直接调。
- [ ] 限制并发量（Semaphore 或连接池上限），避免一次性打爆对端或自己内存。
- [ ] 进程池入口加 `if __name__ == "__main__":`；传给子进程的参数和返回值必须是可 pickle 的。
- [ ] 多线程共享的可变状态用 Lock 保护，或者干脆改成通过 Queue 传递消息（避免共享）。
- [ ] 给并发任务设超时：`asyncio.wait_for(coro, timeout=10)` 或 Executor 的超时策略。
- [ ] 需要优雅退出时用 TaskGroup / try-finally 确保子任务被取消或清理。

## 六、新手常踩的坑

1. **协程里调用阻塞函数**：在 async 函数里用了 `requests.get`、`time.sleep`、同步 DB 驱动，事件循环被卡死，所有"并发"退化成串行。排查方法：并发 10 个任务总耗时 ≈ 单任务耗时 × 10，基本就是有阻塞点。
2. **忘记 await**：`fetch()` 只创建了协程对象但没有执行，程序静默结束（或报 "coroutine was never awaited"）。创建协程对象不会运行它，必须 `await` 或交给 TaskGroup/gather。
3. **共享状态竞争**：
   - 线程：`counter += 1` 不是原子操作，多线程下会丢更新，要用 Lock。
   - asyncio：虽然单线程，但 `await` 是切换点，"读→await→写"的跨 await 读改写同样会竞争，读改写之间不要夹 await，或用 Lock。
4. **进程池序列化开销**：传给子进程的参数经过 pickle 复制，传一个大对象（如几百 MB 的数组）再拿回结果，序列化时间可能超过计算本身。大数据场景考虑共享内存（`multiprocessing.shared_memory`）或干脆用 numpy 这类本身并行/释放 GIL 的库。
5. **在异步代码里用 `multiprocessing`**：进程池是阻塞 API，会卡住事件循环。需要时用 `loop.run_in_executor(None, pool_fn, ...)` 包装。
6. **无限制并发**：`gather` 一万个下载任务 = 一万个连接同时打开。并发不是越大越快，配 Semaphore。
7. **认为加线程一定加速**：CPU 密集任务开多线程不仅不加速，还可能因 GIL 争抢更慢。先测再优化。

## 小结

- I/O 密集 → asyncio（全链路异步）或线程池（阻塞库、任务少）。
- CPU 密集 → 进程池，注意序列化成本和 main 保护。
- 混合任务 → 进程跑 CPU + 协程/线程跑 I/O。
- 所有并发都应有并发上限和超时，"能跑"和"跑得对"之间隔着锁、队列和测试。
