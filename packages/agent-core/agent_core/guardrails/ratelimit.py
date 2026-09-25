# -*- coding: utf-8 -*-
"""
速率限制器（框架无关内核，源自 zhiku M5）。

- ``SlidingWindowRateLimiter``：入站**拒绝式**滑动窗口限流（进程内 dict + 线程锁）。
- ``apply_api_rate_limit``：出站**阻塞式等待**滑动窗口（保护第三方 API 不被打爆）。

框架无关：仅依赖 stdlib + 自带 ``agent_core.logging``；不 import 任何宿主应用。
"""

import math
import threading
import time
from collections import deque
from typing import Deque, Dict, Optional, Tuple

from agent_core.logging import get_logger

logger = get_logger(__name__)


class SlidingWindowRateLimiter:
    """按 key 的滑动窗口限流器（线程安全）。"""

    def __init__(self, max_requests: int, window_seconds: int = 60, sweep_threshold: int = 10000) -> None:
        if max_requests < 1:
            raise ValueError("max_requests 必须 >= 1")
        if window_seconds < 1:
            raise ValueError("window_seconds 必须 >= 1")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._sweep_threshold = max(1, sweep_threshold)
        self._buckets: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: Optional[float] = None) -> Tuple[bool, int]:
        """
        判断 key 是否允许通过。

        :param key: 限流桶标识（如 key:<sha256> / ip:<host>）
        :param now: 当前时间（秒，测试可注入固定时钟）
        :return: (allowed, retry_after_seconds)；
                 allowed=False 时 retry_after 为最早请求滑出窗口还需秒数（>=1，供 Retry-After 响应头）。
        """
        current = now if now is not None else time.time()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                self._buckets[key] = deque([current])
            else:
                # 清理窗口外的过期时间戳（滑动窗口核心）
                while bucket and current - bucket[0] >= self.window_seconds:
                    bucket.popleft()

                if not bucket:
                    bucket.append(current)
                elif len(bucket) >= self.max_requests:
                    retry_after = max(1, math.ceil(bucket[0] + self.window_seconds - current))
                    return False, retry_after
                else:
                    bucket.append(current)

            # 轻量内存治理：仅在桶数超阈值时扫描清理已完全空闲的桶。
            self._maybe_sweep(current)
            return True, 0

    def reset(self) -> None:
        """清空所有桶（测试 / 运维用）。"""
        with self._lock:
            self._buckets.clear()

    def bucket_size(self) -> int:
        """当前活跃桶数量（测试用）。"""
        with self._lock:
            return len(self._buckets)

    def _maybe_sweep(self, now: float) -> None:
        """
        轻量内存治理：桶数超阈值时清理**已完全空闲**的桶，防止 key 无限增长。

        清理条件：该桶最近一次请求已滑出窗口（``now - v[-1] >= window_seconds``）。
        必须在持有 ``self._lock`` 时调用；v 可能为空 deque，取 ``v[-1]`` 前需判空。
        """
        if len(self._buckets) <= self._sweep_threshold:
            return
        idle_keys = [k for k, v in self._buckets.items() if v and now - v[-1] >= self.window_seconds]
        for key in idle_keys:
            del self._buckets[key]


def apply_api_rate_limit(request_times: Deque[float], max_requests: int, window_seconds: int = 60) -> None:
    """
    通用滑动窗口 API 速率限制器（抽离为公共工具）。
    核心逻辑：维护请求时间戳双端队列，窗口内请求数超上限则自动等待，防止触发第三方 API 限流。

    :param request_times: 存储请求时间戳的双端队列，需外部初始化（全局/单例），跨调用复用
    :param max_requests: 速率限制窗口内的最大允许请求次数
    :param window_seconds: 速率限制滑动窗口时长，默认 60 秒（1 分钟）
    :return: None，超出限制时会阻塞等待
    """
    current_time = time.time()

    # 1. 清理滑动窗口外的过期请求时间戳，保证队列仅存窗口内的请求
    while request_times and current_time - request_times[0] >= window_seconds:
        request_times.popleft()

    # 2. 窗口内请求数达上限，计算并阻塞等待剩余时间
    if len(request_times) >= max_requests:
        sleep_duration = window_seconds - (current_time - request_times[0])
        if sleep_duration > 0:
            logger.debug(
                "触发 API 速率限制，窗口 %s 秒内最多 %s 次，需等待：%.2f 秒",
                window_seconds,
                max_requests,
                sleep_duration,
            )
            time.sleep(sleep_duration)
            current_time = time.time()
            while request_times and current_time - request_times[0] >= window_seconds:
                request_times.popleft()

    # 3. 记录当前请求时间戳，加入滑动窗口队列
    request_times.append(current_time)
    logger.debug("API 请求时间戳已记录，当前 %s 秒窗口内请求数：%s", window_seconds, len(request_times))


__all__ = ["SlidingWindowRateLimiter", "apply_api_rate_limit"]
