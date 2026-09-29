# -*- coding: utf-8 -*-
"""
合成语料 seed + 真实 chunk_id 回填标注（路线消融前置，方案「实施步骤 §2」）。

背景（关键障碍）：现有 `eval/golden_queries.jsonl` 的 `relevant_chunk_ids` 为假设标注
（`c_101` 等），而 Milvus `chunk_id` 是 `auto_id=True` 自增主键。不重标注则所有检索指标
恒为 0，路线消融无从测起。本脚本把「构造样例」变成「可对真实索引计分的标注」：

流程：
    1. 读 golden → 按 `relevant_chunk_ids` 里出现的每个唯一 `chunk_key` 生成一条合成 chunk，
       content 内嵌引用它的那些 query 文本（保证 dense+sparse 都能 lexical/语义命中）。
    2. 对全部 content 生成 dense+sparse 向量 → 走 **线上同一入库节点** `node_import_milvus`
       写入（自动建 schema + 幂等清理 + 主键回填），不另写一套入库逻辑。
    3. 从回填后的 chunk 读取 `chunk_key → 真实 chunk_id` 映射。
    4. 重写 golden 为 `golden_queries.labeled.jsonl`（保留原件），把 `c_xxx` → 真实 chunk_id，
       grade 分级键同步迁移。

隔离与安全：
    - 默认写入**专用集合** `eval.ablation.EVAL_COLLECTION_NAME`（未显式设置 CHUNKS_COLLECTION
      时 setdefault 生效），与生产集合隔离——因为 `node_import_milvus` 会按 item_name 幂等
      清理旧数据，若打到生产集合会误删真实语料。
    - **不改动任何线上代码**，仅调用既有节点。

诚实声明：合成语料为构造样例，content 非真实说明书原文；本脚本不预填任何评测数字，
只做「入库 + 反查真实 chunk_id + 重标注」，指标由 `run_route_ablation.py` 实测。

用法：
    python eval/seed_synthetic_corpus.py [--golden eval/golden_queries.jsonl]
                                         [--out-labeled eval/golden_queries.labeled.jsonl]
                                         [--dry-run]

    --dry-run  只解析 golden 生成合成语料并打印将写入的 chunk（不连 Milvus / 不生成向量），
               用于离线核对语料构造；正式标注需连 Milvus 去掉 --dry-run。

环境要求：Milvus 可达（写入目标集合）+ embedding 可用（local BGE-M3 或 api 模式）。
不满足时打印清晰错误并以非 0 退出（不吞异常、不伪造映射）。
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# 脚本直跑路径引导：`python eval/seed_synthetic_corpus.py` 时把项目根加入 sys.path，
# 使 `knowledge_service.*` 与 `eval.*` 可导入（uv run / 已安装 editable 包时此步为 no-op）。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 纯 stdlib 依赖，可早导入（供 --help / setdefault 用）。
from eval.ablation import EVAL_COLLECTION_NAME, fallback_config_hash  # noqa: E402

# 集合隔离必须在任何 knowledge_service.* 导入前生效（milvus_config 在导入时读 env）。
os.environ.setdefault("CHUNKS_COLLECTION", EVAL_COLLECTION_NAME)

DEFAULT_GOLDEN: Path = Path(__file__).resolve().parent / "golden_queries.jsonl"
DEFAULT_LABELED: Path = Path(__file__).resolve().parent / "golden_queries.labeled.jsonl"
# KG 侧 sidecar：`kg::{item_name}::{name}` → canonical（Milvus 真实 chunk_id）映射，供 runner 归一。
DEFAULT_KG_MAP: Path = Path(__file__).resolve().parent / "kg_id_map.json"
# 合成实体命名空间前缀（区别于生产图谱实体）+ eval 隔离 tag（seed 幂等清理仅按此 tag）。
_KG_ENTITY_PREFIX = "evalsyn::"
_KG_EVAL_TAG = "route_ablation"

# 合成语料的生命周期/租户元数据（满足 node_import_milvus 的 PUBLISHED 发布门禁；
# 检索侧 retrieve_one 不传 tenant/scope，过滤退化为仅 item_name，故这里的租户值不影响召回）。
_LIFECYCLE_STATE: Dict[str, Any] = {
    "status": "PUBLISHED",
    "knowledge_id": "eval_synthetic_kb",
    "tenant_id": "eval_tenant",
    "scope_type": "PUBLIC",
    "authority": "vendor-manual",
    "effective_from": "2020-01-01",
    "effective_to": "2099-12-31",
    "exhibition_id": "eval_exhibition",
}


# ---------------------------------------------------------------------------
# golden 加载（与 run_eval 同口径：跳过 # 注释行；此处独立实现避免在模块顶层
# 触发 run_eval 的重型 import，便于 --help 与 --dry-run）
# ---------------------------------------------------------------------------
def load_golden(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"golden 数据集不存在：{path}")
    queries: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                queries.append(json.loads(stripped))
            except json.JSONDecodeError as e:
                raise json.JSONDecodeError(
                    f"{path}:{line_no} JSON 解析失败: {e.msg}", e.doc, e.pos
                ) from e
    return queries


# ---------------------------------------------------------------------------
# 合成语料构造（数据驱动：不手写 43 条内容，按 label→引用它的 queries 生成）
# ---------------------------------------------------------------------------
def build_corpus(queries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    从 golden 的唯一 `chunk_key` 构造合成 chunk 规格。

    返回：[{chunk_key, item_name, queries: [...], content}, ...]，按 chunk_key 升序，
    保证多次运行产出稳定（幂等）。
    """
    label_q: Dict[str, List[str]] = {}
    label_item: Dict[str, str] = {}
    for item in queries:
        item_name = item.get("item_name", "")
        query = item.get("query", "")
        for chunk_key in item.get("relevant_chunk_ids") or []:
            chunk_key = str(chunk_key)
            label_q.setdefault(chunk_key, [])
            if query and query not in label_q[chunk_key]:
                label_q[chunk_key].append(query)
            label_item.setdefault(chunk_key, item_name)

    corpus: List[Dict[str, Any]] = []
    for chunk_key in sorted(label_q):
        item_name = label_item.get(chunk_key, "")
        qs = label_q[chunk_key]
        qblock = "；".join(qs) if qs else item_name
        content = (
            f"{item_name}相关说明。用户常问：{qblock}。"
            f"本节汇总该{item_name}对应的参数/操作/故障排查要点，"
            f"具体规格与步骤以官方随机说明书为准。"
        )
        corpus.append(
            {
                "chunk_key": chunk_key,
                "item_name": item_name,
                "queries": qs,
                "content": content,
            }
        )
    return corpus


