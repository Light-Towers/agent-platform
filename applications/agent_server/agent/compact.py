"""上下文压缩：多轮会话 token 超阈值时，将旧消息摘要为一条。

参考 Claude Code / Codex CLI / OpenCode 三源标配的 compact 机制：
- 估算当前消息 token 数；
- 超过阈值（默认 80% 模型窗口）时，用 LLM 将较早的消息摘要为一条 SystemMessage；
- 保留最近若干条原始消息不动（短期上下文完整性）；
- 无 LLM 时跳过（无法生成摘要），不阻塞主链路。
"""

import logging
from typing import Any

from agent_core.tokenizer import estimate_tokens as _count_tokens
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

_KEEP_RECENT = 4
_SUMMARY_PROMPT = (
    "你是上下文压缩器。将以下对话历史压缩为一条简洁的摘要，保留：\n"
    "1. 用户的核心问题和意图；\n"
    "2. 已确定的事实和结论；\n"
    "3. 关键上下文（如路由决策、证据要点）。\n"
    "丢弃寒暄、重复、中间推理过程。输出纯文本摘要，不超过 500 字。"
)


def estimate_tokens(messages: list[Any], model: str | None = None) -> int:
    """统计消息列表的 token 数。

    优先走 ``agent_core.tokenizer``（OpenAI 系精确计数，其他启发式），
    传入 ``model`` 可启用精确计数；不传则启发式估算。
    """
    return _count_tokens(messages, model)


def _msg_content(msg: Any) -> str:
    if isinstance(msg, (SystemMessage, HumanMessage, AIMessage)):
        return str(msg.content)
    if isinstance(msg, dict):
        return str(msg.get("content", ""))
    if isinstance(msg, (list, tuple)):
        return str(msg)
    return str(msg)


def should_compact(
    messages: list[Any], threshold_tokens: int, model: str | None = None
) -> bool:
    """消息 token 估算超过阈值且可压缩消息数 > _KEEP_RECENT 时返回 True。"""
    if len(messages) <= _KEEP_RECENT:
        return False
    return estimate_tokens(messages, model) > threshold_tokens


async def compact_messages(
    messages: list[Any], llm, model: str | None = None
) -> tuple[list[Any], str | None]:
    """将旧消息摘要为一条 SystemMessage，保留最近 _KEEP_RECENT 条。

    返回 (压缩后的消息列表, 错误信息)。
    成功时错误信息为 None；失败时返回原始消息不变，错误信息供上层降级。
    """
    if len(messages) <= _KEEP_RECENT:
        return messages, None

    old_messages = messages[:-_KEEP_RECENT]
    recent_messages = messages[-_KEEP_RECENT:]

    old_text = "\n".join(f"[{_msg_role(m)}] {_msg_content(m)}" for m in old_messages)

    try:
        raw = await llm.ainvoke(
            [
                {"role": "system", "content": _SUMMARY_PROMPT},
                {"role": "user", "content": old_text},
            ]
        )
        summary = raw.content if hasattr(raw, "content") else str(raw)
    except Exception as exc:
        logger.warning("上下文压缩失败，保留原始消息: %s", exc)
        return messages, f"COMPACTION_FAILED: {exc}"

    compacted = [SystemMessage(content=f"[上下文摘要] {summary}")] + recent_messages
    logger.info(
        "上下文压缩完成: %d 条消息 → %d 条, token 估算 %d → %d",
        len(messages),
        len(compacted),
        estimate_tokens(messages, model),
        estimate_tokens(compacted, model),
    )
    return compacted, None


def _msg_role(msg: Any) -> str:
    if isinstance(msg, SystemMessage):
        return "system"
    if isinstance(msg, HumanMessage):
        return "user"
    if isinstance(msg, AIMessage):
        return "assistant"
    if isinstance(msg, dict):
        return msg.get("role", "unknown")
    return "unknown"
