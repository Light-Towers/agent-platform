"""POST /api/meta/ingest 写端点归属断言（#102）：无断言即 fail-fast，请求体归属拒收。

钉五件事：
1. 无任何身份断言 ⇒ 401 且零写入（不落任何桶）；
2. 携带 tenant_id/workspace_id 请求体字段 ⇒ 400（宁拒勿默，与断言有无无关）；
3. 断言绑定时租户取自断言，落点经 report 回传可见；
4. workspace 取服务端 default_workspace（断言路径缺位，#8 在册债）；
5. datasource 仍受理请求显式选源（目标选择非身份，与 /api/query 同权 P1-3）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agent_runtime.workspace_registry import bind_tenant_context, reset_tenant_context
from fastapi import HTTPException
from nl2sql_service.api.routers.ingest_router import ingest
from nl2sql_service.api.schemas.ingest_schema import IngestRequest

_DDL = "CREATE TABLE t (id INT)"


def _http_request() -> MagicMock:
    app = MagicMock()
    app.state.context = MagicMock(meta_repository=MagicMock())
    req = MagicMock()
    req.app = app
    return req


def _settings() -> MagicMock:
    s = MagicMock()
    s.default_workspace = "default-ws"
    s.default_tenant = ""
    s.datasource_id = "dw"
    s.embedding_backend = "mock"
    s.embedding_api_key = ""
    s.embedding_model = "m"
    s.embedding_base_url = ""
    s.vector_dim = 1024
    s.tokenizer = "bigram"
    return s


def _patches():
    return (
        patch("nl2sql_service.api.routers.ingest_router.get_settings", return_value=_settings()),
        patch(
            "nl2sql_service.clients.embedding_client_manager.build_embedder",
            return_value=MagicMock(),
        ),
        patch(
            "nl2sql_service.api.routers.ingest_router.write_scope",
            new=AsyncMock(
                return_value={
                    "columns": {"inserted": 1, "updated": 0},
                    "examples": {"inserted": 0, "updated": 0},
                }
            ),
        ),
    )


async def test_no_assertion_401_and_zero_write():
    http_request = _http_request()
    p_settings, p_embed, p_write = _patches()
    with p_settings, p_embed, p_write as write:
        with pytest.raises(HTTPException) as exc_info:
            await ingest(IngestRequest(ddl=_DDL), http_request)
    assert exc_info.value.status_code == 401
    write.assert_not_called(), "无断言必须零写入——不落任何桶"


async def test_body_scope_fields_rejected_400():
    """携带归属字段即 400——与断言有无无关（先拒字段，再见断言）。"""
    http_request = _http_request()
    p_settings, p_embed, p_write = _patches()
    with p_settings, p_embed, p_write:
        with pytest.raises(HTTPException) as exc_info:
            await ingest(IngestRequest(ddl=_DDL, tenant_id="evil"), http_request)
    assert exc_info.value.status_code == 400
    assert "请求体归属" in str(exc_info.value.detail)

    with p_settings, p_embed, p_write:
        with pytest.raises(HTTPException) as exc_info:
            await ingest(IngestRequest(ddl=_DDL, workspace_id="evil-ws"), http_request)
    assert exc_info.value.status_code == 400


async def test_scope_from_assertion_body_clean():
    token = bind_tenant_context("t-asserted")
    try:
        http_request = _http_request()
        p_settings, p_embed, p_write = _patches()
        with p_settings, p_embed, p_write as write:
            report = await ingest(IngestRequest(ddl=_DDL, datasource_id="custom-ds"), http_request)
    finally:
        reset_tenant_context(token)
    assert report.tenant_id == "t-asserted", "租户取自服务端断言，不落 default 桶"
    assert report.workspace_id == "default-ws", "workspace 取服务端 default（#8 在册）"
    assert report.datasource_id == "custom-ds", "datasource 显式选源仍受理（目标选择非身份）"
    assert write.call_args.kwargs["tenant_id"] == "t-asserted"
    assert write.call_args.kwargs["workspace_id"] == "default-ws"
    assert write.call_args.kwargs["datasource_id"] == "custom-ds"
