# -*- coding: utf-8 -*-
"""
Prompt 组装预算工具（纯逻辑，零外部依赖）。

背景（代码审查修复 2）：
    node_answer_output.step_2_construct_prompt 中，历史对话的长度累加使用了
    累积拼接后的 history_str 总长（``used += len(history_str) + 2``），
    导致 used 呈 O(n²) 增长、被严重高估，历史对话过早截断。
    本模块提供「每轮只累加该轮新增文本长度」的 O(n) 纯函数实现，
    供节点与单元测试复用（不依赖 LLM / Milvus / MongoDB / fastapi / loguru）。
"""

from typing import List, Tuple


def format_history(history: List[dict], used: int = 0, max_chars: int = 12000) -> Tuple[str, int]:
    """按预算把历史对话格式化为提示词文本块，返回 (history_str, used)。

    与 node_answer_output.step_2_construct_prompt 原实现保持完全相同的输出格式：
    - 用户轮      -> ``用户: {text}\\n``
    - 助手轮      -> ``助手: {text}\\n``
    - 无有效消息 / 空历史 -> ``无历史对话``

    预算语义（修复后，O(n)）：
    - 每轮只累加**该轮新增文本**的长度（``len(turn) + 2``），而非累积拼接后的总长；
    - 当 used 超过 max_chars 时 break，停止追加后续轮次（截断发生在预算耗尽处，
      超出预算的那一轮本身仍保留 —— 与原实现语义一致）。

    :param history: MongoDB 历史消息列表，元素形如 {"role": ..., "text": ...}
    :param used: 已使用的预算（通常为上文文档部分累加后的值）
    :param max_chars: 上下文总预算（默认与 node_answer_output.MAX_CONTEXT_CHARS 一致）
    :return: (history_str, 累加后的 used)
    """
    history_str = ""
    if history:
        for msg in history:
            role = msg.get("role")
            text = msg.get("text")
            if role == "user" and text:
                turn = f"用户: {text}\n"
            elif role == "assistant" and text:
                turn = f"助手: {text}\n"
            else:
                continue
            history_str += turn
            used += len(turn) + 2
            if used > max_chars:
                break
    else:
        history_str = "无历史对话"
    return history_str, used
