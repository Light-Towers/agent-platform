"""精确回忆：按 ``thread_id`` + checkpointer 回溯历史对话原文（优化 I）。

与优化 H 的「语义回忆」（LLM 抽取结构化事实 + 向量召回）正交：
- 语义回忆：跨会话、语义模糊匹配、可能丢失原文细节。
- 精确回忆（本模块）：按会话标识 ``thread_id`` 精确定位某次对话的真实内容，
  支持关键词过滤，返回逐条原文。用于「找到我之前某次聊天里具体说了什么」。

复用 LangGraph ``AsyncPostgresSaver`` 的 ``alist_messages`` / ``aget_thread_state``
（内核 ``get_checkpointer`` 工厂产出，已在 ``app.state.checkpointer`` 挂载）。
本模块零依赖内核契约扩展，仅消费其返回的消息对象。
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def _message_to_record(msg, idx: int) -> dict:
    """把 LangGraph BaseMessage 规整为可序列化记录。"""
    content = getattr(msg, "content", "")
    if isinstance(content, list):
        # 多模态 content 取文本部分
        text_parts = [
            p.get("text", "") for p in content if isinstance(p, dict) and p.get("text")
        ]
        content = "\n".join(text_parts)
    role = getattr(msg, "type", "unknown")
    # langgraph 消息 type 形如 'human'/'ai'/'tool'/'system'，归一化
    if role == "human":
        role = "user"
    elif role == "ai":
        role = "assistant"
    created = None
    ts = getattr(msg, "additional_kwargs", {}).get("created_at")
    if ts:
        try:
            created = datetime.fromisoformat(ts) if isinstance(ts, str) else ts
        except Exception:
            created = None
    return {
        "index": idx,
        "role": role,
        "content": content,
        "id": getattr(msg, "id", None),
        "created_at": created.isoformat() if isinstance(created, datetime) else None,
    }


async def get_thread_history(
    checkpointer,
    thread_id: str,
    keyword: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """精确取回某会话的完整历史（按时间序）。

    - ``keyword`` 非空时仅保留 content 含该子串的消息（精确匹配，非语义）。
    - ``limit`` 限制返回条数（取最后 N 条）。
    返回 ``[{index, role, content, id, created_at}, ...]``。
    """
    if checkpointer is None:
        return []
    try:
        msgs = await checkpointer.alist_messages(
            {"configurable": {"thread_id": thread_id}}
        )
    except Exception:
        logger.exception("精确回忆：读取 thread=%s 历史失败", thread_id)
        return []

    records = [_message_to_record(m, i) for i, m in enumerate(msgs)]
    if keyword:
        kw = keyword.lower()
        records = [r for r in records if kw in (r["content"] or "").lower()]
    if limit is not None and limit > 0:
        records = records[-limit:]
    return records


async def search_in_thread(
    checkpointer,
    thread_id: str,
    keyword: str,
) -> list[dict]:
    """在某会话历史中按关键词精确检索（精确回忆的核心入口）。

    与语义召回不同：这里匹配的是字面原文，定位「之前聊天具体说过什么」。
    """
    if not keyword:
        return []
    return await get_thread_history(checkpointer, thread_id, keyword=keyword)
