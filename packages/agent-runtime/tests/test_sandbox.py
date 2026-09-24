"""沙箱执行器 + 沙箱 Skill 测试。

本机无 Docker，测试用 subprocess 后端（开发降级模式）。
Docker 后端逻辑与 subprocess 同构，生产环境自动选择 Docker。
"""

from __future__ import annotations

import pytest

from agent_runtime.sandbox import SandboxExecutor, SandboxResult
from agent_runtime.skills.registry import SkillKind, SkillRegistry
from agent_runtime.skills.sandbox import as_sandbox_skill

# ---------- SandboxExecutor ----------


@pytest.mark.asyncio
async def test_sandbox_execute_simple_code():
    executor = SandboxExecutor(backend="subprocess")
    result = await executor.execute("print(1 + 1)")
    assert result.success
    assert "2" in result.stdout
    assert result.backend == "subprocess"


@pytest.mark.asyncio
async def test_sandbox_execute_returns_result():
    executor = SandboxExecutor(backend="subprocess")
    result = await executor.execute("x = 6 * 7; print(x)")
    assert result.success
    assert "42" in result.stdout


@pytest.mark.asyncio
async def test_sandbox_execute_failure():
    executor = SandboxExecutor(backend="subprocess")
    result = await executor.execute("raise ValueError('test error')")
    assert not result.success
    assert result.exit_code != 0
    assert "test error" in result.stderr


@pytest.mark.asyncio
async def test_sandbox_execute_timeout():
    executor = SandboxExecutor(backend="subprocess")
    result = await executor.execute("import time; time.sleep(100)", timeout=1)
    assert not result.success
    assert "超时" in result.stderr


@pytest.mark.asyncio
async def test_sandbox_unsupported_language():
    executor = SandboxExecutor(backend="subprocess")
    result = await executor.execute("console.log('hi')", language="javascript")
    assert not result.success
    assert "不支持的语言" in result.stderr


@pytest.mark.asyncio
async def test_sandbox_result_fields():
    executor = SandboxExecutor(backend="subprocess")
    result = await executor.execute("print('ok')")
    assert isinstance(result, SandboxResult)
    assert result.success is True
    assert result.exit_code == 0
    assert result.duration_ms >= 0
    assert result.backend == "subprocess"


# ---------- as_sandbox_skill ----------


@pytest.mark.asyncio
async def test_sandbox_skill_registered_correctly():
    skill = as_sandbox_skill(executor=SandboxExecutor(backend="subprocess"))
    assert skill.name == "code_execution"
    assert skill.kind == SkillKind.FUNCTION
    assert skill.input_schema is not None
    assert "code" in skill.input_schema["required"]
    assert "code_execution" in skill.permissions


@pytest.mark.asyncio
async def test_sandbox_skill_execute_success():
    skill = as_sandbox_skill(executor=SandboxExecutor(backend="subprocess"))
    result = await skill.executor(code="print(3 + 4)")
    assert result["stdout"].strip() == "7"
    assert result["exit_code"] == 0
    assert result["backend"] == "subprocess"


@pytest.mark.asyncio
async def test_sandbox_skill_execute_failure_raises():
    skill = as_sandbox_skill(executor=SandboxExecutor(backend="subprocess"))
    with pytest.raises(RuntimeError, match="沙箱执行失败"):
        await skill.executor(code="raise RuntimeError('boom')")


@pytest.mark.asyncio
async def test_sandbox_skill_via_registry():
    registry = SkillRegistry()
    skill = as_sandbox_skill(executor=SandboxExecutor(backend="subprocess"))
    registry.register(skill)
    result = await registry.execute("code_execution", code="print(100)")
    assert "100" in result["stdout"]


@pytest.mark.asyncio
async def test_sandbox_skill_custom_timeout():
    skill = as_sandbox_skill(executor=SandboxExecutor(backend="subprocess"), timeout=5)
    result = await skill.executor(code="print('fast')")
    assert result["stdout"].strip() == "fast"
