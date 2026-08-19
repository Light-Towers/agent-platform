"""TB-1 / TB-2 桥接契约测试。

验证 dialogue-framework 能通过适配器复用 agent_core 的内核协议，
且不破坏 DF 自身数据结构（红线）。
"""
from agent_core.llm.providers import BaseLLMProvider
from agent_core.memory.base import ConversationMemory
from dialogue_framework.core.tracker import Tracker
from dialogue_framework.shared.llm.base_client import BaseChatClient
from dialogue_framework.shared.llm.core_adapter import LLMCoreClient


class _StubProvider(BaseLLMProvider):
    """最小内核工厂协议实现，build 出一个伪 client。"""

    name = "stub"
    default_model = "stub-1"

    def build(self, model=None, json_mode=False, **kwargs):
        class _StubClient:
            async def ainvoke(self, *a, **k):
                return {"ok": True, "args": a, "kwargs": k}

            def with_structured_output(self, schema):
                self._schema = schema
                return self

        return _StubClient()


async def test_tb1_llm_core_client_implements_base_chat_client():
    client = LLMCoreClient(_StubProvider(), model="stub-1")
    assert isinstance(client, BaseChatClient)
    out = await client.ainvoke("hi", temperature=0)
    assert out == {"ok": True, "args": ("hi",), "kwargs": {"temperature": 0}}
    client.with_structured_output(dict)
    assert client.backend is not None


def test_tb2_tracker_bridges_conversation_memory():
    tracker = Tracker(session_id="s1")
    mem = tracker.to_conversation_memory()
    assert isinstance(mem, ConversationMemory)

    mid1 = mem.save("s1", "user", "你好")
    mid2 = mem.save("s1", "assistant", "您好")
    assert mid1 != mid2

    recent = mem.get_recent(10)
    assert len(recent) == 2
    assert recent[0]["role"] == "user"
    assert recent[1]["role"] == "assistant"

    mem.update("s1", mid1, "你好呀")
    assert mem.get_recent(10)[0]["text"] == "你好呀"

    mem.clear("s1")
    assert len(mem) == 0
    # Tracker 自有结构不被破坏：slots / stack 等仍存在
    assert tracker.session_id == "s1"
    assert tracker.slots == {}


def test_tb2_memory_adapter_rejects_wrong_session():
    tracker = Tracker(session_id="s1")
    mem = tracker.to_conversation_memory()
    try:
        mem.save("other", "user", "x")
    except ValueError:
        return
    raise AssertionError("应拒绝 session_id 不匹配")
