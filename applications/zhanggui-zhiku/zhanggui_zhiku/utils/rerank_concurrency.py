# -*- coding: utf-8 -*-
"""
reranker 并发闸门（M6，方案 §10.4）。

node_rerank 在进程内加载重排序模型，多请求并发推理会放大内存 / 显存占用。
M6 用 ``threading.BoundedSemaphore(max_concurrency)`` 限制同时进入模型推理的调用数
（超出闸门的调用**排队等待**而非丢弃）。

本模块为纯 stdlib 封装，便于无重型依赖的单测直接验证（见 tests/unit/test_concurrency.py）；
``node_rerank.py`` 通过 ``call_under_semaphore`` 包裹 ``compute_score`` 调用。

说明：检索图当前为同步 LangGraph invoke（节点在线程中执行），因此使用线程级信号量；
语义与方案 §10.4 的 ``asyncio.Semaphore`` 等价（限并发模型推理，防 OOM）。
"""

import threading
from typing import Any, Callable


def make_rerank_semaphore(max_concurrency: int) -> threading.BoundedSemaphore:
    """创建 reranker 并发闸门；非法值收敛到 1（至少允许单路推理）。"""
    return threading.BoundedSemaphore(max(1, int(max_concurrency)))


def call_under_semaphore(
    semaphore: threading.BoundedSemaphore,
    fn: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """在信号量闸门内执行 ``fn(*args, **kwargs)``；超出闸门的调用排队等待（不丢弃）。"""
    with semaphore:
        return fn(*args, **kwargs)
