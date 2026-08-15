# -*- coding: utf-8 -*-
"""
通用 guarded 执行（框架无关内核，源自 zhiku fanout 的 guarded_call / wrap_channel_node）。

- ``guarded_invoke(tool, state, *, timeout_s, channel)``：在线程池执行 ``tool.invoke(state)``
  并施加超时；超时 / 异常 → ``{}``（空状态更新，等价该路未召回），**绝不向上抛**。
- ``wrap_tool(tool, *, enabled, timeout_s, channel)``：生成被 guard 包裹的节点函数；
  ``enabled=False`` 直接返回 ``{}``。

**去除 zhiku 耦合**：不再依赖 ``app.conf.retrieval_config``；``enabled`` / ``timeout_s``
由调用方从注册表条目或参数显式传入（设计 §3 ⑥）。

框架无关：仅 stdlib + 自带 agent_core.logging + agent_core.tracing（均懒导入降级）。
"""

import concurrent.futures
from typing import Any, Callable, Dict, Optional

from agent_core.logging import get_logger
from agent_core.tracing import start_span

logger = get_logger(__name__)

# 有界线程池：guard 在线程中执行节点；超时后线程仍可能占用，故池必须有界
_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="tool-guard")

_DEFAULT_TIMEOUT_S = 3.0


def guarded_invoke(
    tool: Any,
    state: Dict[str, Any],
    *,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
    channel: Optional[str] = None,
) -> Dict[str, Any]:
    """
    在线程池中执行工具并施加超时；超时 / 异常 → ``{}``，绝不向上抛。

    :param tool: 实现 Tool 协议的对象（有 invoke(state)）或普通可调用函数
    :param state: 上游状态
    :param timeout_s: 超时上界（秒）
    :param channel: 通道名（用于日志与 span 标识，可空）
    :return: 工具返回的 dict；超时 / 异常 / 非 dict 一律归一为 {}
    """
    invoke = getattr(tool, "invoke", None)
    if invoke is not None:
        future = _EXECUTOR.submit(invoke, state)
    else:
        future = _EXECUTOR.submit(tool, state)
    try:
        result = future.result(timeout=timeout_s)
        return result if isinstance(result, dict) else {}
    except concurrent.futures.TimeoutError:
        _mark_guard_span(channel, timeout_s, "timeout")
        logger.warning("tool invoke timeout channel=%s timeout_s=%s", channel, timeout_s)
        return {}
    except Exception as e:  # noqa: BLE001 —— 单路失败降级，绝不向上抛
        _mark_guard_span(channel, timeout_s, "error", exception=e)
        logger.exception("tool invoke failed channel=%s", channel)
        return {}


def wrap_tool(
    tool: Any,
    *,
    enabled: bool = True,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
    channel: Optional[str] = None,
) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """
    将工具包装为「超时隔离 + 失败降级」节点。

    :param tool: 实现 Tool 协议的对象
    :param enabled: 是否启用（False → 直接返回 {}，跳过该路）
    :param timeout_s: 逐路超时上界
    :param channel: 通道名（日志 / span）
    :return: 节点函数 ``(state) -> dict``
    """
    if not enabled:
        logger.info("tool %s disabled, skip", channel or getattr(tool, "name", "?"))
        return lambda state: {}
    return lambda state: guarded_invoke(tool, state, timeout_s=timeout_s, channel=channel)


def _mark_guard_span(
    channel: Optional[str], timeout_s: float, outcome: str, exception: Optional[BaseException] = None
) -> None:
    """异常路径 span 埋点：标记某路被超时截断 / 失败（正常路径由工具自身 span 覆盖）。"""
    name = f"tool.{channel}.guarded" if channel else "tool.guarded"
    with start_span(name, attrs={"channel": channel or "", "timeout_s": timeout_s, "outcome": outcome}) as span:
        if exception is not None:
            try:
                span.record_exception(exception)
            except Exception:  # pragma: no cover - 防御
                pass


__all__ = ["guarded_invoke", "wrap_tool", "_DEFAULT_TIMEOUT_S"]
