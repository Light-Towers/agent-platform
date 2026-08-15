"""提示词构建器：构建对话理解提示词。"""

from dialogue_framework.core.tracker import Tracker

_COMMAND_SYSTEM = """你是对话理解模块。分析用户消息并输出命令列表（JSON 数组）。
可用命令类型：answer（直接回复）、slot（槽位填充）、flow（Flow 调用）、session（会话控制）、error。
输出格式：[{"type": "answer", "params": {"text": "..."}}]"""


def build_prompt(user_message: str, tracker: Tracker) -> str:
    slots_state = {n: s.value for n, s in tracker.slots.items() if s.filled}
    return f"{_COMMAND_SYSTEM}\n\n当前槽位状态：{slots_state}\n用户消息：{user_message}"
