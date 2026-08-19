"""子服务健康探活：定期检查 3 个子服务可达性。

复用 zhiku_tools.py 已有的异步线程探活模式。
不可达时 mark_unhealthy，影响路由决策。
"""

from __future__ import annotations

import threading
import time

import httpx
from agent_core.logging import get_logger

from agent.config import get_all_subservices, is_remote_mode, mark_healthy, mark_unhealthy

logger = get_logger(__name__)

_CHECK_INTERVAL = 30.0
_TIMEOUT = 3.0


def _check_one(name: str, url: str) -> bool:
    """探活单个子服务。"""
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.get(f"{url}/health")
            return resp.status_code == 200
    except Exception:
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                resp = client.get(url)
                return resp.status_code < 500
        except Exception:
            return False


def _health_loop() -> None:
    """持续探活循环（daemon 线程）。"""
    while True:
        if not is_remote_mode():
            time.sleep(_CHECK_INTERVAL)
            continue

        for key, svc in get_all_subservices().items():
            ok = _check_one(svc.name, svc.url)
            if ok:
                mark_healthy(key)
                logger.debug("子服务 %s (%s) 健康", key, svc.url)
            else:
                mark_unhealthy(key)
                logger.warning("子服务 %s (%s) 不可达，将降级到 fallback", key, svc.url)

        time.sleep(_CHECK_INTERVAL)


_started = False


def start_health_check() -> None:
    """启动健康探活 daemon 线程（幂等）。"""
    global _started
    if _started:
        return
    _started = True
    t = threading.Thread(target=_health_loop, daemon=True, name="subservice-health")
    t.start()
    logger.info("子服务健康探活已启动（间隔 %ss）", _CHECK_INTERVAL)
