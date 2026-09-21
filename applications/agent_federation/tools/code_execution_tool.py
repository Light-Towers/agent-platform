"""沙箱代码执行工具（langchain @tool 格式）。

供 AgenticPlanner（deepagents）经工具调用在隔离沙箱中执行 Python 代码。
后端：Docker 优先（生产），subprocess 降级（开发）。
"""

from __future__ import annotations

import logging

try:
    from typing import Annotated
except ImportError:
    from typing_extensions import Annotated

from agent_runtime.sandbox import SandboxExecutor
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_sandbox = SandboxExecutor()


@tool
async def execute_python_code(
    code: Annotated[str, "要执行的 Python 代码字符串"],
    timeout: Annotated[int, "超时秒数（默认 30）"] = 30,
) -> str:
    """在隔离沙箱中执行 Python 代码，返回 stdout。

    安全措施：Docker 容器隔离（--network=none --read-only --user=nobody），
    Docker 不可用时降级 subprocess（仅开发环境）。
    """
    result = await _sandbox.execute(code, timeout=timeout)
    if not result.success:
        return f"执行失败 (exit={result.exit_code}): {result.stderr}"
    output = result.stdout
    if result.stderr:
        output += f"\n[stderr]\n{result.stderr}"
    return output or "(无输出)"