def _load_heavy_deps():
    """延迟加载重型依赖（embedding / 入库节点 / 归一化 / tracing）。"""
    try:
        from knowledge_service.conf.config_hash import compute_config_hash
    except ModuleNotFoundError:
        # 部署镜像落后于工作树、缺 conf/config_hash；仅作 tracing 归因标签，降级不阻断入库。
        compute_config_hash = fallback_config_hash
    from knowledge_service.core.tracing import init_tracing
    from knowledge_service.import_process.agent.nodes.node_import_milvus import node_import_milvus
    from knowledge_service.lm.embedding_utils import generate_embeddings
    from knowledge_service.utils.item_name_normalize_utils import normalize_item_name

    return {
        "generate_embeddings": generate_embeddings,
        "node_import_milvus": node_import_milvus,
        "normalize_item_name": normalize_item_name,
        "compute_config_hash": compute_config_hash,
        "init_tracing": init_tracing,
    }


# ---------------------------------------------------------------------------
# 重标注：c_xxx → 真实 chunk_id
# ---------------------------------------------------------------------------
def relabel_golden(
    queries: List[Dict[str, Any]],
    mapping: Dict[str, str],
) -> List[Dict[str, Any]]:
    """
    用 `chunk_key → 真实 chunk_id` 映射重写每条 query 的 relevant_chunk_ids / grade。

    仅当某 query 的**全部** label 都能映射成功时才计入（否则该 query 跳过并告警，
    避免半标注污染指标）。返回重标注后的 query 列表。
    """
    relabeled: List[Dict[str, Any]] = []
    for item in queries:
        labels = [str(x) for x in (item.get("relevant_chunk_ids") or [])]
        if not labels:
            continue
        missing = [lb for lb in labels if lb not in mapping]
        if missing:
            print(
                f"[seed] 跳过 {item.get('qid', '?')}：label 无对应真实 chunk_id：{missing}",
                file=sys.stderr,
            )
            continue
        new_item = dict(item)
        new_item["relevant_chunk_ids"] = [mapping[lb] for lb in labels]
        # grade 键同步迁移（原键为 c_xxx，值为分级）
        old_grade = item.get("grade") or {}
        new_grade: Dict[str, Any] = {}
        for lb, g in old_grade.items():
            if str(lb) in mapping:
                new_grade[mapping[str(lb)]] = g
        new_item["grade"] = new_grade
        relabeled.append(new_item)
    return relabeled


