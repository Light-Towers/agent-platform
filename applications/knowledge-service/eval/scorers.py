# -*- coding: utf-8 -*-
"""
端到端答案质量打分器（Phase C1 的 scorer 协议，Phase C2 三方替换实现的对象）。

设计目标（回应"检索差还是生成差要能分开归因"）：
- 把"给一条 (query, context, answer, reference) 打分"抽象成统一 **Scorer 协议**，
  `score(...) -> {faithfulness, relevance, correctness, reasons}`，值域归一 0..1；
  换实现（自研 LLM-as-judge / RAGAS / DeepEval）只需满足同一协议，运行器不改。
- **纯函数优先**：token 级启发式打分、上下文组装、judge JSON 解析、聚合都是确定性的
  纯 stdlib 逻辑，可在无 Milvus/LLM 环境单测；LLM judge 仅在其 score() 内延迟取客户端。

三个维度（与端到端报表口径一致）：
- faithfulness：答案是否忠于检索到的上下文（防幻觉）——答案内容 token 被上下文覆盖的比例；
- relevance：答案是否切题——答案与 query 的 token F1；
- correctness：对照 reference_answer 的正确性——答案与参考答案的 token F1（启发式）/ LLM 判定。

诚实约定：
- 缺 reference（如合成 golden 无 reference_answer）→ correctness 记 None（**不伪造**、不计入均值）；
- LLM 不可达 / 输出非法 → 该条打分记 skipped，绝不预填高分。
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional, Protocol, Sequence

from eval.gen_golden import parse_llm_json, tokenize_cn

# 打分维度（报表 / 聚合统一键名）
DIMS: Sequence[str] = ("faithfulness", "relevance", "correctness")

# LLM judge 每维 0/1/2 档 → 归一除数
JUDGE_SCALE = 2


# ---------------------------------------------------------------------------
# 纯 token 度量（确定性，供启发式打分与单测）
# ---------------------------------------------------------------------------
def _tokens(text: str) -> Counter:
    return Counter(tokenize_cn(text or ""))


def token_f1(a: str, b: str) -> float:
    """两段文本的 token 多重集 F1（0..1）。任一侧空 → 0.0（不猜高分）。"""
    ca, cb = _tokens(a), _tokens(b)
    if not ca or not cb:
        return 0.0
    overlap = sum((ca & cb).values())
    if overlap == 0:
        return 0.0
    precision = overlap / sum(ca.values())
    recall = overlap / sum(cb.values())
    if precision + recall == 0:
        return 0.0
    return round(2 * precision * recall / (precision + recall), 4)


def grounding_ratio(answer: str, context: str) -> float:
    """
    faithfulness 启发式代理：答案内容 token 有多少被上下文覆盖（越低越可能幻觉）。

    口径：|answer ∩ context| / |answer|（按去重 token 集）。答案为空 → 0.0。
    这是**词面接地度**，非语义蕴含；语义级 faithfulness 交给 LLM judge / RAGAS。
    """
    a, c = _tokens(answer), set(_tokens(context))
    if not a:
        return 0.0
    covered = len(set(a) & c)
    return round(covered / len(a), 4)


def normalize_grade(value: Any, scale: int = JUDGE_SCALE) -> Optional[float]:
    """把 LLM judge 的 0/1/2 档归一到 0..1；非法/越界 → None（不计入，不猜测）。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v < 0 or v > scale:
        return None
    return round(v / scale, 4)


# ---------------------------------------------------------------------------
# 上下文组装（检索层与生成层的边界产物）
# ---------------------------------------------------------------------------
def doc_text(doc: Dict[str, Any]) -> str:
    """从检索 doc 取正文（兼容 content / text / snippet / page_content 多形态）。"""
    if not isinstance(doc, dict):
        return str(doc or "")
    return str(doc.get("content") or doc.get("text") or doc.get("snippet") or doc.get("page_content") or "")


def build_context(docs: Sequence[Dict[str, Any]], *, max_chars: int = 6000, sep: str = "\n\n") -> str:
    """把检索到的候选拼成喂给 LLM 的上下文串，按 max_chars 截断（防超窗）。空列表 → 空串。"""
    parts: List[str] = []
    total = 0
    for doc in docs or []:
        t = doc_text(doc).strip()
        if not t:
            continue
        if total + len(t) > max_chars:
            remain = max_chars - total
            if remain > 0:
                parts.append(t[:remain])
            break
        parts.append(t)
        total += len(t) + len(sep)
    return sep.join(parts)


# ---------------------------------------------------------------------------
# Scorer 协议 + 两种实现
# ---------------------------------------------------------------------------
class Scorer(Protocol):
    """端到端打分器协议：Phase C2 的 RAGAS / DeepEval 适配亦须实现同名 score。"""

    name: str

    def score(
        self,
        *,
        query: str,
        context: str,
        answer: str,
        reference: Optional[str],
    ) -> Dict[str, Any]:
        """返回 {faithfulness, relevance, correctness, reasons, skipped?}；值域 0..1 或 None。"""
        ...


class HeuristicScorer:
    """确定性词面打分（零 LLM，可完全单测；作为 judge 不可用时的降级与对照基线）。"""

    name = "heuristic"

    def score(self, *, query: str, context: str, answer: str, reference: Optional[str]) -> Dict[str, Any]:
        return {
            "faithfulness": grounding_ratio(answer, context),
            "relevance": token_f1(answer, query),
            "correctness": token_f1(answer, reference) if reference else None,
            "reasons": {},
        }


