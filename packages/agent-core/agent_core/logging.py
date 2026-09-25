# -*- coding: utf-8 -*-
"""
自包含日志封装（基于 stdlib :mod:`logging`，不依赖 loguru / 宿主应用 logger）。

设计原则：
- 替代 zhiku 的 ``app.core.logger``，使 agent_core 与宿主应用日志实现解耦，
  内核框架无关。
- ``get_logger(name)``：仅获取 logger，**不做命名空间改写**（保持 ``__name__`` 原样），
  保证 Loki/ELK/Datadog 等日志管线中的 logger 身份稳定。
- ``configure_logging()``：进程内**幂等**地一次性配置 root + agent_core 子树：
  - root 挂 stderr handler，使所有未单独配置的子树（如 ``agent_runtime.*``）正常输出；
  - ``agent_core`` 子树自有 stderr handler 且 ``propagate=False``，**消除双打**
    （旧实现给 agent_core 加 handler 但未禁止传播，宿主 basicConfig 又给 root 加
    handler 时每条 agent_core 日志打印两次）；
  - 级别：显式参数 > 环境变量 ``LOG_LEVEL`` > 默认 INFO；第三方库（httpx/uvicorn 等）
    不被主动拉低到 DEBUG，避免生产噪声爆炸。
- 首次调用 ``get_logger`` 时惰性触发 ``configure_logging``（默认参数），保证日志必有出口。
- 所有 core / 宿主模块统一 ``from agent_core.logging import get_logger`` 后
  ``logger = get_logger(__name__)``。
"""

import logging
import os
import sys
import threading

_CONFIGURED: bool = False
_CONFIG_LOCK = threading.Lock()

_DEFAULT_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"


def configure_logging(
    level: int | str | None = None,
    fmt: str | None = None,
    datefmt: str | None = None,
) -> None:
    """进程内幂等配置 root + agent_core 子树（可重复调用，不增长 handler 数量）。

    参数：
        level: 日志级别；为 None 时取环境变量 ``LOG_LEVEL``（默认 INFO）。
        fmt: 日志格式；为 None 时用默认 ``_DEFAULT_FORMAT``。
        datefmt: 时间格式；为 None 时用默认 ``_DEFAULT_DATEFMT``。

    幂等保证：仅当 root / agent_core 尚无 handler 时才挂载，重复调用不重复添加，
    仅更新级别；因此多次调用 ``configure_logging()`` 后 root 与 agent_core 的
    handler 总数恒定。
    """
    global _CONFIGURED
    with _CONFIG_LOCK:
        if level is None:
            level = os.environ.get("LOG_LEVEL", "INFO").upper()
        _fmt = fmt or _DEFAULT_FORMAT
        _datefmt = datefmt or _DEFAULT_DATEFMT
        formatter = logging.Formatter(_fmt, _datefmt)

        # root：所有未单独配置的子树（agent_runtime.* 等）统一出口
        root = logging.getLogger()
        if not root.handlers:
            handler = logging.StreamHandler(sys.stderr)
            handler.setFormatter(formatter)
            root.addHandler(handler)
        root.setLevel(level)

        # agent_core 子树：自有 handler + 不向 root 传播（消除双打）
        ac = logging.getLogger("agent_core")
        if not ac.handlers:
            ac_handler = logging.StreamHandler(sys.stderr)
            ac_handler.setFormatter(formatter)
            ac.addHandler(ac_handler)
        ac.propagate = False
        ac.setLevel(level)

        _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """返回以 ``name`` 为名的 stdlib logger（保持原样，不做命名空间改写）。

    参数：
        name: 通常为 ``__name__``；直接透传给 ``logging.getLogger``，
        保证 logger 身份与模块路径一致（如 ``agent_runtime.admission``）。

    返回：
        :class:`logging.Logger`。
    """
    if not _CONFIGURED:
        configure_logging()  # 惰性幂等配置，保证日志必有出口
    return logging.getLogger(name)


def set_level(level: int | str) -> None:
    """设置 root + agent_core 级别（覆盖默认 INFO）。"""
    configure_logging(level=level)
