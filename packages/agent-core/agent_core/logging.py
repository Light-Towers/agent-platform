# -*- coding: utf-8 -*-
"""
自包含日志封装（基于 stdlib :mod:`logging`，不依赖 loguru / 宿主应用 logger）。

设计原则：
- 替代 zhiku 的 ``app.core.logger``，使 agent_core 与宿主应用日志实现解耦，
  内核框架无关。
- 首次调用 :func:`get_logger` 时惰性配置根 logger（仅一次），避免 import 期副作用。
- 默认输出到 stderr，格式含时间 / 级别 / logger 名 / 消息，与多数服务日志兼容。
- 所有 core 模块统一 ``from agent_core.logging import get_logger`` 后 ``logger = get_logger(__name__)``。
"""

import logging
import sys
import threading

_CONFIGURED: bool = False
_CONFIG_LOCK = threading.Lock()

_DEFAULT_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _ensure_configured() -> None:
    """进程内仅配置一次根 handler（线程安全）；幂等。"""
    global _CONFIGURED
    if _CONFIGURED:
        return
    with _CONFIG_LOCK:
        if _CONFIGURED:
            return
        root = logging.getLogger("agent_core")
        if not root.handlers:
            handler = logging.StreamHandler(sys.stderr)
            handler.setFormatter(logging.Formatter(_DEFAULT_FORMAT, _DEFAULT_DATEFMT))
            root.addHandler(handler)
        # 默认 INFO；可被宿主应用通过标准 logging 接口覆盖。
        if root.level == logging.NOTSET:
            root.setLevel(logging.INFO)
        _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """返回以 ``agent_core`` 为前缀的 stdlib logger。

    参数：
        name: 通常为 ``__name__``；自动加 ``agent_core.`` 前缀以保证层级归属。

    返回：
        :class:`logging.Logger`。
    """
    _ensure_configured()
    if not name.startswith("agent_core"):
        name = f"agent_core.{name}" if name else "agent_core"
    return logging.getLogger(name)


def set_level(level: int | str) -> None:
    """设置 agent_core 根 logger 级别（覆盖默认 INFO）。"""
    _ensure_configured()
    logging.getLogger("agent_core").setLevel(level)
