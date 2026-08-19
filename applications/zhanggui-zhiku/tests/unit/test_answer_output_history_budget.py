# -*- coding: utf-8 -*-
"""
test_answer_output_history_budget.py —— 修复 2 回归测试：历史对话长度预算（O(n) 单条增量）。

背景（代码审查发现）：
    node_answer_output.step_2_construct_prompt 旧实现中
    ``used += len(history_str) + 2`` 使用**累积拼接后的总长**累加（O(n²)），
    导致 used 严重高估、历史对话被过早截断。修复后每轮只累加该轮新增文本长度。

本文件直接测试修复后抽取的纯函数 ``format_history``
（app/query_process/agent/prompt_budget.py），不依赖 LLM / Milvus / MongoDB /
fastapi / loguru 等重型依赖，可在纯逻辑环境独立运行（仅需 pytest）。

覆盖：
1. 单轮增量 = len(该轮文本)+2，多次累加为线性（对比旧行为 O(n²) 会超预算）；
2. 预算充足时 N 轮历史全部保留；
3. 预算紧张时按序截断（break 停止追加后续轮次，截断发生在预算耗尽处）；
4. history_str 最终内容与旧实现完全一致（修复只影响 used 计算与截断时机）；
5. 空历史 / 无效消息的兜底行为。
"""

from app.query_process.agent.prompt_budget import format_history


# ---------------------------------------------------------------------------
# 旧实现参考（仅用于对比断言：证明修复只改变 used 计算，不改变 history_str 内容）
# ---------------------------------------------------------------------------
def _old_format_history(history, used=0, max_chars=12000):
    """复刻修复前的 O(n²) 实现（node_answer_output.py 旧代码）。"""
    history_str = ""
    if history:
        for msg in history:
            role = msg.get("role")
            text = msg.get("text")
            if role == "user" and text:
                history_str += f"用户: {text}\n"
            elif role == "assistant" and text:
                history_str += f"助手: {text}\n"
            used += len(history_str) + 2
            if used > max_chars:
                break
    else:
        history_str = "无历史对话"
    return history_str, used


def _turn(role, text):
    """构造与生产代码一致的轮次文本块。"""
    prefix = "用户" if role == "user" else "助手"
    return f"{prefix}: {text}\n"


# ===========================================================================
# 1) 单轮增量 = len(该轮文本)+2，线性累加（旧行为 O(n²) 会超预算）
# ===========================================================================
def test_per_turn_increment_is_linear_not_quadratic():
    texts = ["甲" * 100, "乙" * 100, "丙" * 100]
    history = [
        {"role": "user", "text": texts[0]},
        {"role": "assistant", "text": texts[1]},
        {"role": "user", "text": texts[2]},
    ]
    max_chars = 500

    # 期望：每轮只累加该轮新增文本长度（len(turn) + 2），共 3 轮线性之和
    expected_used = sum(len(_turn(history[i]["role"], texts[i])) + 2 for i in range(3))

    history_str, used = format_history(history, used=0, max_chars=max_chars)

    assert used == expected_used
    assert used <= max_chars  # 修复后未超预算

    # 旧实现 used 为累积拼接后总长之和（O(n²)），必然超预算
    _, old_used = _old_format_history(history, used=0, max_chars=max_chars)
    assert old_used > max_chars  # 旧行为会超预算
    assert used < old_used  # 新计算严格小于旧计算

    # 3 轮文本全部保留（输出内容不受 used 计算方式影响）
    assert all(t in history_str for t in texts)


def test_old_quadratic_over_budget_drops_later_turn_new_keeps_it():
    # 4 轮、每轮文本 100 字符：旧实现第 3 轮即超预算（break 后丢弃第 4 轮），
    # 新实现线性累加后 4 轮全部在预算内。
    texts = ["甲" * 100, "乙" * 100, "丙" * 100, "丁" * 100]
    history = [
        {"role": "user", "text": texts[0]},
        {"role": "assistant", "text": texts[1]},
        {"role": "user", "text": texts[2]},
        {"role": "assistant", "text": texts[3]},
    ]
    max_chars = 500

    history_str, used = format_history(history, used=0, max_chars=max_chars)
    old_str, old_used = _old_format_history(history, used=0, max_chars=max_chars)

    assert used <= max_chars
    assert old_used > max_chars  # 旧实现超预算
    assert all(t in history_str for t in texts)  # 新实现保留全部 4 轮
    assert texts[-1] not in old_str  # 旧实现丢弃了第 4 轮（截断过早）


