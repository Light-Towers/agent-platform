"""联邦 WS 出口统一测试（Plan-F WS 出口统一）。

验证 /ws/{thread_id} 端点：收 {"type":"query","text":...} → 经 AgenticPlanner.execute
产出 StreamEvent → 逐条 send_json（与 app /query 同构 serialize_stream_event）→ 收尾 done。
冻结 AgenticPlanner.execute（mock 为产固定 StreamEvent），不依赖真实 LLM。
"""

from __future__ import annotations

import os

# 确保 agent.llm 在 import server 时成功初始化（无真实 key 时的测试桩）
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("OPENAI_BASE_URL", "http://localhost/v1")
# 关闭 WS 端点认证（_check_api_key 依赖模块加载期计算的 _ALLOW_NO_AUTH）
os.environ.setdefault("DISABLE_AUTH", "true")

import agent_federation.api.server as server
from agent_runtime.planner.protocol import StreamEvent
from fastapi.testclient import TestClient


async def _fake_execute(self, plan, runtime):
    yield StreamEvent(type="route", payload={"capability": "agentic", "reason": "P3 兜底"})
    yield StreamEvent(type="answer", payload={"text": "上海共有 128 个用户。"})


def test_ws_query_streams_stream_events(monkeypatch):
    # 冻结 execute：避免真实 LLM / 重型 agent 执行
    import agent_federation.planners.agentic as agentic_mod

    monkeypatch.setattr(agentic_mod.AgenticPlanner, "execute", _fake_execute)

    client = TestClient(server.app)
    with client.websocket_connect("/ws/test_thread?api_key=dummy") as ws:
        ws.send_json({"type": "query", "text": "帮我查一下上海的用户"})
        route = ws.receive_json()
        answer = ws.receive_json()
        done = ws.receive_json()

    assert route == {"type": "route", "capability": "agentic", "reason": "P3 兜底"}
    assert answer == {"type": "answer", "text": "上海共有 128 个用户。"}
    assert done["type"] == "done"
    assert done["thread_id"] == "test_thread"
    assert done["answer"] == "上海共有 128 个用户。"


def test_ws_non_query_falls_back_to_pong(monkeypatch):
    import agent_federation.planners.agentic as agentic_mod

    monkeypatch.setattr(agentic_mod.AgenticPlanner, "execute", _fake_execute)

    client = TestClient(server.app)
    with client.websocket_connect("/ws/test_thread?api_key=dummy") as ws:
        # 合法 JSON 但非 query 类型：回退 pong（保持旧 echo 行为）
        ws.send_json({"type": "ping"})
        resp = ws.receive_json()

    assert resp["type"] == "pong"
