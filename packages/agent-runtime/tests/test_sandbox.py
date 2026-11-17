"""沙箱执行器 + 沙箱 Capability 测试。

本机无 Docker，测试用 subprocess 后端（开发降级模式）。
Docker 后端逻辑与 subprocess 同构，生产环境自动选择 Docker。
"""

from __future__ import annotations

import pytest

from agent_runtime.capabilities.registry import CapabilityKind, CapabilityRegistry
from agent_runtime.capabilities.sandbox import as_sandbox_capability
from agent_runtime.sandbox import SandboxExecutor, SandboxResult

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


# ---------- as_sandbox_capability ----------


@pytest.mark.asyncio
async def test_sandbox_capability_registered_correctly():
    capability = as_sandbox_capability(executor=SandboxExecutor(backend="subprocess"))
    assert capability.name == "code_execution"
    assert capability.kind == CapabilityKind.FUNCTION
    assert capability.input_schema is not None
    assert "code" in capability.input_schema["required"]
    assert "code_execution" in capability.permissions


@pytest.mark.asyncio
async def test_sandbox_capability_execute_success():
    capability = as_sandbox_capability(executor=SandboxExecutor(backend="subprocess"))
    result = await capability.executor(code="print(3 + 4)")
    assert result["stdout"].strip() == "7"
    assert result["exit_code"] == 0
    assert result["backend"] == "subprocess"


@pytest.mark.asyncio
async def test_sandbox_capability_execute_failure_raises():
    capability = as_sandbox_capability(executor=SandboxExecutor(backend="subprocess"))
    with pytest.raises(RuntimeError, match="沙箱执行失败"):
        await capability.executor(code="raise RuntimeError('boom')")


@pytest.mark.asyncio
async def test_sandbox_capability_via_registry():
    registry = CapabilityRegistry()
    capability = as_sandbox_capability(executor=SandboxExecutor(backend="subprocess"))
    registry.register(capability)
    result = await registry.execute("code_execution", code="print(100)")
    assert "100" in result["stdout"]


@pytest.mark.asyncio
async def test_sandbox_capability_custom_timeout():
    capability = as_sandbox_capability(executor=SandboxExecutor(backend="subprocess"), timeout=5)
    result = await capability.executor(code="print('fast')")
    assert result["stdout"].strip() == "fast"