class LLMJudgeScorer:
    """
    自研 LLM-as-judge（透明 prompt + 可导出理由，符合 spec.md"保可控/零长期依赖"取向）。

    - 每维 0/1/2 档，归一到 0..1；解析失败 → 该条 skipped（不猜值）。
    - 惰性取客户端（get_llm_client(json_mode=True)），构造期不连外部服务。
    - Phase C2 用它与 RAGAS/DeepEval 在同一人工裁决集上做四维对比。
    """

    name = "llm_judge"

    def __init__(self, llm: Any = None) -> None:
        self._llm = llm

    def _client(self) -> Any:
        if self._llm is None:
            from knowledge_service.lm.lm_utils import get_llm_client

            self._llm = get_llm_client(json_mode=True)
        return self._llm

    def score(self, *, query: str, context: str, answer: str, reference: Optional[str]) -> Dict[str, Any]:
        prompt = judge_prompt(query=query, context=context, answer=answer, reference=reference)
        try:
            raw = self._client().invoke(prompt)
            text = getattr(raw, "content", raw)
            data = parse_llm_json(str(text))
        except Exception as e:  # noqa: BLE001 —— judge 为外部 I/O，异常面宽，诚实降级为 skipped
            return {"faithfulness": None, "relevance": None, "correctness": None, "reasons": {}, "skipped": True, "error": str(e)}
        reasons = {
            "faithfulness": str(data.get("faithfulness_reason", ""))[:500],
            "relevance": str(data.get("relevance_reason", ""))[:500],
            "correctness": str(data.get("correctness_reason", ""))[:500],
        }
        return {
            "faithfulness": normalize_grade(data.get("faithfulness")),
            "relevance": normalize_grade(data.get("relevance")),
            "correctness": normalize_grade(data.get("correctness")) if reference else None,
            "reasons": reasons,
        }


def make_scorer(kind: str, *, llm: Any = None) -> Scorer:
    """按名构造打分器（运行器用 --scorer 选择；未知名报错，不静默降级）。"""
    if kind == "judge":
        return LLMJudgeScorer(llm=llm)
    if kind == "heuristic":
        return HeuristicScorer()
    raise ValueError(f"未知 scorer：{kind!r}（可选 judge/heuristic）")


# ---------------------------------------------------------------------------
# prompt 构造（内联，导出供 meta-eval 复核；不碰生产 prompt 目录）
# ---------------------------------------------------------------------------
def default_answer_prompt(*, query: str, context: str, item_name: str = "") -> str:
    """RAG 生成答案的 prompt：仅依据上下文作答，无依据须说明。"""
    scope = f"（限定商品：{item_name}）" if item_name else ""
    ref = context or "（无检索结果）"
    return (
        "你是设备说明书智能问答助手。请**仅依据下面提供的参考资料**回答用户问题"
        f"{scope}；资料中没有的信息不要编造，如无法回答请明确说明。\n"
        f"参考资料：\n{ref}\n\n"
        f"用户问题：{query}\n\n"
        "请给出简洁、准确的回答："
    )


def judge_prompt(*, query: str, context: str, answer: str, reference: Optional[str]) -> str:
    """自研 judge 的透明评分指令：三维度各 0/1/2 档 + 理由，严格 JSON。"""
    ref_block = reference if reference else "（无参考答案，correctness 请打 1 并注明）"
    return (
        "你是 RAG 答案质量评审。依据给定材料对**回答**打分，严格输出一个 JSON 对象（无多余文字）：\n"
        "{\n"
        '  "faithfulness": 0/1/2, "faithfulness_reason": "简短中文理由",\n'
        '  "relevance": 0/1/2, "relevance_reason": "...",\n'
        '  "correctness": 0/1/2, "correctness_reason": "..."\n'
        "}\n"
        "档位含义：0=差/无关/幻觉，1=部分成立，2=完全忠实/切题/正确。\n"
        "维度：faithfulness=回答是否只基于参考资料（防编造）；relevance=是否切题；"
        "correctness=是否与参考答案一致。\n"
        f"【用户问题】{query}\n"
        f"【参考资料】{context or '（空）'}\n"
        f"【待评回答】{answer or '（空）'}\n"
        f"【参考答案】{ref_block}"
    )


# ---------------------------------------------------------------------------
# 聚合（缺值/ skip 不计入均值，不伪造）
# ---------------------------------------------------------------------------
def aggregate_scores(records: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """
    对 per-query 生成层打分记录求各维度均值（跳过 None/skipped）。

    每条 record 形如 {dim: float|None, ..., "skipped"?: bool}。
    返回 {dim: {"mean": float|None, "n": int}}；某维度全无有效值 → mean=None（诚实标注非 0）。
    """
    out: Dict[str, Any] = {}
    for dim in DIMS:
        vals = [r[dim] for r in records if r.get(dim) is not None and not r.get("skipped")]
        out[dim] = {"mean": round(sum(vals) / len(vals), 4) if vals else None, "n": len(vals)}
    return out


__all__ = [
    "DIMS",
    "Scorer",
    "HeuristicScorer",
    "LLMJudgeScorer",
    "make_scorer",
    "token_f1",
    "grounding_ratio",
    "normalize_grade",
    "doc_text",
    "build_context",
    "default_answer_prompt",
    "judge_prompt",
    "aggregate_scores",
]
