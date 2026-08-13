"""测试 SSE 流消费逻辑。"""


import httpx
import pytest
from main import _consume_sse_stream


def _make_response(lines: list[str]) -> httpx.Response:
    body = "\n".join(lines)
    return httpx.Response(200, text=body)


@pytest.mark.asyncio
async def test_consume_sse_result_string():
    lines = [
        'data: {"type": "result", "data": "hello"}',
        'data: {"type": "result", "data": " world"}',
    ]
    resp = _make_response(lines)
    answer, _data, error = await _consume_sse_stream(resp)
    assert answer == "hello world"
    assert error is None


@pytest.mark.asyncio
async def test_consume_sse_result_dict():
    lines = [
        'data: {"type": "result", "data": {"answer": "42", "meta": "x"}}',
    ]
    resp = _make_response(lines)
    answer, data, _error = await _consume_sse_stream(resp)
    assert answer == "42"
    assert data == {"answer": "42", "meta": "x"}


@pytest.mark.asyncio
async def test_consume_sse_error():
    lines = [
        'data: {"type": "error", "message": "boom"}',
    ]
    resp = _make_response(lines)
    _answer, _data, error = await _consume_sse_stream(resp)
    assert error == "boom"


@pytest.mark.asyncio
async def test_consume_sse_content_field():
    lines = [
        'data: {"type": "chunk", "content": "partial"}',
        'data: {"type": "final", "content": " done"}',
    ]
    resp = _make_response(lines)
    answer, data, _error = await _consume_sse_stream(resp)
    assert answer == "partial done"
    assert data is not None
    assert data["type"] == "final"


@pytest.mark.asyncio
async def test_consume_sse_skip_non_data_lines():
    lines = [
        ": comment",
        "",
        'data: {"type": "result", "data": "ok"}',
    ]
    resp = _make_response(lines)
    answer, _, _ = await _consume_sse_stream(resp)
    assert answer == "ok"


@pytest.mark.asyncio
async def test_consume_sse_skip_invalid_json():
    lines = [
        "data: not-json",
        'data: {"type": "result", "data": "ok"}',
    ]
    resp = _make_response(lines)
    answer, _, _ = await _consume_sse_stream(resp)
    assert answer == "ok"


@pytest.mark.asyncio
async def test_consume_sse_empty_stream():
    resp = _make_response([])
    answer, data, error = await _consume_sse_stream(resp)
    assert answer == ""
    assert data is None
    assert error is None
