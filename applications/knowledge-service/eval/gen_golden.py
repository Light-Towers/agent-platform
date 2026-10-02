# -*- coding: utf-8 -*-
"""
真实语料自举 golden（Phase A，落地 knowledge-service/docs/spec.md §1.1 决策）。

要解决的老问题：现有合成 golden 的 chunk content 内嵌原 query → 词法近似精确命中 →
**全路 Recall@10 恒为 1.0**，只能比排序、比不了召回，更比不了"某数据源该不该加"。
本脚本从 **Milvus 里的真实说明书 chunk** 自举 golden，天然带干扰块，召回不再饱和。

流程（live 模式）：
    1. `fetch_real_chunks`：从目标集合拉 N 条真实 chunk（chunk_id / content / item_name）。
    2. `synthesize_record`：对每条真实 chunk 调 LLM「基于该文本合成一条用户 query +
       一句 grounded 的 reference_answer + 归类 tag」，**直接回注真实 chunk_id** 作 relevant。
    3. 分桶补齐 + 干扰标注：`select_hard_negatives` 选"语义相近但不该命中"的块、
       `detect_near_dupes` 选近似重复块、`derive_expected_source` 标"该由哪条通道答"。
    4. 产出 `golden_queries.real.jsonl` + `golden_audit.md`（人工抽检表）。

诚实声明（务必读）：
    - golden 由 **LLM 基于真实 chunk 自举**，`reference_answer` 亦 LLM 草拟；`--audit N`
      随机抽 N 条导出复核表，**须人工确认标注质量后方可作为门禁基准**（spec.md 口径）。
    - 前置不满足（真实 chunk 不足 / 无 LLM key）→ 清晰报错终止，**绝不回退内嵌-query 玩具语料**
      （否则饱和问题原样保留，等于没做）。
    - 仅 eval/开发用，**不进生产运行时依赖**；不改动任何线上代码。

用法：
    python eval/gen_golden.py --dry-run                     # 只跑纯标注逻辑核对（不连 Milvus/LLM）
    python eval/gen_golden.py --collection <name> --target-count 120 --audit 30
    python eval/gen_golden.py --from-chunks dump.jsonl ...   # 离线：用导出的真实 chunk（仍需 LLM）

依赖（live）：Milvus 可达且目标集合有真实 chunk + LLM key。缺失即非 0 退出，不伪造。
"""

import argparse
import json
import os
import random
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from eval.ablation import EVAL_COLLECTION_NAME  # noqa: E402  纯 stdlib，供 setdefault / --help

DEFAULT_OUT: Path = Path(__file__).resolve().parent / "golden_queries.real.jsonl"
DEFAULT_AUDIT: Path = Path(__file__).resolve().parent / "golden_audit.md"

# query 类型四类（与现有 golden 对齐，供分桶分析 + expected_source 归因）
TAGS: Sequence[str] = ("参数查询", "操作步骤", "故障排查", "多跳")

# 通道名（与 retrieval.yaml channels 对齐）
CHANNELS: Sequence[str] = ("embedding", "hyde", "kg", "web")

# 故障排查 / 操作步骤关键词（derive_expected_source 与 tag 兜底用）
_KW_TROUBLE = ("故障", "报错", "异常", "无法", "失败", "怎么办", "解决", "排查", "告警")
_KW_HOWTO = ("如何", "怎么", "步骤", "流程", "操作", "设置", "配置", "连接", "安装")
_KW_MULTIHOP = ("以及", "同时", "分别", "对比", "并且", "然后")


# ---------------------------------------------------------------------------
# 轻量中文分词（纯函数，避免为评测拉起重型依赖）：CJK 单字 bigram + ASCII 词
# ---------------------------------------------------------------------------
def tokenize_cn(text: str) -> set:
    if not text:
        return set()
    tokens: set = set()
    ascii_word: List[str] = []
    prev_cjk = ""
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            if ascii_word:
                tokens.add("".join(ascii_word).lower())
                ascii_word = []
            if prev_cjk:
                tokens.add(prev_cjk + ch)  # CJK bigram
            prev_cjk = ch
        elif ch.isalnum():
            if prev_cjk:
                prev_cjk = ""
            ascii_word.append(ch)
        else:
            if ascii_word:
                tokens.add("".join(ascii_word).lower())
                ascii_word = []
            prev_cjk = ""
    if ascii_word:
        tokens.add("".join(ascii_word).lower())
    return tokens


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


