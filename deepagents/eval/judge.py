#!/usr/bin/env python3
"""
deepagents 评测裁判：rubric 逐项打分 + 不同 provider 去偏。

按 eval/PROPOSAL.md §8 步骤 3 落地。
- entity 验收点：字符串包含判断（无需 LLM）
- conclusion 验收点：LLM 语义判断（judge 用不同 provider 去偏）
- judge provider 由环境变量 EVAL_JUDGE_* 覆盖，缺省降级同主模型并告警
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1].resolve()
sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)

_JUDGE_MODEL = None
_JUDGE_IS_FALLBACK = False


def build_judge_model():
    """构建 judge 模型。优先读 EVAL_JUDGE_* 环境变量，缺省降级同主模型。"""
    global _JUDGE_MODEL, _JUDGE_IS_FALLBACK
    if _JUDGE_MODEL is not None:
        return _JUDGE_MODEL, _JUDGE_IS_FALLBACK

    judge_model = os.getenv("EVAL_JUDGE_MODEL", "")
    judge_base = os.getenv("EVAL_JUDGE_BASE_URL", "")
    judge_key = os.getenv("EVAL_JUDGE_API_KEY", "")
    judge_provider = os.getenv("EVAL_JUDGE_PROVIDER", "openai")

    if judge_model and judge_base and judge_key:
        from langchain.chat_models import init_chat_model
        prev_key = os.environ.get("OPENAI_API_KEY")
        prev_url = os.environ.get("OPENAI_BASE_URL")
        try:
            os.environ["OPENAI_API_KEY"] = judge_key
            os.environ["OPENAI_BASE_URL"] = judge_base
            _JUDGE_MODEL = init_chat_model(model=judge_model, model_provider=judge_provider)
        finally:
            if prev_key is not None:
                os.environ["OPENAI_API_KEY"] = prev_key
            else:
                os.environ.pop("OPENAI_API_KEY", None)
            if prev_url is not None:
                os.environ["OPENAI_BASE_URL"] = prev_url
            else:
                os.environ.pop("OPENAI_BASE_URL", None)
        logger.info("judge 模型: %s (provider=%s)", judge_model, judge_provider)
        return _JUDGE_MODEL, False

    from agent.llm import model as main_model
    _JUDGE_MODEL = main_model
    _JUDGE_IS_FALLBACK = True
    logger.warning("未配置 EVAL_JUDGE_*，judge 降级同主模型（self-bias 风险）")
    return _JUDGE_MODEL, True


def score_entity(answer: str | None, value: str, must_contain: bool) -> bool:
    """entity 验收点：字符串包含判断。"""
    if answer is None:
        return False
    contained = value in answer
    return contained if must_contain else not contained


async def score_conclusion(query: str, answer: str | None, value: str, model) -> tuple[bool, str]:
    """conclusion 验收点：LLM 语义判断。返回 (hit, reason)。"""
    if answer is None:
        return False, "answer 为空（incomplete）"

    prompt = (
        "你是评测裁判。判断以下回答是否满足给定要求。\n\n"
        f"【问题】\n{query}\n\n"
        f"【回答】\n{answer}\n\n"
        f"【要求】\n{value}\n\n"
        '只回答一行 JSON，格式：{"satisfied": true, "reason": "简短理由"} '
        '或 {"satisfied": false, "reason": "简短理由"}'
    )

    from langchain_core.messages import HumanMessage
    try:
        resp = await model.ainvoke([HumanMessage(content=prompt)])
        content = resp.content if hasattr(resp, "content") else str(resp)
        match = re.search(r'\{[^}]*"satisfied"[^}]*\}', content)
        if match:
            data = json.loads(match.group())
            return bool(data.get("satisfied", False)), data.get("reason", "")
        return False, f"judge 返回解析失败: {content[:100]}"
    except Exception as e:
        logger.warning("conclusion judge 异常: %s", e)
        return False, f"judge 异常: {type(e).__name__}"


async def score_rubric(query: str, answer: str | None, acceptance_points: list, model) -> dict:
    """对单题的 acceptance_points 逐项打分。"""
    details = []
    hit = 0
    for pt in acceptance_points:
        pt_type = pt.get("type", "")
        value = pt.get("value", "")
        must_contain = pt.get("must_contain", True)
        if pt_type == "entity":
            ok = score_entity(answer, value, must_contain)
            details.append({"type": "entity", "value": value, "hit": ok, "method": "string_match"})
        elif pt_type == "conclusion":
            ok, reason = await score_conclusion(query, answer, value, model)
            details.append({"type": "conclusion", "value": value, "hit": ok, "method": "llm_judge", "reason": reason})
        else:
            details.append({"type": pt_type, "value": value, "hit": False, "method": "unknown_type"})
        if details[-1]["hit"]:
            hit += 1
    total = len(acceptance_points)
    return {
        "hit": hit,
        "total": total,
        "rate": round(hit / total, 4) if total else 0.0,
        "details": details,
    }


async def judge_record(record: dict, model=None) -> dict:
    """对单条评测记录打 rubric 分。返回 {"rubric_score": {...}}。"""
    if model is None:
        model, _ = build_judge_model()
    answer = record.get("answer")
    query = record.get("query", "")
    points = record.get("acceptance_points", [])
    if not points:
        return {"rubric_score": None}
    return {"rubric_score": await score_rubric(query, answer, points, model)}
