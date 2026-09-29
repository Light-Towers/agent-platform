# -*- coding: utf-8 -*-
"""
judge 选型 meta-eval（Phase C2，**有界 spike、不进生产**）。

回应用户诉求"为什么不比比看：自研 LLM-as-judge 和成熟框架哪个效果更好"——把"端到端质量框架选型"
本身做成一次**有对照、有裁决基准、有判据**的对比决策，而非拍脑袋站队（同时调和 AGENTS.md
"引入 RAGAS/DeepEval" vs spec.md "不引第三方、自研" 的决策冲突）。

四维对比（主判据 = 与人工一致性）：
  ① 与人工一致性：分箱 Cohen kappa（0/1/2 档）+ 原值 Spearman（agent_core.metrics.compare）。
  ② 成本：每条打分的 token 估算 + 端到端延迟（CostMeter）。
  ③ 依赖足迹：该候选引入的额外第三方包数（importlib.metadata 直依赖计数；未安装标 n/a）。
  ④ 可解释：候选是否导出可复核理由（self/部分框架 True）。

决策规则：一致性显著更高且成本/依赖可接受者胜出；三者差异落在噪声内 → 按 spec.md 取**自研**
（保可控、零长期依赖）。**未胜出方不进 pyproject 生产依赖**（本 spike 只做临时对照）。

诚实约定：
  - RAGAS/DeepEval 默认**未安装**（生产不固化）。未安装候选标 available=False，不出假数字；
    需要对比时在 spike 环境临时 `uv pip install ragas/deepeval` 后复跑，用完即弃。
  - 一致性只在 human 与 model **都有标**的样本上算；缺标剔除，不伪造。

裁决集（人工标注）来源：
  - `--from-e2e <e2e_per_query.jsonl>` 抽样导出待标注模板（human 列留空）；
  - 人工填 0/1/2 后用 `--adjudication <file.jsonl>` 读回打分对比。

用法：
  python eval/meta_eval_judge.py --from-e2e eval/runs/<run>/e2e_per_query.jsonl --sample 30   # 出模板
  python eval/meta_eval_judge.py --adjudication eval/adjudication.jsonl --candidates self,ragas,deepeval
"""

import argparse
import importlib.metadata
import json
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# 脚本直跑路径引导：`python eval/meta_eval_judge.py` 时把项目根加入 sys.path。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 纯 stdlib + agent-core 统计原语（零重依赖，--help 可打印）。
from agent_core.metrics.compare import cohens_kappa, spearman_rho  # noqa: E402

from eval.ablation import estimate_tokens  # noqa: E402
from eval.scorers import DIMS, LLMJudgeScorer  # noqa: E402

DEFAULT_OUT_DIR: Path = Path(__file__).resolve().parent
JUDGE_SELECTION_FILE = "judge_selection.md"
ADJUDICATION_TEMPLATE = "adjudication_template.jsonl"

# 候选：self=自研 judge（零额外依赖）；ragas/deepeval 为临时对照工具。
CANDIDATE_PACKAGES: Dict[str, Optional[str]] = {
    "self": None,          # 自研：无额外第三方包
    "ragas": "ragas",
    "deepeval": "deepeval",
}
# 是否可导出可复核理由（元信息；ragas 部分指标带 reason 视版本，保守标 False 待核）。
EXPLAINABLE: Dict[str, bool] = {"self": True, "ragas": False, "deepeval": False}

# 路径 3（AI 交叉一致）中“收敛”的 κ 阈值（Landis & Koch substantial）。
# 背景与三分支决策见 docs/plans/plan-c2-cross-agreement-pivot-2026-09-29.md。
CROSS_AGREEMENT_THRESHOLD: float = 0.6


# ---------------------------------------------------------------------------
# 纯统计/装配（可完全单测）
# ---------------------------------------------------------------------------
def to_bucket(x: Optional[float]) -> Optional[int]:
    """把归一 0..1 打分箱到 0/1/2（与人工档位对齐）；None 透传。"""
    if x is None:
        return None
    return max(0, min(2, int(round(x * 2))))