# ---------------------------------------------------------------------------
# 干扰块选取（打破饱和的核心：强制检索要能区分相近但不相关的块）
# ---------------------------------------------------------------------------
def select_hard_negatives(
    target: Dict[str, Any],
    pool: Sequence[Dict[str, Any]],
    *,
    same_item_limit: int = 3,
    cross_item_limit: int = 3,
    min_overlap: float = 0.05,
) -> List[str]:
    """
    选"语义相近但不该命中"的块 id（grade 0，用于分析"干扰项是否压过 gold"）：
      - 同 item 其它 chunk（同类参数，最易混）；
      - 跨 item 但 token 重叠高的 chunk（同类目不同设备）。
    按 jaccard 相似度降序取，过滤掉重叠 < min_overlap 的（太不相干的没区分价值）。
    """
    t_tok = tokenize_cn(target.get("content", ""))
    t_id = str(target.get("chunk_id"))
    same: List[tuple] = []
    cross: List[tuple] = []
    for c in pool:
        cid = str(c.get("chunk_id"))
        if cid == t_id:
            continue
        sim = jaccard(t_tok, tokenize_cn(c.get("content", "")))
        if sim < min_overlap:
            continue
        if c.get("item_name") == target.get("item_name"):
            same.append((sim, cid))
        else:
            cross.append((sim, cid))
    same.sort(key=lambda x: x[0], reverse=True)
    cross.sort(key=lambda x: x[0], reverse=True)
    return [cid for _s, cid in same[:same_item_limit]] + [cid for _s, cid in cross[:cross_item_limit]]


def detect_near_dupes(
    target: Dict[str, Any],
    pool: Sequence[Dict[str, Any]],
    *,
    threshold: float = 0.6,
) -> List[str]:
    """近似重复块 id（jaccard >= threshold 且非自身）：检验去重与排序稳定性。"""
    t_tok = tokenize_cn(target.get("content", ""))
    t_id = str(target.get("chunk_id"))
    out: List[str] = []
    for c in pool:
        cid = str(c.get("chunk_id"))
        if cid == t_id:
            continue
        if jaccard(t_tok, tokenize_cn(c.get("content", ""))) >= threshold:
            out.append(cid)
    return out


def derive_expected_source(target: Dict[str, Any], query: str) -> str:
    """
    标注"该 query 本应由哪条通道答"（用于分通道贡献归因），确定性启发式：
      - 多跳（query 含并列/对比连接词 或 gold 跨多块）→ embedding（靠语义拼接）；
      - 含专有型号（字母+数字 token）→ kg（实体图谱强项）；
      - 操作步骤/故障排查（长语义描述）→ hyde；
      - 其余参数事实 → embedding。
    LLM 可覆写（synthesize_record 里如返回合法 channel 则优先）。
    """
    has_model = bool(re.search(r"[A-Za-z]+\s*\d+", query or ""))
    if any(k in (query or "") for k in _KW_MULTIHOP):
        return "embedding" if not has_model else "kg"
    if has_model and any(k in (query or "") for k in _KW_TROUBLE):
        return "kg"
    if any(k in (query or "") for k in _KW_HOWTO):
        return "hyde"
    if any(k in (query or "") for k in _KW_TROUBLE):
        return "hyde"
    if has_model:
        return "kg"
    return "embedding"


def guess_tag(query: str) -> str:
    """LLM 未给合法 tag 时的兜底归类。"""
    q = query or ""
    if any(k in q for k in _KW_TROUBLE):
        return "故障排查"
    if any(k in q for k in _KW_HOWTO):
        return "操作步骤"
    if any(k in q for k in _KW_MULTIHOP):
        return "多跳"
    return "参数查询"


