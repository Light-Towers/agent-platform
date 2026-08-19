"""9 种命令定义：对应 legacy command_prompt.jinja2。

start_flow / cancel_flow / change_flow / set_slot /
knowledge_answer / chitchat / cannot_handle / clarify / human_handoff
"""

from __future__ import annotations

from enum import Enum


class Command(str, Enum):
    """9 种对话命令。"""

    START_FLOW = "start_flow"
    CANCEL_FLOW = "cancel_flow"
    CHANGE_FLOW = "change_flow"
    SET_SLOT = "set_slot"
    KNOWLEDGE_ANSWER = "knowledge_answer"
    CHITCHAT = "chitchat"
    CANNOT_HANDLE = "cannot_handle"
    CLARIFY = "clarify"
    HUMAN_HANDOFF = "human_handoff"


COMMAND_DESCRIPTIONS = {
    Command.START_FLOW: "启动业务流程",
    Command.CANCEL_FLOW: "取消当前流程",
    Command.CHANGE_FLOW: "切换到新流程",
    Command.SET_SLOT: "设置槽位值",
    Command.KNOWLEDGE_ANSWER: "知识库回答",
    Command.CHITCHAT: "闲聊",
    Command.CANNOT_HANDLE: "无法处理",
    Command.CLARIFY: "澄清追问",
    Command.HUMAN_HANDOFF: "转人工",
}

INTENT_TO_COMMAND = {
    "order_query": Command.START_FLOW,
    "logistics_query": Command.START_FLOW,
    "postsale_query": Command.START_FLOW,
    "knowledge": Command.KNOWLEDGE_ANSWER,
    "chitchat": Command.CHITCHAT,
    "cannot_handle": Command.CANNOT_HANDLE,
    "clarify": Command.CLARIFY,
    "human_handoff": Command.HUMAN_HANDOFF,
}
