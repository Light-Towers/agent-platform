"""测试公共 fixture（契约 v1.1）。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest

from exhibition_agent.client.warehouse_client import WarehouseClient
from exhibition_agent.contract.execution_context import ExecutionContext
from exhibition_agent.mock_server.warehouse_mock import create_mock_app
from exhibition_agent.testing_helpers import ctx, ctx_header, make_context_payload, make_header


@pytest.fixture
def execution_context() -> ExecutionContext:
    """默认合法 ExecutionContext（v1.1 测试便利性：正常用例无感）。"""
    return ctx()


@pytest.fixture
def execution_context_header(execution_context: ExecutionContext) -> str:
    """合法 ExecutionContext 编码成 X-Execution-Context 头值（JWT）。"""
    return ctx_header(execution_context, mode="jwt")


@pytest.fixture
def context_payload() -> dict:
    return make_context_payload()


@pytest.fixture
def jwt_header(context_payload: dict) -> str:
    return make_header(context_payload, mode="jwt")


@pytest.fixture
def base64_header(context_payload: dict) -> str:
    return make_header(context_payload, mode="base64")


@pytest.fixture
def mock_app():
    return create_mock_app()


@pytest.fixture
async def mock_transport(mock_app) -> AsyncIterator[httpx.ASGITransport]:
    transport = httpx.ASGITransport(app=mock_app)
    yield transport


@pytest.fixture
def warehouse_client(mock_transport: httpx.ASGITransport) -> WarehouseClient:
    return WarehouseClient(
        base_url="http://mock-warehouse",
        transport=mock_transport,
        timeout=5.0,
    )
