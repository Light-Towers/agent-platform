"""as_remote_capability + as_dag_capability 单元测试：薄包装契约。"""

from __future__ import annotations

import pytest

from agent_runtime.capabilities.dag import as_dag_capability
from agent_runtime.capabilities.registry import CapabilityKind
from agent_runtime.capabilities.remote import as_remote_capability


@pytest.mark.asyncio
async def test_as_remote_capability_basic():
    async def fetch(url):
        return f"content from {url}"

    capability = as_remote_capability("fetch", "远程获取", fetch)
    assert capability.name == "fetch"
    assert capability.description == "远程获取"
    assert capability.kind == CapabilityKind.REMOTE
    result = await capability.executor(url="http://example.com")
    # 契约是「kwargs 透传 + 原样返回」，故用等值断言（比子串包含更强）。
    # 刻意不写成 ``"example.com" in result``：形似 URL 子串白名单校验，会被
    # CodeQL ``py/incomplete-url-substring-sanitization`` 判为「URL 安全校验依赖子串」
    # （见 docs/plans/plan-codeql-codescanning-remediation-2026-10-01.md Batch 5）。
    assert result == "content from http://example.com"
    # 返回值类型也钉住：薄包装不得把协程结果再包一层
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_as_remote_capability_with_schema_and_permissions():
    async def invoke(**kwargs):
        return "ok"

    schema = {"type": "object", "properties": {"q": {"type": "string"}}}
    capability = as_remote_capability(
        "svc", "服务", invoke,
        input_schema=schema,
        timeout_ms=3000,
        permissions={"read"},
    )
    assert capability.input_schema == schema
    assert capability.timeout_ms == 3000
    assert "read" in capability.permissions


@pytest.mark.asyncio
async def test_as_remote_capability_empty_permissions():
    async def invoke(**kwargs):
        return "ok"

    capability = as_remote_capability("svc", "服务", invoke)
    assert capability.permissions == frozenset()


@pytest.mark.asyncio
async def test_as_dag_capability_basic():
    async def run_pipeline(**kwargs):
        return {"summary": kwargs.get("query", "")}

    capability = as_dag_capability("pipeline", "流水线", run_pipeline)
    assert capability.name == "pipeline"
    assert capability.description == "流水线"
    assert capability.kind == CapabilityKind.WORKFLOW
    result = await capability.executor(query="test")
    assert result["summary"] == "test"


@pytest.mark.asyncio
async def test_as_dag_capability_with_schema_and_permissions():
    async def run_dag(**kwargs):
        return "done"

    schema = {"type": "object", "properties": {"input": {"type": "string"}}}
    capability = as_dag_capability(
        "dag", "DAG", run_dag,
        input_schema=schema,
        timeout_ms=5000,
        permissions={"admin"},
    )
    assert capability.input_schema == schema
    assert capability.timeout_ms == 5000
    assert "admin" in capability.permissions
