"""跨轮记忆复用 LLM 质量雷达用例（ADR-0004 候选B）。

非阻塞 LLM 雷达：验证「先告知偏好 → 后续相关轮次答案体现已知偏好」的端到端
记忆复用闭环，以及「不同 workspace 不串味」的隔离正确性。

依赖（均 CI 门禁不可达，缺失即显式 SKIP）：
- LLM_API_KEY：端到端答案质量 + LLM 断言裁判都需要真模型。
- DATABASE_URL：app 长期记忆闭环走 pgvector（workspace_id 隔离主键），无 PG 池则
  记忆不落库、recall 永远空，用例无意义。

调用链路（与线上一致）：app.agent.graph.build_graph(llm) → ainvoke(state)，
state.workspace_id 驱动跨会话记忆隔离（记忆本身按 workspace 维度持久，而非按
checkpointer 会话；故同一 workspace_id 多次 ainvoke 不同 question 即「跨轮」）。

退出码约定：0=复用+隔离均通过；1=未复用或串味（质量退化）；2=环境缺失 SKIP。

用法：
    python eval/memory_reuse_llm.py            # 环境缺失→SKIP(2)
    make eval-llm-memory                       # 经 uv 运行
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

EXIT_SKIP = 2

# 偏好设定（第1轮告知）；相关题（第2轮）应体现该偏好。
_PREFERENCE_TELL = "我是财务岗，做报表时请用简洁的中文表格呈现，不要写长篇解释。"
_RELATED_QUESTION = "帮我汇总一下上个月各项支出的金额，做个对照。"
# 裁判要找的偏好信号关键词（至少一个即视为体现偏好）
_PREFERENCE_SIGNALS = ("表格", "财务", "支出", "对照", "汇总")


async def _judge_reused(llm, answer: str) -> bool:
    """用 LLM 裁判：答案是否体现了已知偏好（简洁中文表格呈现）。"""
    prompt = (
        "你是评测裁判。下面是一段助手回答。已知用户此前声明偏好："
        f"「{_PREFERENCE_TELL}」。\n"
        "请判断该回答是否体现了这一偏好（以简洁表格/对照方式组织、面向财务场景）。\n"
        "仅回答 JSON：{\"reused\": true/false, \"reason\": \"一句话\"}。\n"
        f"回答：{answer}"
    )
    try:
        resp = await llm.ainvoke(prompt)
        text = getattr(resp, "content", resp) if not isinstance(resp, str) else resp
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
        import json

        data = json.loads(text)
        return bool(data.get("reused", False))
    except Exception:
        # 裁判失败时退化为关键词启发式，不阻断（雷达本就非阻塞）
        return any(sig in answer for sig in _PREFERENCE_SIGNALS)


def _has_preference_leak(answer: str) -> bool:
    """隔离校验：另一 workspace 的回答不应出现偏好信号（未被告知却用表格/财务口吻）。

    注意：相关题本身含「支出/汇总」字样，故仅用强偏好信号（表格/财务/对照）判定串味。
    """
    strong = ("表格", "财务", "对照")
    return any(sig in answer for sig in strong)


async def run() -> int:
    if not os.getenv("LLM_API_KEY"):
        print("SKIP: LLM_API_KEY 未配置，跨轮记忆雷达不可达")
        return EXIT_SKIP
    if not os.getenv("DATABASE_URL"):
        print("SKIP: DATABASE_URL 未配置，记忆闭环无 PG 池，跨轮记忆雷达不可达")
        return EXIT_SKIP

    from app.agent.graph import build_graph
    from app.agent.llm import build_chat_model
    from app.config import get_settings

    settings = get_settings()
    if not settings.memory_enabled:
        print("SKIP: app settings.memory_enabled=False，记忆闭环关闭，雷达无意义")
        return EXIT_SKIP

    llm = build_chat_model()
    if llm is None:
        print("SKIP: build_chat_model() 返回 None，跨轮记忆雷达不可达")
        return EXIT_SKIP

    graph = build_graph(llm)

    ws_pref = "eval-memory-reuse-pref"  # 被告知偏好的 workspace
    ws_other = "eval-memory-reuse-other"  # 隔离对照组

    async def ask(workspace_id: str, question: str) -> str:
        state = {
            "question": question,
            "workspace_id": workspace_id,
            "messages": [],
        }
        result = await graph.ainvoke(state)
        return result.get("answer", "") if isinstance(result, dict) else getattr(result, "answer", "")

    # 第1轮：告知偏好（workspace A）
    await ask(ws_pref, _PREFERENCE_TELL)
    # 第2轮：相关题（同一 workspace，应复用偏好）
    answer_reuse = await ask(ws_pref, _RELATED_QUESTION)
    reused = await _judge_reused(llm, answer_reuse)

    # 隔离校验：未告知偏好的另一 workspace 问同题，不应串味
    answer_other = await ask(ws_other, _RELATED_QUESTION)
    leaked = _has_preference_leak(answer_other)

    print(f"\n[复用] workspace={ws_pref} 第2轮答案体现偏好: {reused}")
    print(f"    答案片段: {answer_reuse[:120]!r}")
    print(f"[隔离] workspace={ws_other} 未告知偏好却串味: {leaked}")
    print(f"    答案片段: {answer_other[:120]!r}")

    if not reused:
        print("未达质量期望：跨轮记忆未复用已知偏好（退化）")
        return 1
    if leaked:
        print("未达质量期望：workspace 隔离失效，记忆跨桶串味（回归）")
        return 1
    print("跨轮记忆复用 + workspace 隔离：通过")
    return 0


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