def agreement_metrics(
    human: Sequence[Optional[int]], model: Sequence[Optional[float]]
) -> Dict[str, Any]:
    """
    只在双方都有效的样本上算一致性：kappa（人工档 vs 模型分箱档）+ Spearman（人工档 vs 模型原值）。

    有效 = human 非 None 且 model 非 None。不足 2 条 → 该度量 None（不猜显著性）。
    """
    hs: List[int] = []
    ms: List[float] = []
    for h, m in zip(human, model):
        if h is None or m is None:
            continue
        hs.append(int(h))
        ms.append(float(m))
    n = len(hs)
    if n < 2:
        return {"kappa": None, "spearman": None, "n": n}
    model_bins = [to_bucket(v) for v in ms]
    kappa = cohens_kappa(hs, [b if b is not None else 0 for b in model_bins])
    rho = spearman_rho(hs, ms)
    return {"kappa": round(kappa, 4), "spearman": round(rho, 4), "n": n}


def direct_requires(pkg: Optional[str]) -> Optional[int]:
    """候选引入的额外直接依赖数（足迹代理）。self→0；未安装→None（n/a，不猜）。"""
    if pkg is None:
        return 0
    try:
        reqs = importlib.metadata.requires(pkg)
    except importlib.metadata.PackageNotFoundError:
        return None
    return len(list(reqs or []))


class CostMeter:
    """记录每条打分的 token 估算与延迟，供成本维度聚合。"""

    def __init__(self) -> None:
        self.tokens: List[int] = []
        self.latency_ms: List[float] = []

    def observe(self, prompt: str, out_text: str, elapsed_ms: float) -> None:
        self.tokens.append(estimate_tokens(prompt) + estimate_tokens(out_text))
        self.latency_ms.append(round(elapsed_ms, 1))

    def summary(self) -> Dict[str, Any]:
        if not self.tokens:
            return {"avg_tokens": None, "avg_latency_ms": None, "n": 0}
        return {
            "avg_tokens": round(sum(self.tokens) / len(self.tokens), 1),
            "avg_latency_ms": round(sum(self.latency_ms) / len(self.latency_ms), 1),
            "n": len(self.tokens),
        }


# ---------------------------------------------------------------------------
# 候选打分适配（self 实装；ragas/deepeval 惰性导入，未安装 → available False）
# ---------------------------------------------------------------------------
def score_self_judge(scorer: LLMJudgeScorer, rec: Dict[str, Any], meter: CostMeter) -> Dict[str, Optional[float]]:
    prompt_est = ""  # judge prompt 由 scorer 内部构造；成本用答案/上下文规模近似
    t0 = time.perf_counter()
    out = scorer.score(
        query=rec.get("query", ""),
        context=rec.get("context", ""),
        answer=rec.get("answer", ""),
        reference=rec.get("reference"),
    )
    elapsed = (time.perf_counter() - t0) * 1000
    if not out.get("skipped"):
        meter.observe(prompt_est, rec.get("answer", ""), elapsed)
    return {d: out.get(d) for d in DIMS}


def make_candidate_scorer(candidate: str, llm: Any = None):
    """
    返回 (available, score_fn)。self → LLMJudgeScorer；ragas/deepeval → 惰性探测，未安装则 available False。

    RAGAS/DeepEval 的具体 API 依版本而定，spike 在装好其包的环境里接入；此处仅提供协议一致的
    score_fn 挂点，**不在未验证时伪造其打分**。
    """
    if candidate == "self":
        scorer = LLMJudgeScorer(llm=llm)

        def _fn(rec: Dict[str, Any], meter: CostMeter) -> Dict[str, Optional[float]]:
            return score_self_judge(scorer, rec, meter)

        return True, _fn

    pkg = CANDIDATE_PACKAGES.get(candidate)
    try:
        importlib.metadata.version(pkg or candidate)
    except importlib.metadata.PackageNotFoundError:
        return False, None

    def _unwired(rec: Dict[str, Any], meter: CostMeter) -> Dict[str, Optional[float]]:  # pragma: no cover - spike 需接线
        raise NotImplementedError(
            f"{candidate} 已安装但本 spike 未接线其打分 API；"
            f"请在该环境实现 score_fn（faithfulness/correctness→0/1/2）后复跑，勿伪造。"
        )

    return True, _unwired