# ---------------------------------------------------------------------------
# LLM 输出解析（稳健提取 JSON，容忍 markdown 围栏与前后噪声）
# ---------------------------------------------------------------------------
def parse_llm_json(text: str) -> Dict[str, Any]:
    """从 LLM 返回文本里抽出第一个 JSON 对象；失败抛 ValueError（由调用方计 skip，不猜值）。"""
    if not text:
        raise ValueError("空 LLM 输出")
    # 去 markdown 围栏
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        brace = re.search(r"\{.*\}", text, re.DOTALL)
        candidate = brace.group(0) if brace else None
    if candidate is None:
        raise ValueError(f"未找到 JSON 对象：{text[:80]!r}")
    data = json.loads(candidate)
    if not isinstance(data, dict):
        raise ValueError("LLM JSON 不是对象")
    return data


def synthesis_prompt(chunk: Dict[str, Any]) -> str:
    """构造"基于真实 chunk 合成 query + reference_answer + tag + channel"的指令（内联，不碰生产 prompt 目录）。"""
    content = str(chunk.get("content", ""))[:1200]
    item = str(chunk.get("item_name", ""))
    return (
        "你是设备说明书知识库的评测数据标注助手。阅读下面这段**真实说明书文本**，"
        "站在用户角度产出评测用问答，严格输出一个 JSON 对象（不要多余文字）：\n"
        "{\n"
        '  "query": "用户最可能就这段内容提出的一个自然问题",\n'
        '  "reference_answer": "仅依据这段内容可回答的简短标准答案（不得编造这段没有的事实）",\n'
        f'  "tag": "从 {list(TAGS)} 中选一个",\n'
        f'  "expected_source": "从 {list(CHANNELS)} 中选最应由该通道回答的"\n'
        "}\n"
        f"商品名：{item}\n"
        f"说明书文本：{content}"
    )


def build_golden_record(
    chunk: Dict[str, Any],
    synthesized: Dict[str, Any],
    hard_negatives: Sequence[str],
    near_dupes: Sequence[str],
    *,
    qid: str,
) -> Dict[str, Any]:
    """把真实 chunk + LLM 合成结果组装成一条 golden（relevant=真实 chunk_id，直接可计分）。"""
    real_id = str(chunk.get("chunk_id"))
    query = str(synthesized.get("query", "")).strip()
    tag = synthesized.get("tag") if synthesized.get("tag") in TAGS else guess_tag(query)
    channel = synthesized.get("expected_source")
    expected_source = channel if channel in CHANNELS else derive_expected_source(chunk, query)
    grade = {real_id: 2}
    for hn in hard_negatives:
        grade.setdefault(str(hn), 0)
    return {
        "qid": qid,
        "query": query,
        "item_name": chunk.get("item_name", ""),
        "relevant_chunk_ids": [real_id],
        "grade": grade,
        "hard_negative_ids": [str(x) for x in hard_negatives],
        "near_duplicate_ids": [str(x) for x in near_dupes],
        "expected_source": expected_source,
        "reference_answer": str(synthesized.get("reference_answer", "")).strip(),
        "tags": [tag],
    }


