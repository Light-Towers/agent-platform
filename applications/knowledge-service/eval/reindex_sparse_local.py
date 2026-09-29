# -*- coding: utf-8 -*-
"""重算 benchmark 集合稀疏向量为 local BGE-M3（一次性运维修复工具，delete+insert 路线）。

背景与方案：docs/plans/plan-rag-sparse-encoding-consistency-2026-09-29.md
    集合 `product_manual_v1_bge_m3` 曾以 EMBEDDING_MODE=api 导入（稀疏=md5 哈希 id），
    而查询以 local 模式（稀疏=BGE-M3 token id）→ 两 id 空间不相交 → 稀疏路恒空、混合检索
    静默退化为纯 dense（曾致路线消融层 2 权重扫描结论整体作废）。

为何 delete+insert 而非原地 upsert（2026-09-29 126 容器实测）：
    该集合主键 chunk_id 为 auto_id=True 的 Milvus 自增 INT64。auto_id 集合的 upsert 语义 =
    "删原行 + 插入并重新自增主键"，无法把向量写回指定主键（实测原 PK ...472 消失、新 PK ...664 出现）。
    故只能整集重插，随之所有 chunk_id 变化 → **配套用 eval/remap_golden_ids.py 按内容把
    golden_queries.real.jsonl 里的 chunk_id 引用从旧 id 重映射到新 id**（内容不变，审计仍有效）。
    dense_vector 原样保留（api-SiliconFlow 与 local-BGE-M3 同语义空间，dense 侧结果不变），
    仅重算 sparse 对齐 local。

关键约束：
    - 必须在 EMBEDDING_MODE=local 下运行（否则等于用 md5 再写一遍，无意义）；脚本启动即校验并拒绝。
    - 先备份全量（可回滚），再改；产出一份 old→new PK 映射 json 供 remap golden 使用。
    - 不改任何线上检索/入库逻辑，仅调既有 generate_embeddings + MilvusClient.query/insert/delete。

用法（126 容器内，集合已确认存在）：
    EMBEDDING_MODE=local CHUNKS_COLLECTION=product_manual_v1_bge_m3 \
        python eval/reindex_sparse_local.py --dry-run            # 只读全量并备份，不写
    EMBEDDING_MODE=local CHUNKS_COLLECTION=product_manual_v1_bge_m3 \
        python eval/reindex_sparse_local.py --one                # 单行端到端 smoke（删1插1+映射+canary）
    EMBEDDING_MODE=local CHUNKS_COLLECTION=product_manual_v1_bge_m3 \
        python eval/reindex_sparse_local.py --yes                # 全量重插 + 产出 PK 映射 + 校验
    # 之后：python eval/remap_golden_ids.py --map <映射json> --golden eval/golden_queries.real.jsonl
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 集合名在 knowledge_service 导入前生效（milvus_config 导入时读 env）。
os.environ.setdefault("CHUNKS_COLLECTION", "product_manual_v1_bge_m3")

# 重插需要回填的全部 schema 字段（chunk_id 除外，auto_id 重新生成；sparse_vector 本脚本重算）。
_FETCH_FIELDS = [
    "chunk_id",
    "content",
    "title",
    "parent_title",
    "part",
    "file_title",
    "item_name",
    "tenant_id",
    "scope_type",
    "embedding_model",
    "chunk_version",
    "created_at",
    "source_doc",
    "dense_vector",
]


def _load_heavy():
    from knowledge_service.clients.milvus_utils import get_milvus_client
    from knowledge_service.conf.embedding_config import embedding_config
    from knowledge_service.conf.milvus_config import milvus_config
    from knowledge_service.lm.embedding_utils import generate_embeddings
    from knowledge_service.utils.sparse_consistency import (
        assert_sparse_encoding_consistent,
        reset_sparse_consistency_cache,
    )

    return {
        "get_milvus_client": get_milvus_client,
        "milvus_config": milvus_config,
        "embedding_config": embedding_config,
        "generate_embeddings": generate_embeddings,
        "assert_sparse_encoding_consistent": assert_sparse_encoding_consistent,
        "reset_sparse_consistency_cache": reset_sparse_consistency_cache,
    }


def _iter_all(client, collection, output_fields, hard_cap=200000, batch_size=1000):
    """分页读全量行。Milvus 单次 query 窗口上限 16384，故优先用 query_iterator，
    环境不支持时回退单次 query（受 16384 约束）。hard_cap 为总量安全上限。"""
    if hasattr(client, "query_iterator"):
        out: List[Dict[str, Any]] = []
        it = client.query_iterator(
            collection_name=collection,
            filter="chunk_id >= 0",
            batch_size=batch_size,
            output_fields=output_fields,
        )
        try:
            while True:
                page = it.next()
                if not page:
                    break
                out.extend(page)
                if len(out) >= hard_cap:
                    break
        finally:
            it.close()
        return out
    return client.query(
        collection_name=collection,
        filter="chunk_id >= 0",
        limit=min(hard_cap, 16384),
        output_fields=output_fields,
    )


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="重算集合稀疏向量为 local BGE-M3（delete+insert + PK 映射）。")
    p.add_argument("--collection", default=None, help="目标集合名，默认读 CHUNKS_COLLECTION/milvus_config")
    p.add_argument("--backup", default=None, help="备份 jsonl 路径，默认 eval/runs_server/reindex_backup_<ts>.jsonl")
    p.add_argument("--map-out", default=None, help="old→new PK 映射输出路径，默认 eval/runs_server/reindex_pk_map_<ts>.json")
    p.add_argument("--limit", type=int, default=200000, help="读取/处理总量安全上限（迭代器分页，不受单次 16384 窗口限制）")
    p.add_argument("--embed-batch", type=int, default=32, help="generate_embeddings 分批大小")
    p.add_argument("--dry-run", action="store_true", help="只读全量 + 备份，不重算不写")
    p.add_argument("--one", action="store_true", help="单行端到端 smoke：仅删 1 插 1 + 产出 1 条映射 + canary")
    p.add_argument(
        "--from-backup",
        default=None,
        help="以 pristine 备份 jsonl 为源重建（而非读 live 集合）；映射键=备份原始 chunk_id，与 golden 对齐。集合被 --one 漂移过时必用",
    )
    p.add_argument("--yes", action="store_true", help="确认执行全量删重插（缺省将拒绝写入）")
    return p.parse_args(argv)


def _load_rows_from_backup(path: Path) -> List[Dict[str, Any]]:
    """从 pristine 备份 jsonl 读取源行（含原 chunk_id + dense + 各业务字段）。"""
    if not path.exists():
        raise FileNotFoundError(f"备份文件不存在：{path}")
    rows: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    missing = [r.get("chunk_id") for r in rows if "chunk_id" not in r or "dense_vector" not in r]
    if missing:
        raise ValueError(f"备份行缺少 chunk_id/dense_vector，无法重建：{missing[:5]}...")
    return rows


def _delete_all(client, collection, old_ids: List[Any]) -> None:
    """清空集合：优先按 filter 全删（能捕获 --one 漂移出的孤儿行），不支持时回退按 ids 删。"""
    try:
        client.delete(collection_name=collection, filter="chunk_id >= 0")
    except Exception as exc:  # noqa: BLE001 —— filter delete 不可用时回退 ids delete
        print(f"[reindex] filter delete 不可用({type(exc).__name__})，回退按 ids 删除 {len(old_ids)} 行", file=sys.stderr)
        client.delete(collection_name=collection, ids=old_ids)


def _recompute_sparse(generate_embeddings, texts: List[str], batch: int) -> List[Dict[int, float]]:
    sparse_all: List[Dict[int, float]] = []
    bs = max(1, batch)
    for i in range(0, len(texts), bs):
        chunk = texts[i : i + bs]
        sparse_all.extend(generate_embeddings(chunk).get("sparse"))
    return sparse_all


def _build_insert(row: Dict[str, Any], sparse_vec: Dict[int, float]) -> Dict[str, Any]:
    """构造 insert 数据体：剔除 auto 主键 chunk_id，保留原 dense 与各业务字段，替换 sparse。"""
    item = {k: v for k, v in row.items() if k != "chunk_id"}
    item["sparse_vector"] = sparse_vec
    return item


def _extract_insert_ids(res: Any) -> List[Any]:
    """从 MilvusClient.insert 返回体提取新生成的主键列表（保持与 data 同序）。"""
    if isinstance(res, dict):
        ids = res.get("ids")
        if ids is None:
            ids = res.get("primary_kb")
        if ids is None:
            raise RuntimeError(f"insert 返回体无法解析主键列表：keys={list(res.keys())}")
        return list(ids)
    raise RuntimeError(f"insert 返回类型非预期：{type(res)}")


def main(argv=None) -> int:
    args = parse_args(argv)
    heavy = _load_heavy()
    embedding_config = heavy["embedding_config"]
    generate_embeddings = heavy["generate_embeddings"]
    client = heavy["get_milvus_client"]()
    collection = args.collection or heavy["milvus_config"].chunks_collection

    if client is None:
        print("错误：Milvus 客户端连接失败，终止（不写入）。", file=sys.stderr)
        return 1

    # 强制 local：api 下 sparse 仍是 md5，重算无意义。
    if (embedding_config.embedding_mode or "local") != "local":
        print(
            f"错误：当前 EMBEDDING_MODE={embedding_config.embedding_mode!r}，本工具要求 local"
            "（BGE-M3 learned sparse）。请 `export EMBEDDING_MODE=local` 后重跑。终止。",
            file=sys.stderr,
        )
        return 1

    print(f"[reindex] 目标集合：{collection} | EMBEDDING_MODE=local")

    ts = int(time.time())

    # ---------- 1) 取源行：pristine 备份（--from-backup）或 live 集合查询 ----------
    if args.from_backup:
        src_path = Path(args.from_backup)
        rows = _load_rows_from_backup(src_path)
        print(f"[reindex] 源=备份 {src_path}（{len(rows)} 行，含原 chunk_id/dense）")
        # 从备份重建时不再写新备份（src 本身即 pristine 备份）；仍产出 live 快照供回滚对照。
        live_rows = _iter_all(client, collection, _FETCH_FIELDS, hard_cap=args.limit)
        backup_path = _PROJECT_ROOT / "eval" / "runs_server" / f"reindex_live_snapshot_{ts}.jsonl"
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        with open(backup_path, "w", encoding="utf-8") as f:
            for r in live_rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"[reindex] 已快照 live 集合当前 {len(live_rows)} 行（含 --one 漂移）→ {backup_path}")
    else:
        # ---------- 1b) 读 live 全量（含 dense，不含 sparse）并备份 ----------
        rows = _iter_all(client, collection, _FETCH_FIELDS, hard_cap=args.limit)
        if not rows:
            print(f"错误：集合 {collection} 查询为空（集合不存在/未导入/filter 不匹配）。终止。", file=sys.stderr)
            return 1
        if len(rows) >= args.limit:
            print(
                f"警告：返回行数达到 --limit={args.limit} 安全上限，可能有未覆盖数据；请调大 --limit 后重跑（本次仅处理已取到的 {len(rows)} 行）。",
                file=sys.stderr,
            )
        backup_path = Path(args.backup) if args.backup else _PROJECT_ROOT / "eval" / "runs_server" / f"reindex_backup_{ts}.jsonl"
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        with open(backup_path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"[reindex] 已备份 {len(rows)} 行（含 dense，不含旧 sparse）→ {backup_path}")

    if args.dry_run:
        print("[reindex] --dry-run：仅读/备份，未重算未写入。")
        return 0

    target_rows = rows[:1] if args.one else rows
    old_ids = [r["chunk_id"] for r in target_rows]
    contents = [str(r.get("content") or "") for r in target_rows]

    # ---------- 2) 分批重算 local 稀疏（dense 原样保留） ----------
    sparse_list = _recompute_sparse(generate_embeddings, contents, args.embed_batch)
    if len(sparse_list) != len(target_rows):
        print(f"错误：重算稀疏数量({len(sparse_list)})≠目标行({len(target_rows)})，终止（不部分写入）。", file=sys.stderr)
        return 1

    # ---------- 3) 清空集合 + 插新（auto_id 重新生成 PK）→ 产出 old→new 映射 ----------
    if not args.one and not args.yes:
        print(f"错误：全量删重插需显式加 --yes（本次将动 {len(target_rows)} 行）。终止，未改动集合。", file=sys.stderr)
        return 1

    if args.one:
        # smoke：只删这一行再插这一行（--one 不启用 filter 全删，避免误清空整集）。
        client.delete(collection_name=collection, ids=old_ids)
    else:
        _delete_all(client, collection, old_ids)
    if hasattr(client, "flush"):
        try:
            client.flush(collection_name=collection)
        except Exception as exc:  # noqa: BLE001 —— flush best-effort，最终以 query/canary 校验为准
            print(f"[reindex] 警告：delete 后 flush 失败（不致命）：{exc}", file=sys.stderr)

    new_ids: List[Any] = []
    bs = max(1, args.embed_batch)
    for i in range(0, len(target_rows), bs):
        data = [_build_insert(r, sp) for r, sp in zip(target_rows[i : i + bs], sparse_list[i : i + bs])]
        res = client.insert(collection_name=collection, data=data)
        new_ids.extend(_extract_insert_ids(res))
        print(f"[reindex] 重插进度 {len(new_ids)}/{len(target_rows)}")
    if hasattr(client, "flush"):
        try:
            client.flush(collection_name=collection)
        except Exception as exc:  # noqa: BLE001 —— flush best-effort，最终以 query/canary 校验为准
            print(f"[reindex] 警告：insert 后 flush 失败（不致命）：{exc}", file=sys.stderr)

    if len(new_ids) != len(old_ids):
        print(
            f"错误：新插主键数({len(new_ids)})≠原行数({len(old_ids)})，映射不完整，终止（golden 暂不 remap）。"
            f"请用备份 {backup_path} 核对回滚。",
            file=sys.stderr,
        )
        return 1

    pk_map = {str(o): str(n) for o, n in zip(old_ids, new_ids)}
    map_path = Path(args.map_out) if args.map_out else _PROJECT_ROOT / "eval" / "runs_server" / f"reindex_pk_map_{ts}.json"
    map_path.parent.mkdir(parents=True, exist_ok=True)
    with open(map_path, "w", encoding="utf-8") as f:
        json.dump({"collection": collection, "generated_at": ts, "map": pk_map}, f, ensure_ascii=False, indent=2)
    print(f"[reindex] 已产出 old→new PK 映射 {len(pk_map)} 条 → {map_path}")

    # ---------- 4) 校验：canary 通过 + 单路 sparse 探针非空 ----------
    heavy["reset_sparse_consistency_cache"]()
    heavy["assert_sparse_encoding_consistent"](client, collection, embed_sparse=None, use_cache=False)

    sp = generate_embeddings([contents[0]]).get("sparse")[0]
    hits = client.search(
        collection_name=collection, anns_field="sparse_vector", data=[sp], limit=5, output_fields=["chunk_id"]
    )
    top = hits[0][:3] if hits and hits[0] else []
    print(f"[reindex] 完成。单路 sparse 探针 top3：{[(h.get('entity', {}).get('chunk_id') if isinstance(h, dict) else h.get('chunk_id'), h.get('distance')) for h in top]}")
    if args.one:
        print("[reindex] --one smoke 完成（canary 通过）。全量请去掉 --one 并加 --yes，随后用 remap_golden_ids.py 重映射 golden。")
        return 0
    print(f"[reindex] 下一步：python eval/remap_golden_ids.py --map {map_path} --golden eval/golden_queries.real.jsonl")
    print("[reindex] 再复跑 run_route_ablation.py（--golden golden_queries.real.jsonl）与 run_e2e_eval.py 刷新层2/e2e 报告。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