# ---------------------------------------------------------------------------
# 决策与报告（纯函数，可单测）
# ---------------------------------------------------------------------------
def decide(results: List[Dict[str, Any]]) -> Tuple[str, str]:
    """
    按四维定选：主判据 correctness+faithfulness 的平均 kappa；差异 <=0.05 视为噪声 → 选自研。

    results: [{candidate, available, agreement:{faithfulness:{kappa..}, correctness:{..}}, footprint, cost}]。
    返回 (胜出候选, 理由)。
    """
    available = [r for r in results if r.get("available")]
    if not available:
        return "self", "无任何候选可评（self 需 LLM、ragas/deepeval 未安装）；回退自研取向，待环境补齐复跑。"

    def mean_kappa(r: Dict[str, Any]) -> Optional[float]:
        ks = [
            (r.get("agreement", {}).get(d) or {}).get("kappa")
            for d in ("faithfulness", "correctness")
        ]
        vals = [k for k in ks if k is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    scored = [(r, mean_kappa(r)) for r in available]
    scored = [(r, k) for r, k in scored if k is not None]
    if not scored:
        return "self", "无人工一致性可算（缺人工标注）；按 spec.md 取向暂选自研，补标后复评。"

    best_row, best_k = max(scored, key=lambda x: x[1])
    self_rows = [k for r, k in scored if r["candidate"] == "self"]
    self_k = self_rows[0] if self_rows else None
    # 差异落噪声内（<=0.05）→ 选自研（保可控、零长期依赖）
    if self_k is not None and best_row["candidate"] != "self" and (best_k - self_k) <= 0.05:
        return "self", (
            f"自研 kappa≈{self_k} 与最优 {best_row['candidate']}（kappa={best_k}）差异 ≤0.05（噪声内）"
            f"→ 按 spec.md 取零依赖、可解释的自研 judge。"
        )
    if best_row["candidate"] == "self":
        return "self", f"自研 judge 与人工一致性最高（mean kappa={best_k}），维持零第三方依赖。"
    # 外部胜出，但强调"临时工具、不进生产"
    return best_row["candidate"], (
        f"{best_row['candidate']} 与人工一致性显著更高（mean kappa={best_k} > self={self_k}）；"
        f"如需引入须用户再批准，且**不得固化进 pyproject 生产依赖**（本 spike 仅临时对照）。"
    )


def _fmt_num(v: Any) -> str:
    return "n/a" if v is None else str(v)


def render_judge_selection(results: List[Dict[str, Any]], decision: Tuple[str, str], sample_note: str) -> str:
    winner, reason = decision
    lines: List[str] = [
        "# Judge 选型决策备忘（Phase C2 meta-eval）",
        "",
        f"- 裁决集：{sample_note}",
        f"- **决策**：采用 `{winner}`",
        f"- 依据：{reason}",
        "",
        "## 四维对比表（主判据=与人工一致性）",
        "",
        "| 候选 | 可用 | faithfulness κ/ρ | correctness κ/ρ | 额外依赖数 | 平均token/延迟(ms) | 可解释 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        ag = r.get("agreement", {})
        f = ag.get("faithfulness", {})
        c = ag.get("correctness", {})
        cost = r.get("cost", {})
        lines.append(
            f"| {r['candidate']} | {'✅' if r.get('available') else '❌(未安装)'} | "
            f"{_fmt_num(f.get('kappa'))}/{_fmt_num(f.get('spearman'))} | "
            f"{_fmt_num(c.get('kappa'))}/{_fmt_num(c.get('spearman'))} | "
            f"{_fmt_num(r.get('footprint'))} | "
            f"{_fmt_num(cost.get('avg_tokens'))}/{_fmt_num(cost.get('avg_latency_ms'))} | "
            f"{'是' if r.get('explainable') else '否'} |"
        )
    lines += [
        "",
        "> κ=Cohen kappa（0/1/2 分箱），ρ=Spearman（原值秩相关）。κ/ρ 仅在人机双方都有标的样本上算。",
        "> 未安装候选标 ❌，不出假数字；需对比时在 spike 环境临时安装其包后复跑（用完即弃）。",
        "> 决策规则：一致性显著更高且成本/依赖可接受者胜出；差异≤0.05 视为噪声 → 取自研（spec.md 取向）。",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 裁决集：模板导出 / 读回
# ---------------------------------------------------------------------------
def export_adjudication_template(per_query_path: Path, out_path: Path, sample: int, seed: int) -> int:
    """从 e2e per-query 记录随机抽 sample 条，产出待人工填 human.faithfulness/correctness(0/1/2) 的模板。"""
    recs: List[Dict[str, Any]] = []
    with open(per_query_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                recs.append(json.loads(line))
    pick = random.Random(seed).sample(recs, k=min(sample, len(recs))) if recs else []
    with open(out_path, "w", encoding="utf-8") as f:
        for r in pick:
            tmpl = {
                "qid": r.get("qid"),
                "query": r.get("query"),
                "context": r.get("context", ""),
                "answer": r.get("answer", ""),
                "reference": r.get("reference"),
                "human": {"faithfulness": None, "correctness": None},  # 待人工填 0/1/2
            }
            f.write(json.dumps(tmpl, ensure_ascii=False) + "\n")
    return len(pick)


def load_adjudication(path: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def evaluate_candidate(candidate: str, records: List[Dict[str, Any]], llm: Any = None) -> Dict[str, Any]:
    """跑一个候选在裁决集上的打分 → 四维结果（与人工 human 档对比）。"""
    available, score_fn = make_candidate_scorer(candidate, llm=llm)
    footprint = direct_requires(CANDIDATE_PACKAGES.get(candidate))
    base = {
        "candidate": candidate,
        "available": available,
        "footprint": footprint,
        "explainable": EXPLAINABLE.get(candidate, False),
    }
    if not available:
        base["agreement"] = {}
        base["cost"] = {"avg_tokens": None, "avg_latency_ms": None, "n": 0}
        base["note"] = "未安装（spike 环境临时安装后复跑）"
        return base

    meter = CostMeter()
    model_fa: List[Optional[float]] = []
    model_co: List[Optional[float]] = []
    human_fa: List[Optional[int]] = []
    human_co: List[Optional[int]] = []
    wired = True
    for rec in records:
        try:
            scored = score_fn(rec, meter)
        except NotImplementedError:
            wired = False
            break
        model_fa.append(scored.get("faithfulness"))
        model_co.append(scored.get("correctness"))
        h = rec.get("human") or {}
        human_fa.append(h.get("faithfulness"))
        human_co.append(h.get("correctness"))

    if not wired:
        base["agreement"] = {}
        base["cost"] = meter.summary()
        base["note"] = "已安装但打分 API 未接线（spike 待补），不计一致性、不伪造"
        return base

    base["agreement"] = {
        "faithfulness": agreement_metrics(human_fa, model_fa),
        "correctness": agreement_metrics(human_co, model_co),
    }
    base["cost"] = meter.summary()
    return base


# ---------------------------------------------------------------------------
# 路径 3：AI 交叉一致性（无人工金标准，只回答“要不要引入外部框架”）
# ---------------------------------------------------------------------------
def agreement_symmetric(
    a: Sequence[Optional[float]], b: Sequence[Optional[float]]
) -> Dict[str, Any]:
    """两个模型分数列→成对一致性（双方都分箱算 κ，原值算 ρ）。缺值剔除，<2 返 None。"""
    av: List[float] = []
    bv: List[float] = []
    for x, y in zip(a, b):
        if x is None or y is None:
            continue
        av.append(float(x))
        bv.append(float(y))
    n = len(av)
    if n < 2:
        return {"kappa": None, "spearman": None, "n": n}
    ab = [to_bucket(v) for v in av]
    bb = [to_bucket(v) for v in bv]
    kappa = cohens_kappa([int(i) for i in ab], [int(i) for i in bb])
    rho = spearman_rho(av, bv)
    return {"kappa": round(kappa, 4), "spearman": round(rho, 4), "n": n}


def score_records_for_candidate(
    candidate: str, records: List[Dict[str, Any]], llm: Any = None
) -> Dict[str, Dict[str, Optional[float]]]:
    """跑一个候选在整批 records 上打分 → {qid: {faithfulness, correctness}}；不可用/未接线→{}。"""
    available, score_fn = make_candidate_scorer(candidate, llm=llm)
    if not available:
        return {}
    meter = CostMeter()
    out: Dict[str, Dict[str, Optional[float]]] = {}
    for rec in records:
        qid = rec.get("qid")
        if qid in (None, ""):
            continue
        try:
            s = score_fn(rec, meter)
        except NotImplementedError:
            return {}
        out[str(qid)] = {
            "faithfulness": s.get("faithfulness"),
            "correctness": s.get("correctness"),
        }
    return out


def pairwise_agreement(
    score_maps: Dict[str, Dict[str, Dict[str, Optional[float]]]],
    candidates: Sequence[str],
    dims: Sequence[str] = ("faithfulness", "correctness"),
) -> Dict[Tuple[str, str], Dict[str, Dict[str, Any]]]:
    """对称矩阵 {(a,b) 名字排序: {dim: agreement_symmetric 结果}}，跳过对角。"""
    result: Dict[Tuple[str, str], Dict[str, Dict[str, Any]]] = {}
    for i, a in enumerate(candidates):
        for b in candidates[i + 1:]:
            ma, mb = score_maps.get(a, {}), score_maps.get(b, {})
            common = sorted(set(ma.keys()) & set(mb.keys()))
            pair: Dict[str, Dict[str, Any]] = {}
            for dim in dims:
                xs = [ma[q].get(dim) for q in common]
                ys = [mb[q].get(dim) for q in common]
                pair[dim] = agreement_symmetric(xs, ys)
            key: Tuple[str, str] = (a, b) if a <= b else (b, a)
            result[key] = pair
    return result


def decide_cross_agreement(
    matrix: Dict[Tuple[str, str], Dict[str, Dict[str, Any]]],
    candidates: Sequence[str],
    threshold: float = CROSS_AGREEMENT_THRESHOLD,
) -> Tuple[str, str]:
    """三分支：三方收敛 → self；self 离群 → external；未收敛 → self + 回退信号。"""
    others = [c for c in candidates if c != "self"]
    if not others:
        return "self", "候选仅含 self，无外部对比；等待 RAGAS/DeepEval 接线后复跑。"
    self_ks: List[float] = []
    ext_ks: List[float] = []
    for (_a, _b), pair in matrix.items():
        vals = [(pair.get(d) or {}).get("kappa") for d in ("faithfulness", "correctness")]
        nums = [v for v in vals if v is not None]
        if not nums:
            continue
        avg = sum(nums) / len(nums)
        if _a == "self" or _b == "self":
            self_ks.append(avg)
        else:
            ext_ks.append(avg)
    if not self_ks:
        return "self", (
            "self 与外部候选无可比对样本（外部未安装/未接线，或共同 qid 不足）；"
            "按 spec.md 保留 self，Stage 2 补齐外部适配后复跑。"
        )
    avg_se = sum(self_ks) / len(self_ks)
    avg_ee = (sum(ext_ks) / len(ext_ks)) if ext_ks else None
    label_se = f"self-外部 κ={avg_se:.3f}"
    label_ee = f"外部对 κ={avg_ee:.3f}" if avg_ee is not None else "外部对 κ=n/a"
    if avg_se >= threshold and (avg_ee is None or avg_ee >= threshold):
        return "self", (
            f"三方交叉一致（{label_se}≥{threshold}，{label_ee}）"
            f"→ 判据收敛，维持零依赖 self。"
        )
    if avg_ee is not None and avg_ee >= threshold and avg_se < threshold:
        return "external", (
            f"self 与外部低一致（{label_se}<{threshold}）、外部之间高（{label_ee}≥{threshold}）"
            f"→ self 为离群者，建议评估引入外部胜出方（不固化 pyproject 生产依赖，另行批准）。"
        )
    return "self", (
        f"判据未收敛（{label_se}，{label_ee}）→ 三对都低，评判标准本身分歧过大；"
        f"回退路径 2：补人工标注后再评。"
    )


def render_cross_agreement(
    candidates: Sequence[str],
    score_maps: Dict[str, Dict[str, Dict[str, Optional[float]]]],
    matrix: Dict[Tuple[str, str], Dict[str, Dict[str, Any]]],
    decision: Tuple[str, str],
    sample_note: str,
    threshold: float,
) -> str:
    winner, reason = decision
    lines: List[str] = [
        "# Judge 选型决策备忘（Phase C2 · 路径 3 AI 交叉一致性）",
        "",
        f"- 数据源：{sample_note}",
        f"- 阈值：κ ≥ {threshold}（substantial，Landis & Koch）",
        f"- **决策**：`{winner}`",
        f"- 依据：{reason}",
        "",
        "## 成对一致性矩阵（对角略；F=faithfulness，C=correctness）",
        "",
        "|  \\  | " + " | ".join(candidates) + " |",
        "|---|" + "---|" * len(candidates),
    ]
    for a in candidates:
        row: List[str] = [a]
        for b in candidates:
            if a == b:
                row.append("—")
                continue
            key = (a, b) if a <= b else (b, a)
            pair = matrix.get(key)
            if not pair or all(
                (pair.get(d) or {}).get("kappa") is None for d in ("faithfulness", "correctness")
            ):
                row.append("n/a")
                continue
            f = pair.get("faithfulness", {})
            c = pair.get("correctness", {})
            row.append(
                f"F κ={_fmt_num(f.get('kappa'))} ρ={_fmt_num(f.get('spearman'))} · "
                f"C κ={_fmt_num(c.get('kappa'))} ρ={_fmt_num(c.get('spearman'))}"
            )
        lines.append("| " + " | ".join(row) + " |")
    lines += [
        "",
        "## 候选覆盖",
        "",
        "| 候选 | 打分数 | 额外依赖数 | 可解释 |",
        "|---|---|---|---|",
    ]
    for c in candidates:
        n = len(score_maps.get(c, {}))
        fp = direct_requires(CANDIDATE_PACKAGES.get(c))
        lines.append(f"| {c} | {n} | {_fmt_num(fp)} | {'是' if EXPLAINABLE.get(c) else '否'} |")
    lines += [
        "",
        "> 路径 3 的 κ 为**代理指标**（AI 间一致度），不直接回答 self 对人是否准确。",
        "> 三方都低→应回退补人工（路径 2），不是“选外部”的信号。",
        "",
    ]
    return "\n".join(lines)


def run_mode3_cross_agreement(
    dataset_path: Path, candidates: Sequence[str], threshold: float, out_path: Path
) -> int:
    records = load_adjudication(dataset_path)
    if not records:
        print(f"错误：数据集 {dataset_path} 为空或格式不符。", file=sys.stderr)
        return 1
    llm: Any = None
    if "self" in candidates:
        try:
            from knowledge_service.lm.lm_utils import get_llm_client

            llm = get_llm_client(json_mode=True)
        except Exception as e:  # noqa: BLE001 —— 无 LLM 环境 self 不可评，诚实标注
            print(f"[cross] 警告：self judge LLM 不可用（{e}），其打分为空。", file=sys.stderr)
    score_maps = {c: score_records_for_candidate(c, records, llm=llm) for c in candidates}
    matrix = pairwise_agreement(score_maps, candidates)
    decision = decide_cross_agreement(matrix, candidates, threshold=threshold)
    sample_note = f"{len(records)} 条（候选：{', '.join(candidates)}；数据源 {dataset_path.name}）"
    md = render_cross_agreement(candidates, score_maps, matrix, decision, sample_note, threshold)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    print(f"[cross] 完成：{out_path}")
    print(f"[cross] 决策：{decision[0]} —— {decision[1]}")
    return 0


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="端到端 judge 选型 meta-eval：自研 judge vs RAGAS/DeepEval 四维对比（有界 spike，不进生产）。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--from-e2e", default=None, help="e2e_per_query.jsonl 路径；配合 --sample 出人工待标注模板")
    parser.add_argument("--sample", type=int, default=30, help="导出模板的抽样条数")
    parser.add_argument("--seed", type=int, default=0, help="抽样种子（可复现）")
    parser.add_argument("--template-out", default=str(DEFAULT_OUT_DIR / ADJUDICATION_TEMPLATE), help="待标注模板输出")
    parser.add_argument("--adjudication", default=None, help="已人工标注的裁决集 jsonl（跑对比）")
    parser.add_argument("--candidates", default="self", help="逗号分隔候选（self,ragas,deepeval）")
    parser.add_argument("--out", default=str(DEFAULT_OUT_DIR / JUDGE_SELECTION_FILE), help="judge_selection.md 输出")
    # 路径 3：AI 交叉一致性（无人工金标准）
    parser.add_argument("--cross-agreement", action="store_true",
                        help="路径 3：AI 交叉一致性（无需人工金标准，只回答‘要不要引入外部框架’）")
    parser.add_argument("--dataset", default=None,
                        help="路径 3 数据集 jsonl（含 qid/query/context/answer/reference，human 列忽略）")
    parser.add_argument("--threshold", type=float, default=CROSS_AGREEMENT_THRESHOLD,
                        help="路径 3 κ 收敛阈值（substantial）")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    # 模式 1：出模板（不连外部服务）
    if args.from_e2e:
        n = export_adjudication_template(Path(args.from_e2e), Path(args.template_out), args.sample, args.seed)
        print(f"[meta-eval] 已导出待标注模板 {n} 条 → {args.template_out}")
        print("[meta-eval] 请人工在每条 human.faithfulness / human.correctness 填 0/1/2 后用 --adjudication 复跑。")
        return 0

    # 模式 3：AI 交叉一致（路径 3，无需人工金标准）
    if args.cross_agreement:
        if not args.dataset:
            print("错误：--cross-agreement 需配 --dataset <path>。", file=sys.stderr)
            return 1
        cands3 = [c.strip() for c in args.candidates.split(",") if c.strip()]
        return run_mode3_cross_agreement(
            Path(args.dataset), cands3, args.threshold, Path(args.out)
        )

    # 模式 2：跑对比
    if not args.adjudication:
        print(
            "错误：需提供 --from-e2e（出模板）/ --adjudication（跑人机对比）/ --cross-agreement+--dataset（跑 AI 交叉对比）。",
            file=sys.stderr,
        )
        return 1

    records = load_adjudication(Path(args.adjudication))
    if not records:
        print(f"错误：裁决集 {args.adjudication} 为空。", file=sys.stderr)
        return 1

    # self judge 需 LLM；惰性探测（失败则 self 也不可用，诚实标注）
    llm = None
    if "self" in args.candidates:
        try:
            from knowledge_service.lm.lm_utils import get_llm_client

            llm = get_llm_client(json_mode=True)
        except Exception as e:  # noqa: BLE001 —— 无 LLM 环境 self 不可评，诚实标注
            print(f"[meta-eval] 警告：self judge LLM 不可用（{e}），其一致性将无值。", file=sys.stderr)

    cands = [c.strip() for c in args.candidates.split(",") if c.strip()]
    results = [evaluate_candidate(c, records, llm=llm) for c in cands]
    decision = decide(results)
    sample_note = f"{len(records)} 条（候选：{', '.join(cands)}）"
    md = render_judge_selection(results, decision, sample_note)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[meta-eval] 完成：{out_path}")
    print(f"[meta-eval] 决策：采用 {decision[0]} —— {decision[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
