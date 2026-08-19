"""DialogueAgent：对话 Agent 入口（组装图 + 调用）。

负责：
- 构建 LangGraph 对话图
- 管理 Tracker Store（加载/保存会话状态）
- 提供 async chat() 入口供 API/Channel/CLI 调用
"""

from typing import Any

from agent_core.logging import get_logger

from dialogue_framework.agent.graph.builder import build_graph
from dialogue_framework.core.tracker import Tracker

logger = get_logger(__name__)


class DialogueAgent:
    """对话 Agent：封装编译后的图与 Store。"""

    def __init__(self, store=None, retriever=None) -> None:
        self._graph = build_graph()
        self._store = store
        self._retriever = retriever

    async def chat(self, session_id: str, message: str, **kwargs: Any) -> dict[str, Any]:
        tracker = await self._load_tracker(session_id)
        state: dict[str, Any] = {
            "tracker": tracker,
            "user_message": message,
            "retriever": self._retriever,
            "rephrase_enabled": kwargs.get("rephrase_enabled", False),
        }
        try:
            result = await self._graph.ainvoke(state)
        except Exception:
            logger.exception("graph invocation failed: session=%s", session_id)
            return {"response": "抱歉，处理时发生错误，请稍后重试。", "fallback": True}

        tracker = result.get("tracker", tracker)
        await self._save_tracker(tracker)
        return {
            "response": result.get("response", ""),
            "intent": result.get("intent"),
            "action_type": result.get("action_type"),
            "guard_passed": result.get("guard_passed", True),
        }

    async def _load_tracker(self, session_id: str) -> Tracker:
        if self._store is None:
            return Tracker(session_id=session_id)
        try:
            data = await self._store.load(session_id)
            if data:
                return Tracker.from_dict(data)
        except Exception:
            logger.exception("tracker load failed: session=%s", session_id)
        return Tracker(session_id=session_id)

    async def _save_tracker(self, tracker: Tracker) -> None:
        if self._store is None:
            return
        try:
            await self._store.save(tracker.session_id, tracker.to_dict())
        except Exception:
            logger.exception("tracker save failed: session=%s", tracker.session_id)
