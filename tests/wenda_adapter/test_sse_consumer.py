"""测试 wenda-adapter JSON 转发逻辑。"""

from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_client(status_code: int = 200, payload: dict | None = None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload or {}
    client = AsyncMock()
    client.post = AsyncMock(return_value=resp)
    return client


@pytest.mark.asyncio
async def test_query_json_answer():
    import main

    client = _make_client(200, {"answer": "hello", "latency_ms": 12.3})
    main._client = client
    result = await main.query({"query": "ping"})
    assert result["answer"] == "hello"
    assert result["fallback"] is False


@pytest.mark.asyncio
async def test_query_json_with_error():
    import main

    client = _make_client(200, {"answer": "", "error": "boom"})
    main._client = client
    result = await main.query({"query": "ping"})
    assert result["fallback"] is True
    assert result["data"]["metadata"]["error"] == "boom"


@pytest.mark.asyncio
async def test_query_non_200():
    import main

    client = _make_client(503, {})
    main._client = client
    result = await main.query({"query": "ping"})
    assert result["fallback"] is True
    assert "503" in result["answer"]


@pytest.mark.asyncio
async def test_query_empty_query():
    import main

    main._client = _make_client()
    result = await main.query({"query": ""})
    assert result["answer"] == ""