# ===========================================================================
# 2) 预算充足时 N 轮历史全部保留
# ===========================================================================
def test_all_turns_kept_when_budget_large():
    n = 10
    history = [{"role": "user" if i % 2 == 0 else "assistant", "text": f"第{i + 1}轮对话内容"} for i in range(n)]
    max_chars = 1_000_000

    history_str, used = format_history(history, used=0, max_chars=max_chars)

    expected_str = "".join(_turn(history[i]["role"], history[i]["text"]) for i in range(n))
    expected_used = sum(len(_turn(history[i]["role"], history[i]["text"])) + 2 for i in range(n))
    assert history_str == expected_str  # 全部 N 轮、顺序一致
    assert used == expected_used
    for i in range(n):
        assert f"第{i + 1}轮对话内容" in history_str


# ===========================================================================
# 3) 预算紧张时按序截断（break 停止追加后续轮次，截断发生在预算耗尽处）
# ===========================================================================
def test_truncation_at_budget_exhaustion():
    # 每轮文本 = "X"*50 + 唯一后缀，turn 长度 = 4 + 51 + 1 = 56，增量 = 58
    n = 6
    history = [{"role": "user" if i % 2 == 0 else "assistant", "text": f"{'X' * 50}{i}"} for i in range(n)]
    inc = len(_turn("user", "X" * 50 + "0")) + 2  # 每轮固定增量
    max_chars = 2 * inc  # 恰好允许前 2 轮不超，第 3 轮推超预算

    history_str, used = format_history(history, used=0, max_chars=max_chars)

    # 截断发生在预算耗尽处：前 3 轮保留（第 3 轮为推超预算的那一轮，与原实现
    # 「break 在追加之后」语义一致），第 4 轮起停止追加
    expected_str = "".join(_turn(history[i]["role"], history[i]["text"]) for i in range(3))
    assert history_str == expected_str
    assert used == 3 * inc
    assert used > max_chars  # 推超预算的那一轮本身仍保留
    for i in range(3):
        assert f"{'X' * 50}{i}" in history_str
    for i in range(3, n):
        assert f"{'X' * 50}{i}" not in history_str  # 后续轮次被截断


# ===========================================================================
# 4) history_str 最终内容与旧实现完全一致（含无效消息不入文本）
# ===========================================================================
def test_history_str_identical_to_old_implementation():
    history = [
        {"role": "user", "text": "你好"},
        {"role": "assistant", "text": "您好！请问有什么可以帮您？"},
        {"role": "user", "text": ""},  # 空文本：旧实现不追加文本（但曾计入 used）
        {"role": "system", "text": "忽略我"},  # 未知角色：旧实现不追加文本（但曾计入 used）
        {"role": "user", "text": "HAK 180 烫金机怎么操作？"},
    ]

    new_str, _ = format_history(history, used=0, max_chars=1_000_000)
    old_str, _ = _old_format_history(history, used=0, max_chars=1_000_000)

    assert new_str == old_str
    assert "忽略我" not in new_str
    assert new_str == "用户: 你好\n助手: 您好！请问有什么可以帮您？\n用户: HAK 180 烫金机怎么操作？\n"


# ===========================================================================
# 5) 空历史 / 无效消息兜底
# ===========================================================================
def test_empty_history_uses_fallback_and_keeps_used():
    history_str, used = format_history([], used=123, max_chars=100)
    assert history_str == "无历史对话"
    assert used == 123  # 空历史不消耗预算


def test_invalid_messages_do_not_consume_budget():
    # 空文本 / 未知角色消息：既不进入 history_str，也不消耗预算（参考形态的 continue）
    history = [
        {"role": "user", "text": "A" * 50},
        {"role": "user", "text": ""},
        {"role": "system", "text": "B" * 50},
        {"role": "assistant", "text": "C" * 50},
    ]
    _, used = format_history(history, used=0, max_chars=1_000_000)

    inc_a = len(_turn("user", "A" * 50)) + 2
    inc_c = len(_turn("assistant", "C" * 50)) + 2
    assert used == inc_a + inc_c
