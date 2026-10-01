"""/query SSE 错误帧脱敏回归（Batch 4，C 类 py/stack-trace-exposure）。

``install_error_handlers`` 兜不住流式响应（状态码 200 已发出、帧已开），因此
``query_router._stream()`` 的 ``except`` 分支必须自行取 kernel 固定文案。

本用例故意让 graph 路径抛 ``AttributeError``（graph 未装配 = None）：修复前该异常
原文（含 ``NoneType`` / 内部属性名）会进 SSE 帧，修复后只留固定文案；异常全貌仍走
``logger.exception``（用替身断言其存在，保证“脱敏 ≠ 丢日志”）。

通过 ASGITransport 直接驱动 app（不触发 lifespan），与 ``test_query_lifecycle.py`` 同法。
"""

import json

import httpx  # noqa: E402
import pytest  # noqa: E402
from agent_core.guardrails.errors import SANITIZED_5XX_MSG  # noqa: E402
from agent_server.main import app as _app  # noqa: E402


def _make_settings():
    """关掉 coordination / admission / cache：本用例只关心 graph 异常后的错误帧。"""
    from agent_server.config import Settings

    s = Settings()
    s.coordination_enabled = False
    s.admission_enabled = False
    s.cache_enabled = False
    s.scheduler_enabled = False
    return s


@pytest.fixture
def app_without_graph(monkeypatch):
    app = _app
    monkeypatch.setattr("agent_server.api.query_router.get_settings", lambda: _make_settings())
    for attr, value in (
        ("graph", None),  # 未装配 → astream 抛 AttributeError，触发错误帧分支
        ("planner", None),
        ("planner_runtime", None),
        ("checkpointer", None),
        ("coordinator", None),
        ("admission_controller", None),
        ("scheduler", None),
        ("status_store", None),
        ("cost_governance", None),
        ("context_governor", None),
        ("otel_tracer", None),
    ):
        setattr(app.state, attr, value)
    yield app


class _RecordingLogger:
    """接管模块 logger，断言“对外脱敏但服务端日志仍有全貌”。

    不用 caplog：agent_core.logging 可能关掉 propagate，caplog 拿不到记录。
    """

    def __init__(self) -> None:
        self.exception_calls: list[tuple] = []

    def exception(self, *args, **kwargs) -> None:
        self.exception_calls.append(args)

    def warning(self, *args, **kwargs) -> None:
        pass

    def info(self, *args, **kwargs) -> None:
        pass

    def debug(self, *args, **kwargs) -> None:
        pass


@pytest.fixture
def recording_logger(monkeypatch):
    rec = _RecordingLogger()
    monkeypatch.setattr("agent_server.api.query_router.logger", rec)
    return rec


async def _post_query(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream("POST", "/query", json={"query": "hi"}) as resp:
            body = ""
            async for chunk in resp.aiter_text():
                body += chunk
            return resp.status_code, body


def _frames(body: str) -> list[dict]:
    """解析 SSE：返回每个 ``data:`` 行的 JSON 负载（附 event 名）。"""
    out: list[dict] = []
    for block in body.split("\n\n"):
        event = ""
        data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[len("event: "):].strip()
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        if data is not None:
            out.append({"event": event or data.get("type", ""), "data": data})
    return out


async def test_stream_error_frame_is_sanitized(app_without_graph, recording_logger):
    status, body = await _post_query(app_without_graph)
    assert status == 200, body

    error_frames = [f for f in _frames(body) if f["event"] == "error"]
    assert len(error_frames) == 1, f"应有且仅有一个 error 帧：{body}"
    assert error_frames[0]["data"]["error"] == SANITIZED_5XX_MSG

    # 修复前的泄漏面：异常原文（对象类型 / 属性名）不得出现在任何帧里
    assert "NoneType" not in body
    assert "astream" not in body

    # 脱敏不等于丢日志：服务端仍逐条记录了异常上下文
    assert recording_logger.exception_calls, "错误分支未落服务端日志"
    assert "query stream failed" in recording_logger.exception_calls[0][0]


async def test_stream_still_terminates_with_done_frame(app_without_graph):
    """错误分支后仍必须发 done 帧（前端据此结束流），契约不变。"""
    _status, body = await _post_query(app_without_graph)
    events = [f["event"] for f in _frames(body)]
    assert events[-1] == "done", body
