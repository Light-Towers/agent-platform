# -*- coding: utf-8 -*-
"""
agent_core 顶层包。

框架无关内核：tracing / metrics / guardrails / llm / memory / tools。
所有模块仅依赖 stdlib + 本包自带的 :mod:`agent_core.logging`，
绝不 import ``app.core.config`` / ``langgraph`` 等宿主应用依赖；
重型/可选第三方依赖（OTel / langchain / pymongo / starlette / openai-agents）
全部通过 extra + 懒导入降级，使纯模块在仅装 stdlib 的 venv 即可 import。
"""

__all__ = ["__version__", "get_logger"]

__version__ = "0.1.0"


def get_logger(name: str):
    """返回 stdlib logger（便捷再导出，等价于 :func:`agent_core.logging.get_logger`）。"""
    from agent_core.logging import get_logger as _get_logger

    return _get_logger(name)
