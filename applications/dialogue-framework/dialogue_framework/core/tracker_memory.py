"""Tracker 与内核 ConversationMemory 的桥接（TB-2 闭环）。

dialogue-framework 的 ``Tracker`` 负责「对话状态追踪」（slots / events / stack），
agent_core 的 ``ConversationMemory`` 定义「会话消息记忆」最小协议
（save / get_recent / clear / update）。

两者语义不同，不应让 Tracker 继承 ConversationMemory。本模块提供：

* ``TrackerConversationMemory``：实现内核 ``ConversationMemory`` 协议的适配器，
  把 user / assistant 消息落进 ``Tracker.events``（以约定结构存储，不破坏原追踪语义）。
* ``Tracker.to_conversation_memory()``：在 ``tracker.py`` 中挂载，返回上述适配器，
  使 DF 的对话状态可桥接进内核记忆契约，供其他 agent 复用。

红线：不修改 Tracker 自有数据结构，仅做协议对齐桥接。
"""
from typing import Any, Iterator

from agent_core.memory.base import ConversationMemory

from dialogue_framework.core.tracker import Tracker

# Tracker.events 中消息型记录的 event 名（与追踪事件区分）
_EVENT_MESSAGE = "message"
# 角色取值遵循内核 ConversationMemory 约定：user / assistant（字面量，避免跨包常量耦合）
_ROLE_USER = "user"
_ROLE_ASSISTANT = "assistant"


class TrackerConversationMemory(ConversationMemory):
    """把内核 ConversationMemory 协议映射到 Tracker.events 的适配器。"""

    def __init__(self, tracker: Tracker) -> None:
        self._tracker = tracker

    def save(self, session_id: str, role: str, text: str, **kwargs: Any) -> str:
        if session_id != self._tracker.session_id:
            raise ValueError(
                f"session_id 不匹配：适配器绑定 {self._tracker.session_id!r}，收到 {session_id!r}"
            )
        message_id = kwargs.get("message_id") or f"m{len(self._tracker.events)}"
        self._tracker.add_event(
            {
                "event": _EVENT_MESSAGE,
                "message_id": message_id,
                "role": role,
                "text": text,
                **{k: v for k, v in kwargs.items() if k != "message_id"},
            }
        )
        return message_id

    def get_recent(self, n: int = 10) -> list[dict[str, Any]]:
        messages = [
            e for e in self._tracker.events if e.get("event") == _EVENT_MESSAGE
        ]
        return messages[-n:]

    def clear(self, session_id: str) -> None:
        if session_id != self._tracker.session_id:
            raise ValueError(
                f"session_id 不匹配：适配器绑定 {self._tracker.session_id!r}，收到 {session_id!r}"
            )
        self._tracker.events = [
            e for e in self._tracker.events if e.get("event") != _EVENT_MESSAGE
        ]

    def update(self, session_id: str, message_id: str, new_text: str) -> None:
        if session_id != self._tracker.session_id:
            raise ValueError(
                f"session_id 不匹配：适配器绑定 {self._tracker.session_id!r}，收到 {session_id!r}"
            )
        for e in self._tracker.events:
            if e.get("event") == _EVENT_MESSAGE and e.get("message_id") == message_id:
                e["text"] = new_text
                return
        raise KeyError(f"message_id {message_id!r} 不存在于该 Tracker")

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self.get_recent(n=len(self)))

    def __len__(self) -> int:
        return len(
            [e for e in self._tracker.events if e.get("event") == _EVENT_MESSAGE]
        )