def render_audit(records: Sequence[Dict[str, Any]], sample: int, seed: int = 0) -> str:
    """随机抽 sample 条导出人工复核表（诚实口径：LLM 自举须人工抽检确认后方可当基准）。"""
    pool = list(records)
    rng = random.Random(seed)
    picked = rng.sample(pool, min(sample, len(pool))) if pool else []
    lines = [
        "# golden 人工抽检表（LLM 自举，须复核）",
        "",
        f"- 总条数：{len(records)}；抽样：{len(picked)}（seed={seed}）",
        "- 复核要点：query 是否真由该 chunk 可答 / reference_answer 有无编造 / tag、expected_source 是否合理。",
        "- **确认全部无误后**，`golden_queries.real.jsonl` 才可作为回归门禁基准（spec.md §1.1）。",
        "",
        "| qid | query | reference_answer | tag | expected_source | relevant_ids | hard_negatives |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in picked:
        q = _esc(r.get("query"))
        a = _esc(r.get("reference_answer"))
        lines.append(
            f"| {r.get('qid')} | {q} | {a} | {','.join(r.get('tags') or [])} | "
            f"{r.get('expected_source')} | {','.join(r.get('relevant_chunk_ids') or [])} | "
            f"{','.join(r.get('hard_negative_ids') or [])} |"
        )
    return "\n".join(lines) + "\n"


def _esc(s: Any) -> str:
    return str(s or "").replace("|", "\\|").replace("\n", " ")


# ---------------------------------------------------------------------------
# 环境相关（延迟导入，保证 --help / --dry-run 不拉起重型依赖）
# ---------------------------------------------------------------------------
def _load_live_deps() -> Dict[str, Any]:
    from knowledge_service.clients.milvus_utils import get_milvus_client
    from knowledge_service.conf.milvus_config import milvus_config
    from knowledge_service.lm.lm_utils import get_llm_client

    return {
        "get_milvus_client": get_milvus_client,
        "milvus_config": milvus_config,
        "get_llm_client": get_llm_client,
    }


def fetch_real_chunks(client, collection: str, limit: int) -> List[Dict[str, Any]]:
    """从集合拉真实 chunk（chunk_id / content / item_name）。空集合返回 []。"""
    rows = client.query(
        collection_name=collection,
        filter="",
        output_fields=["chunk_id", "content", "item_name"],
        limit=limit,
    )
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        cid = r.get("chunk_id")
        content = r.get("content")
        if cid is None or not content:
            continue
        out.append({"chunk_id": str(cid), "content": str(content), "item_name": str(r.get("item_name") or "")})
    return out


def synthesize_record(chunk: Dict[str, Any], llm, pool: Sequence[Dict[str, Any]], qid: str) -> Dict[str, Any]:
    """调 LLM 基于真实 chunk 合成 → 解析 → 组装 golden 记录（异常由调用方捕获计 skip）。"""
    resp = llm.invoke(synthesis_prompt(chunk))
    raw = getattr(resp, "content", resp)
    synthesized = parse_llm_json(raw if isinstance(raw, str) else str(raw))
    hn = select_hard_negatives(chunk, pool)
    nd = detect_near_dupes(chunk, pool)
    return build_golden_record(chunk, synthesized, hn, nd, qid=qid)


def load_chunks_file(path: Path) -> List[Dict[str, Any]]:
    """离线导入真实 chunk（--from-chunks）：jsonl，每行 {chunk_id, content, item_name}。"""
    out: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            d = json.loads(s)
            out.append({"chunk_id": str(d["chunk_id"]), "content": d["content"], "item_name": d.get("item_name", "")})
    return out


def write_jsonl(path: Path, records: Sequence[Dict[str, Any]]) -> None:
    header = (
        "# ============================================================================\n"
        "# 真实语料自举 golden（gen_golden.py 自动生成，relevant=真实 Milvus chunk_id）\n"
        "# LLM 基于真实 chunk 合成 query/reference_answer + 干扰块标注；须人工抽检（见 golden_audit.md）。\n"
        "# 请勿手工编辑；重生成：python eval/gen_golden.py\n"
        "# ==========================================================================="
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + "\n")
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="真实语料自举 golden：读 Milvus 真实 chunk → LLM 合成 query → 回注真实 chunk_id + 干扰标注。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--collection", default=os.environ.get("CHUNKS_COLLECTION", EVAL_COLLECTION_NAME),
                        help="读取真实 chunk 的集合（默认生产说明书集合需显式指定）")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="golden 输出路径")
    parser.add_argument("--audit-out", default=str(DEFAULT_AUDIT), help="人工抽检表输出路径")
    parser.add_argument("--target-count", type=int, default=120, help="目标 golden 条数")
    parser.add_argument("--chunk-scan-limit", type=int, default=2000, help="从集合最多扫描的真实 chunk 数")
    parser.add_argument("--audit", type=int, default=30, help="抽检表抽样条数（0=不产出抽检表）")
    parser.add_argument("--seed", type=int, default=0, help="抽样/打乱随机种子（可复现）")
    parser.add_argument("--dry-run", action="store_true",
                        help="不连 Milvus/LLM，仅用 --from-chunks（若有）核对标注构造逻辑")
    parser.add_argument("--from-chunks", default=None,
                        help="离线真实 chunk jsonl（配合 --dry-run 无需 Milvus）")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    # ---------- 离线核对（不连 Milvus/LLM）：只验证标注构造，不产出可计分 golden ----------
    if args.dry_run:
        if not args.from_chunks:
            print("[dry-run] 未提供 --from-chunks，仅演示纯函数标注逻辑（自洽样例）...", file=sys.stderr)
            demo = [
                {"chunk_id": "1", "content": "HAK 180 烫金机额定电压 220V，功率 1.5kW。", "item_name": "HAK 180 烫金机"},
                {"chunk_id": "2", "content": "HAK 180 烫金机额定电压为 220V 交流。", "item_name": "HAK 180 烫金机"},
                {"chunk_id": "3", "content": "万用表 RS-12 量程切换：旋转档位开关至目标档。", "item_name": "万用表RS-12"},
            ]
            hn = select_hard_negatives(demo[0], demo)
            nd = detect_near_dupes(demo[0], demo)
            rec = build_golden_record(
                demo[0], {"query": "HAK180额定电压多少", "reference_answer": "220V", "tag": "参数查询"},
                hn, nd, qid="demo001",
            )
            print("[dry-run] 构造样例：", json.dumps(rec, ensure_ascii=False))
            return 0
        chunks = load_chunks_file(Path(args.from_chunks))
        if len(chunks) < 2:
            print(f"错误：--from-chunks 真实 chunk 不足（{len(chunks)} 条），无法构造干扰集。", file=sys.stderr)
            return 1
        print(f"[dry-run] 载入真实 chunk {len(chunks)} 条；下面标注每条的干扰/近似块与 expected_source（未经 LLM 合成 query）：")
        for c in chunks[: args.target_count]:
            hn = select_hard_negatives(c, chunks)
            nd = detect_near_dupes(c, chunks)
            print(f"[dry-run] chunk={c['chunk_id']} item={c['item_name']} "
                  f"hard_neg={len(hn)} near_dupe={len(nd)} exp_src={derive_expected_source(c, c['content'])}")
        return 0

    # ---------- live：需 Milvus + LLM ----------
    deps = _load_live_deps()
    collection = args.collection
    client = deps["get_milvus_client"]()
    if client is None:
        print(f"错误：无法连接 Milvus，无法读取真实 chunk（集合 {collection}）。", file=sys.stderr)
        return 1
    if not client.has_collection(collection_name=collection):
        print(f"错误：集合 {collection} 不存在。真实语料自举须指向已入库真实文档的集合。", file=sys.stderr)
        return 1

    chunks = fetch_real_chunks(client, collection, args.chunk_scan_limit)
    if len(chunks) < args.target_count:
        print(
            f"错误：集合 {collection} 仅 {len(chunks)} 条真实 chunk，少于 target-count={args.target_count}。"
            "请先导入真实文档（node_import_milvus）再自举——绝不回退内嵌-query 玩具语料（否则饱和未解）。",
            file=sys.stderr,
        )
        return 1

    rng = random.Random(args.seed)
    rng.shuffle(chunks)
    pool = chunks
    llm = deps["get_llm_client"](json_mode=True)

    records: List[Dict[str, Any]] = []
    failures = 0
    for idx, chunk in enumerate(pool, start=1):
        if len(records) >= args.target_count:
            break
        try:
            rec = synthesize_record(chunk, llm, pool, qid=f"g{idx:03d}")
        except Exception as e:  # noqa: BLE001 —— 单条 LLM 合成/解析失败计 skip 并继续，不阻断整体、不猜值
            failures += 1
            print(f"[gen] #{idx} chunk={chunk['chunk_id']} 合成失败跳过：{e}", file=sys.stderr)
            continue
        if not rec["query"]:
            failures += 1
            continue
        records.append(rec)
        if idx % 10 == 0:
            print(f"[gen] 已产出 {len(records)}/{args.target_count} 条（失败 {failures}）")

    if not records:
        print("错误：无一条 golden 成功自举（检查 LLM key / 输出格式）。不写空文件。", file=sys.stderr)
        return 1

    write_jsonl(Path(args.out), records)
    print(f"[gen] 完成：写出真实语料 golden {len(records)} 条 → {args.out}（失败跳过 {failures}）")
    if args.audit > 0:
        Path(args.audit_out).write_text(render_audit(records, args.audit, args.seed), encoding="utf-8")
        print(f"[gen] 人工抽检表 → {args.audit_out}（抽 {min(args.audit, len(records))} 条；确认后方可作门禁基准）")
    print("[gen] 下一步：python eval/run_route_ablation.py --golden " + str(args.out) + " --with-contrib")
    return 0


if __name__ == "__main__":
    sys.exit(main())
