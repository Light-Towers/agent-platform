"""沙箱代码执行工具（langchain @tool 格式）。

供 AgenticPlanner（deepagents）经工具调用在隔离沙箱中执行 Python 代码。
后端：Docker 优先（生产），subprocess 降级（开发）。
"""

from __future__ import annotations

import logging
import os

try:
    from typing import Annotated
except ImportError:
    from typing_extensions import Annotated

from agent_runtime.sandbox import SandboxExecutor
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# LLM 传入 timeout 的服务端钳制上限（T1.2b）：防单次调用长时间占用执行资源
_MAX_TIMEOUT_S = 120

_sandbox: SandboxExecutor | None = None


def _get_sandbox() -> SandboxExecutor:
    """懒初始化沙箱执行器（T1.2a/T1.2b）：避免 import 期固化后端选择。

    SANDBOX_ALLOW_SUBPROCESS 未开启（默认）时强制 docker-only：
    Docker 不可用则执行直接失败（SandboxResult.success=False），不静默降级为
    宿主任意代码执行。asyncio 单线程事件循环下无需加锁；
    若未来引入多线程调用，需补 threading.Lock。
    """
    global _sandbox
    if _sandbox is None:
        allow_subprocess = os.getenv("SANDBOX_ALLOW_SUBPROCESS", "false").lower() == "true"
        _sandbox = SandboxExecutor(backend="auto" if allow_subprocess else "docker")
    return _sandbox


@tool
async def execute_python_code(
    code: Annotated[str, "要执行的 Python 代码字符串"],
    timeout: Annotated[int, "超时秒数（默认 30，服务端钳制上限 120）"] = 30,
) -> str:
    """在隔离沙箱中执行 Python 代码，返回 stdout。

    安全措施：Docker 容器隔离（--network=none --read-only --user=nobody）；
    subprocess 降级仅限 SANDBOX_ALLOW_SUBPROCESS=true（开发环境显式允许）。
    timeout 由调用方传入，服务端钳制到 [1, 120]s（T1.2b）。
    """
    effective_timeout = min(max(int(timeout), 1), _MAX_TIMEOUT_S)
    result = await _get_sandbox().execute(code, timeout=effective_timeout)
    if not result.success:
        return f"执行失败 (exit={result.exit_code}): {result.stderr}"
    output = result.stdout
    if result.stderr:
        output += f"\n[stderr]\n{result.stderr}"
    return output or "(无输出)"
