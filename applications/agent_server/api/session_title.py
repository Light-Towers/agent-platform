# -*- coding: utf-8 -*-
"""会话标题生成（首轮问答后按内容生成短标题，旁路 best-effort）。

职责单一：把「首条问题 + 回答」变成一行可上屏的短标题。不碰数据库、不碰会话归属——
那些在 sessions_service 里。这样生成的 prompt/清洗/回退策略可独立测试，且与主链路解耦。

设计纪律：
- **绝不抛异常**：LLM 未配置、超时、返回脏数据一律回退为截断的问题原文；调用方无需 try。
- **复用现有 LLM 客户端**（planner_runtime.llm / build_chat_model()），不引入新依赖。
- **不泄露长原文**：标题只取问题前若干字，回答只用于给 LLM 理解主题、不进回退文案。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_TITLE_PROMPT = (
    "请为下面这轮对话生成一个简短标题，用于会话列表中识别这段对话。\n"
    "要求：不超过20个字，中文，直接概括对话主题；"
    "只输出标题本身，不要引号、不要解释、不要标点结尾、不要 Markdown。\n"
    "用户：%(question)s\n助手：%(answer)s"
)

_FALLBACK_MAX = 40
"""回退标题（问题截断）的最大字符数，够在侧栏单行显示又不至于撑破布局。"""
_LLM_INPUT_MAX = 500
"""喂给 LLM 的问题/回答各取前 N 字，控制成本与延迟（标题只需主题，不需全文）。"""
_STRIP_CHARS = " \t\n\r\"'「」『』《》〈〉。.!！?？:：,，;；、~—-"
"""首尾要剥的字符：引号/书名号 + 尾随标点。合并成一个集合避免剥离顺序陷阱
（如「《标题》。」先剥引号会被句末的「。」挡住，导致右书名号残留）。"""


def _first_line(text: str) -> str:
    """取首行并去首尾空白——LLM 有时会多输出一句解释，标题只认第一行。"""
    return text.strip().splitlines()[0].strip() if text else ""


def _clean_llm_title(text: object) -> str:
    """清洗 LLM 输出：去代码块围栏/引号，取首行，截断。空则返回空串。"""
    if not isinstance(text, str):
        return ""
    title = text.strip()
    if title.startswith("```"):
        parts = title.split("```")
        if len(parts) >= 2:
            title = parts[1].strip()
    title = _first_line(title).strip(_STRIP_CHARS)
    return title[:_FALLBACK_MAX]


def fallback_title(question: str) -> str:
    """LLM 不可用时的确定性回退：问题首行截断。空问题给「新会话」。"""
    line = _first_line(question)
    return (line[:_FALLBACK_MAX] or "新会话")


async def generate_title(llm: object | None, question: str, answer: str) -> str:
    """按内容生成标题。任何异常/空结果都回退为截断问题，绝不抛出。

    :param llm: 具备 ``ainvoke(prompt)`` 的 LangChain 模型（可为 None → 直接回退）
    """
    fallback = fallback_title(question)
    if llm is None:
        return fallback
    try:
        prompt = _TITLE_PROMPT % {
            "question": question[:_LLM_INPUT_MAX],
            "answer": answer[:_LLM_INPUT_MAX],
        }
        resp = await llm.ainvoke(prompt)
        text = getattr(resp, "content", resp) if not isinstance(resp, str) else resp
        title = _clean_llm_title(text)
        return title or fallback
    except Exception as exc:  # noqa: BLE001 —— 标题是旁路，任何失败都退回截断问题
        logger.warning("会话标题生成失败，回退截断问题: %s", exc)
        return fallback