_LABELED_HEADER = """# ============================================================================
# 路线消融 golden（合成语料真实 chunk_id 标注版，seed_synthetic_corpus.py 自动生成）
# 由 golden_queries.jsonl（c_xxx 假设标注）+ Milvus 真实 chunk_id 映射重写而来。
# relevant_chunk_ids / grade 键均为**真实 chunk_id**，可直接对 eval_rag_routes 集合计分。
# 诚实声明：语料为构造样例，结果仅供路线/向量级消融的定性方向判断，非线上指标。
# 请勿手工编辑本文件；重新生成：python eval/seed_synthetic_corpus.py
# =========================================================================="""


def write_labeled(path: Path, relabeled: List[Dict[str, Any]]) -> None:
    lines = [_LABELED_HEADER]
    for item in relabeled:
        lines.append(json.dumps(item, ensure_ascii=False))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# KG 侧 seed（--with-kg）：写 Neo4j Entity + 产出 kg_id_map.json（canonical 别名用）
# ---------------------------------------------------------------------------
def _kg_entity_id(item_name: str, name: str) -> str:
    """复刻 neo4j_utils.query_kg 合成的 chunk_id 形状：`kg::{item_name}::{name}`。"""
    return f"kg::{item_name}::{name}"


def seed_neo4j_entities(corpus: List[Dict[str, Any]], mapping: Dict[str, str]) -> Dict[str, str]:
    """把每个 chunk_key 写成 Neo4j `Entity`（供线上同一 node_query_kg 检索），
    并返回 `kg::{item}::{name}` → canonical（Milvus 真实 chunk_id）的别名映射。

    契约对齐（据 neo4j_utils.query_kg）：
      - 过滤 `e.item_name IN $item_names` 用**原始** golden item_name（query_kg 不做归一化）；
      - 命中 `toLower(e.content) CONTAINS toLower($q)` → content 复用内嵌 query 的同一文本；
      - query_kg 合成 chunk_id = `kg::{e.item_name}::{e.name}` → 以此拼 sidecar 键。

    隔离：Entity 带 eval_tag；开跑先按该 tag DETACH DELETE（幂等），**绝不碰生产其它实体**。
    依赖 neo4j 驱动（镜像默认未装，需 pip install neo4j）；不可用时抛错由调用方处理，不伪造映射。
    """
    from knowledge_service.clients.neo4j_utils import get_neo4j_driver

    driver = get_neo4j_driver()
    if driver is None:
        raise RuntimeError(
            "Neo4j 驱动不可用（未装 neo4j 包 或 NEO4J_URI/USERNAME/PASSWORD 未配）。"
            "KG seed 需容器内 pip install neo4j 且配好连接；勿伪造映射。"
        )
    db = os.getenv("NEO4J_DATABASE", "neo4j")
    kg_map: Dict[str, str] = {}
    with driver.session(database=db) as session:
        # 幂等清理：仅删本 eval 之前写入的实体（按 eval_tag），不触碰生产图谱其它节点。
        session.run("MATCH (e:Entity {eval_tag: $tag}) DETACH DELETE e", tag=_KG_EVAL_TAG)
        for spec in corpus:
            ck = str(spec["chunk_key"])
            canon = mapping.get(ck)
            item_raw = spec["item_name"]           # 原始 golden item_name（query_kg 精确 IN）
            name = f"{_KG_ENTITY_PREFIX}{ck}"       # 确定性 name → kg id 可复算
            session.run(
                "MERGE (e:Entity {eval_tag: $tag, item_name: $item, name: $name}) "
                "ON CREATE SET e.content = $content, e.tenant_id = $tenant, "
                "            e.scope_type = $scope, e.source = 'route_ablation_eval' "
                "ON MATCH  SET e.content = $content",
                tag=_KG_EVAL_TAG, item=item_raw, name=name, content=spec["content"],
                tenant=_LIFECYCLE_STATE["tenant_id"], scope=_LIFECYCLE_STATE["scope_type"],
            )
            if canon:
                kg_map[_kg_entity_id(item_raw, name)] = str(canon)
    return kg_map


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="路线消融前置：把合成语料写入专用 Milvus 集合并按真实 chunk_id 重标注 golden。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--golden", default=str(DEFAULT_GOLDEN), help="原始 golden 数据集路径")
    parser.add_argument("--out-labeled", default=str(DEFAULT_LABELED), help="重标注后 golden 输出路径")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只解析 golden 构造合成语料并打印，不连 Milvus / 不生成向量 / 不写文件",
    )
    parser.add_argument(
        "--with-kg",
        action="store_true",
        help="额外把合成语料写入 Neo4j Entity（eval_tag 隔离）+ 生成 kg_id_map.json，使 KG 路可计分",
    )
    parser.add_argument("--kg-map", default=str(DEFAULT_KG_MAP), help="KG sidecar 映射输出路径（--with-kg 时生效）")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    golden_path = Path(args.golden)
    out_labeled = Path(args.out_labeled)

    queries = load_golden(golden_path)
    if not queries:
        print(f"错误：golden 数据集 {golden_path} 无有效 query。", file=sys.stderr)
        return 1

    corpus = build_corpus(queries)
    print(f"[seed] golden {len(queries)} 条 → 合成 chunk {len(corpus)} 条（唯一 chunk_key）")
    print(f"[seed] 目标集合：{os.environ.get('CHUNKS_COLLECTION')}")

    # ---------- dry-run：仅核对语料构造 ----------
    if args.dry_run:
        for spec in corpus:
            print(f"[dry-run] chunk_key={spec['chunk_key']} item={spec['item_name']} "
                  f"refs={len(spec['queries'])} content={spec['content'][:40]}...")
        print(f"[dry-run] 共 {len(corpus)} 条合成 chunk（未连 Milvus，未生成向量，未写文件）")
        return 0

    # ---------- 正式：生成向量 + 线上节点入库 + 回填真实 chunk_id ----------
    deps = _load_heavy_deps()
    generate_embeddings = deps["generate_embeddings"]
    node_import_milvus = deps["node_import_milvus"]
    normalize_item_name = deps["normalize_item_name"]

    texts = [spec["content"] for spec in corpus]
    print(f"[seed] 生成 dense+sparse 向量：{len(texts)} 条文本 ...")
    emb = generate_embeddings(texts)
    dense_list = emb.get("dense")
    sparse_list = emb.get("sparse")

    chunks: List[Dict[str, Any]] = []
    for idx, spec in enumerate(corpus):
        chunks.append(
            {
                "content": spec["content"],
                "title": f"{spec['item_name']} 合成条目",
                "parent_title": "eval_synthetic.md",
                "part": idx,
                "file_title": "eval_synthetic.md",
                # 存 normalize 后的 item_name，与检索侧 build_retrieval_filter 归一口径一致
                "item_name": normalize_item_name(spec["item_name"]),
                # 不写入自定义字段（chunk_key）：部署镜像建的集合未 enable dynamic field，
                # 多余字段会被 insert 拒绝；chunk_key → chunk_id 靠下方**回填顺序**关联。
                "dense_vector": dense_list[idx],
                "sparse_vector": sparse_list[idx],
            }
        )

    state: Dict[str, Any] = {"task_id": "eval_seed_synthetic", "chunks": chunks}
    state.update(_LIFECYCLE_STATE)

    # tracing 幂等初始化（未配置 endpoint 时 no-op，与 run_eval 一致）
    try:
        deps["init_tracing"](
            config_hash=deps["compute_config_hash"](),
            collection=os.environ.get("CHUNKS_COLLECTION", EVAL_COLLECTION_NAME),
        )
    except Exception as e:  # noqa: BLE001 —— tracing 初始化失败不应阻断入库（可选可观测能力）
        print(f"[seed] tracing 初始化跳过：{e}", file=sys.stderr)

    print(f"[seed] 调用 node_import_milvus 入库 {len(chunks)} 条 ...")
    result = node_import_milvus(state)
    imported = result.get("chunks") or []

    # 关联 chunk_key → 真实 chunk_id：node_import_milvus.step_4 按**列表顺序**回填 chunk_id
    # （chunks_json_data[idx]["chunk_id"] = inserted_ids[idx]），故用 corpus 顺序 zip 回填结果，
    # 不依赖 Milvus 动态字段（部署镜像建的集合未 enable dynamic field，多余字段会被 insert 拒绝）。
    mapping: Dict[str, str] = {}
    if len(imported) != len(corpus):
        print(
            f"错误：入库回填数量({len(imported)})与合成 chunk 数({len(corpus)})不一致，"
            "无法按顺序关联 chunk_key → chunk_id，终止（不伪造映射）。",
            file=sys.stderr,
        )
        return 1
    for spec, chunk in zip(corpus, imported):
        cid = chunk.get("chunk_id")
        if cid:
            mapping[str(spec["chunk_key"])] = str(cid)

    if not mapping:
        print(
            "错误：入库后未取到任何 chunk_id 回填（node_import_milvus 主键回填可能失败）。"
            "请检查 Milvus 连接与集合状态，勿伪造标注。",
            file=sys.stderr,
        )
        return 1

    missing_keys = [spec["chunk_key"] for spec in corpus if spec["chunk_key"] not in mapping]
    print(f"[seed] 回填映射：{len(mapping)}/{len(corpus)} 条 chunk_key → 真实 chunk_id")
    if missing_keys:
        print(f"[seed] 警告：以下 chunk_key 未回填 chunk_id：{missing_keys}", file=sys.stderr)

    relabeled = relabel_golden(queries, mapping)
    if not relabeled:
        print("错误：无任何 query 能完成真实 chunk_id 标注，终止（不写空文件）。", file=sys.stderr)
        return 1

    write_labeled(out_labeled, relabeled)

    # ---------- 可选：KG 侧 seed（写 Neo4j Entity + 产出 canonical 别名映射）----------
    if args.with_kg:
        print("[seed] --with-kg：写入 Neo4j Entity（eval_tag 隔离）+ 生成 KG 别名映射 ...")
        try:
            kg_map = seed_neo4j_entities(corpus, mapping)
        except Exception as e:  # noqa: BLE001 —— KG seed 失败应清晰终止（不伪造映射），交由环境修复后复跑
            print(f"错误：KG seed 失败（不伪造映射）：{e}", file=sys.stderr)
            return 1
        kg_map_path = Path(args.kg_map)
        with open(kg_map_path, "w", encoding="utf-8") as f:
            json.dump(kg_map, f, ensure_ascii=False, indent=2)
        print(f"[seed] KG：写入 {len(kg_map)} 条 Entity 别名 → {kg_map_path}")
        if len(kg_map) != len(corpus):
            print(
                f"[seed] 警告：KG 别名映射({len(kg_map)})少于合成 chunk({len(corpus)}) 条（部分 chunk_key 无 canonical id）。",
                file=sys.stderr,
            )

    print(f"\n[seed] 完成：写出重标注 golden → {out_labeled}（{len(relabeled)} 条）")
    print("[seed] 下一步：python eval/run_route_ablation.py --golden " + str(out_labeled))
    return 0


if __name__ == "__main__":
    sys.exit(main())
