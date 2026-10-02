# -*- coding: utf-8 -*-
"""
RAGAS 0.4.x 打分适配（Phase C2 路径 3，**有界 spike、不进生产依赖**）。

背景：meta_eval_judge 的 mode 3（AI 交叉一致）需要一个与 self judge 契约一致的候选打分器。
本模块把 RAGAS 的 collections API 适配为 meta_eval_judge 期望的 `score_fn(rec, meter)`：

  rec 键           → RAGAS 参数
  query            → user_input
  context          → retrieved_contexts（单元素 list）
  answer           → response
  reference        → reference（缺 → correctness None）

真实 API 经 126 spike 容器端到端验证（ragas 0.4.3）：
  - Faithfulness(llm).ascore(user_input, response, retrieved_contexts) -> MetricResult(.value∈0..1)
  - AnswerCorrectness(llm, weights=[1.0,0.0]).ascore(user_input, response, reference) -> MetricResult(.value)
    * weights=[1.0,0.0] 关闭 embedding 相似度分量，走纯 claim-based 事实性打分，
      避免 spike 环境额外引入 embedding 模型（语义仍对应"答案 vs 参考"的正确性）。

诚实约定：
  - 任一维度内部异常 → 该维 None（不伪造数字）；整批判分仍由上层按 None 剔除。
  - 环境缺 ragas / 缺网关 env / 构造失败 → make_score_fn 返回 (False, None)，上层标 available False。
  - 生产 pyproject 不引入 ragas；仅在 spike 容器临时装。用完即弃。
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import types
from typing import Any, Callable, Dict, Optional, Tuple

DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"


def _stub_vertexai() -> None:
    """ragas 0.4.3 无条件 import langchain_community.chat_models.vertexai（未装会炸）。

    仅注入一个占位 ChatVertexAI 类满足 import 链；spike 不使用 vertexai。
    """
    name = "langchain_community.chat_models.vertexai"
    if name in sys.modules:
        return
    stub = types.ModuleType(name)

    class ChatVertexAI:  # noqa: D101 - 占位，仅为满足 ragas 顶层 import
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

    stub.ChatVertexAI = ChatVertexAI  # type: ignore[attr-defined]
    sys.modules[name] = stub


def _gateway_config() -> Tuple[str, str, Optional[str]]:
    """从容器 env 解析 (model, base_url, api_key)。缺 key 抛错交由上层降级 available False。"""
    model = os.environ.get("RAG_EVAL_MODEL") or DEFAULT_MODEL
    base_url = os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 未设置，RAGAS adapter 无法运行")
    return model, base_url, api_key


def _extract_value(result: Any) -> Optional[float]:
    """MetricResult.value → float；None/异常 → None（不猜值）。"""
    try:
        v = getattr(result, "value", None)
    except Exception:  # noqa: BLE001 - 外部对象属性访问面宽，诚实降级
        return None
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


async def _score_one(
    faithfulness: Any, answer_correctness: Any, rec: Dict[str, Any]
) -> Dict[str, Optional[float]]:
    """对单条记录并发跑 faithfulness + correctness，各自异常隔离为 None。"""
    query = rec.get("query") or ""
    context = rec.get("context") or ""
    answer = rec.get("answer") or ""
    reference = rec.get("reference")

    contexts = [context] if context else []

    async def _faith() -> Optional[float]:
        if not contexts:
            return None  # 无上下文，faithfulness 无意义，不伪造
        res = await faithfulness.ascore(
            user_input=query, response=answer, retrieved_contexts=contexts
        )
        return _extract_value(res)

    async def _correct() -> Optional[float]:
        if not reference:
            return None  # 缺 reference，correctness 不可算（与 self judge 口径一致）
        res = await answer_correctness.ascore(
            user_input=query, response=answer, reference=reference
        )
        return _extract_value(res)

    f_task = asyncio.ensure_future(_faith())
    c_task = asyncio.ensure_future(_correct())
    f_val = c_val = None
    try:
        f_val = await f_task
    except Exception:  # noqa: BLE001 - 单维隔离
        f_val = None
    try:
        c_val = await c_task
    except Exception:  # noqa: BLE001
        c_val = None
    return {"faithfulness": f_val, "correctness": c_val}


def make_score_fn() -> Tuple[bool, Optional[Callable[[Dict[str, Any], Any], Dict[str, Optional[float]]]]]:
    """
    构造 RAGAS 打分器。返回 (available, score_fn)。

    - available False：ragas 未装 / 网关 env 缺失 / 构造失败（上层标 available False，不出假数字）。
    - score_fn(rec, meter) -> {"faithfulness", "correctness"}，各 0..1 或 None。

    仅在 meta_eval_judge 惰性调用；生产环境不装 ragas，此函数首行 import 即失败 → (False, None)。
    """
    try:
        import importlib.metadata

        importlib.metadata.version("ragas")
    except Exception:  # noqa: BLE001 - ragas 未装即不可用
        return False, None

    try:
        _stub_vertexai()
        from openai import AsyncOpenAI
        from ragas.llms import llm_factory
        from ragas.metrics.collections import AnswerCorrectness, Faithfulness

        model, base_url, api_key = _gateway_config()
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        llm = llm_factory(model, provider="openai", client=client)
        faithfulness = Faithfulness(llm=llm)
        answer_correctness = AnswerCorrectness(llm=llm, weights=[1.0, 0.0])
    except Exception:  # noqa: BLE001 - 构造期任何失败诚实降级为不可用
        return False, None

    def score_fn(rec: Dict[str, Any], meter: Any) -> Dict[str, Optional[float]]:
        t0 = time.perf_counter()
        # meta_eval_judge 主流程为同步、无运行中 event loop，每条起一个 run 可接受（spike 规模 30）
        out = asyncio.run(_score_one(faithfulness, answer_correctness, rec))
        elapsed = (time.perf_counter() - t0) * 1000
        try:
            meter.observe("", rec.get("answer", ""), elapsed)
        except Exception:  # noqa: BLE001, S110 - meter 记账失败不影响打分结果
            pass
        return out

    return True, score_fn


__all__ = ["make_score_fn", "DEFAULT_MODEL"]
