"""沙箱代码执行 Skill：把 SandboxExecutor 包装为可注册的 Skill。

注册后，Planner / Agent 可经 ``delegate("code_execution", code="...")``
在隔离沙箱中执行代码——Docker 容器（生产）或 subprocess（开发降级）。

架构契约：代码执行是高风险操作，必须经沙箱隔离，不得在宿主机直接执行。
"""

from __future__ import annotations

from typing import Any

from agent_runtime.sandbox import SandboxExecutor
from agent_runtime.skills.registry import ExecutionBoundary, Skill, SkillKind


def as_sandbox_skill(
    executor: SandboxExecutor | None = None,
    *,
    name: str = "code_execution",
    timeout: int = 30,
) -> Skill:
    """把沙箱执行器包装为 FUNCTION 型 Skill。

    :param executor: 沙箱执行器（缺省自动创建，Docker 优先 subprocess 降级）。
    :param name: Skill 名称（默认 "code_execution"）。
    :param timeout: 默认超时秒数。
    :return: 可注册到 SkillRegistry 的 Skill。

    Skill 入参：
    - ``code`` (str, 必填)：要执行的 Python 代码。
    - ``language`` (str, 默认 "python")：代码语言。
    - ``timeout`` (int, 默认 30)：超时秒数。
    """
    sandbox = executor or SandboxExecutor()

    async def execute(**kwargs: Any) -> Any:
        code = kwargs.get("code", "")
        language = kwargs.get("language") or "python"
        t = kwargs.get("timeout") or timeout
        result = await sandbox.execute(code, language=language, timeout=t)
        if not result.success:
            raise RuntimeError(
                f"沙箱执行失败 (exit={result.exit_code}, backend={result.backend}): {result.stderr}"
            )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "backend": result.backend,
        }

    return Skill(
        name=name,
        description="在隔离沙箱中执行 Python 代码（Docker 容器或 subprocess 隔离）",
        kind=SkillKind.FUNCTION,
        executor=execute,
        execution_boundary=ExecutionBoundary.SANDBOX,
        input_schema={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "要执行的 Python 代码"},
                "language": {"type": "string", "description": "代码语言（默认 python）"},
                "timeout": {
                    "type": "integer",
                    "description": "超时秒数（默认 30）",
                },
            },
            "required": ["code"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "stdout": {"type": "string"},
                "stderr": {"type": "string"},
                "exit_code": {"type": "integer"},
                "duration_ms": {"type": "integer"},
                "backend": {"type": "string"},
            },
        },
        metadata={"source": "sandbox", "backend": sandbox.backend},
        permissions=frozenset({"code_execution"}),
    )


__all__ = ["as_sandbox_skill"]
