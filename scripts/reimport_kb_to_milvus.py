# -*- coding: utf-8 -*-
"""PUBLISHED 文档切片从旧 Milvus 集合搬到新集合（plan-knowledge-base-model 步骤 3 / P2 重灌）。

背景：集合 schema 升 v2（+knowledge_id/workspace_id）再升 v3（+status 软删除字段），
Milvus 不支持给已有集合加字段 ⇒ 换集合名（platform_doc_v2_bge_m3 → platform_doc_v3_bge_m3）。
登记表（kb_documents）里已是 PUBLISHED 的文档，其切片还在旧集合；重灌 = 把切片搬到新集合，
补 status 字段，使新集合成为可按 knowledge_id/status 过滤的完整检索面。

为什么不用 KS /reimport（原实现 2026-11-18 修正）：/reimport 走 VALID_TRANSITIONS 合法迁移，
PUBLISHED→PUBLISHED 被拒（400 非法迁移）——重灌的目标文档本就是 PUBLISHED，触发不了。
且向量无需重算（dense 1024 维 / sparse 两集合同口径），直接搬切片即可。

行为：
- 不带 --yes = dry-run：列清单 + 两集合的现存切片数，零写操作（默认安全态）；
- --yes：对每个 PUBLISHED knowledge_id：从 src 读切片 → 删 dst 中同 knowledge_id 的旧切片
  （幂等）→ 补 status 字段后写入 dst；
- 租户：搬运用 pymilvus 直连（ Milvus 侧标量 tenant_id 随切片原样保留，不改归属）；
- 退出码：dry-run 成功 0；任一失败非 0（可对失败子集重跑）。

用法（在能连 milvus 的环境，如平台 Pod）::
    python scripts/reimport_kb_to_milvus.py --milvus-uri http://milvus:19530 --yes
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Any

# 默认集合名与 agent_runtime.document_store / KS milvus_config 对齐
DEFAULT_SRC = "platform_doc_v2_bge_m3"
DEFAULT_DST = "platform_doc_v3_bge_m3"
# v3 schema 的标量字段（从 v2 搬运时逐字段复制；chunk_id 主键不复制，让目标 auto_id 生成）
_SCALAR_FIELDS = (
    "content", "title", "parent_title", "part", "file_title", "item_name",
    "tenant_id", "scope_type", "knowledge_id", "workspace_id",
    "embedding_model", "chunk_version", "created_at", "source_doc",
    "sparse_vector", "dense_vector",
)


def _client(uri: str) -> Any:
    from pymilvus import MilvusClient
    return MilvusClient(uri=uri)


def list_collections(uri: str) -> list[str]:
    return _client(uri).list_collections()


def count_by_knowledge(uri: str, collection: str, knowledge_id: str) -> int:
    """查某集合里某 knowledge_id 的切片数（dst 幂等用）。"""
    c = _client(uri)
    if not c.has_collection(collection):
        return 0
    res = c.query(collection_name=collection, filter=f'knowledge_id == "{knowledge_id}"',
                  output_fields=["knowledge_id"], limit=16384)
    return len(res or [])


def published_knowledge_ids(uri: str, collection: str) -> list[str]:
    """从旧集合里取所有 PUBLISHED / 非空 knowledge_id 的去重列表。"""
    c = _client(uri)
    if not c.has_collection(collection):
        return []
    rows = c.query(collection_name=collection, filter='knowledge_id != ""',
                   output_fields=["knowledge_id", "status"], limit=16384)
    return sorted({str(r["knowledge_id"]) for r in (rows or [])
                   if str(r.get("knowledge_id") or "").strip()
                   and str(r.get("status") or "PUBLISHED").upper() != "REVOKED"})


def reimport_one(uri: str, kid: str, src: str, dst: str) -> tuple[int, int]:
    """搬一个 knowledge_id：从 src 读切片 → 删 dst 旧切片 → 补 status 写 dst。返回 (读, 写)。"""
    c = _client(uri)
    if not c.has_collection(src):
        raise RuntimeError(f"源集合不存在: {src}")
    if not c.has_collection(dst):
        raise RuntimeError(f"目标集合不存在: {dst}（应由 KS 首次上传自动创建）")
    rows = c.query(collection_name=src, filter=f'knowledge_id == "{kid}"',
                   output_fields=list(_SCALAR_FIELDS), limit=16384)
    if not rows:
        return (0, 0)
    # 幂等：先删 dst 中同 knowledge_id 的旧切片
    c.delete(collection_name=dst, filter=f'knowledge_id == "{kid}"')
    to_insert = []
    for r in rows:
        item = {k: r[k] for k in _SCALAR_FIELDS if k in r}
        item["status"] = str(r.get("status") or "PUBLISHED")  # 补 v3 字段；老数据缺省 PUBLISHED
        if str(item.get("status") or "").upper() != "PUBLISHED":
            item["status"] = "PUBLISHED"
        to_insert.append(item)
    c.insert(collection_name=dst, data=to_insert)
    return (len(rows), len(to_insert))


def main() -> int:
    ap = argparse.ArgumentParser(description="PUBLISHED 切片搬迁到新 Milvus 集合（默认 dry-run）")
    ap.add_argument("--milvus-uri", required=True, help="Milvus 连接串，如 http://milvus:19530")
    ap.add_argument("--src", default=DEFAULT_SRC, help=f"源集合（默认 {DEFAULT_SRC}）")
    ap.add_argument("--dst", default=DEFAULT_DST, help=f"目标集合（默认 {DEFAULT_DST}）")
    ap.add_argument("--interval", type=float, default=1.0, help="每个 knowledge_id 间隔秒数")
    ap.add_argument("--yes", action="store_true", help="真实执行（缺省 = dry-run）")
    args = ap.parse_args()

    try:
        cols = list_collections(args.milvus_uri)
        print(f"[collections] {cols}", flush=True)
        if args.src not in cols:
            print(f"[FAIL] 源集合不存在: {args.src}", file=sys.stderr)
            return 2
        if args.dst not in cols:
            print(f"[FAIL] 目标集合不存在: {args.dst}", file=sys.stderr)
            return 2
        kids = published_knowledge_ids(args.milvus_uri, args.src)
    except Exception as e:  # noqa: BLE001 — 运维脚本顶层出口
        print(f"[FAIL] 读取集合失败: {e}", file=sys.stderr)
        return 1

    print(f"[plan] 源集合 {args.src} 中待搬的 PUBLISHED knowledge_id 共 {len(kids)} 条：")
    for kid in kids:
        n = count_by_knowledge(args.milvus_uri, args.src, kid)
        print(f"  - {kid}  ({n} 切片)")

    if not args.yes:
        print("[dry-run] 未传 --yes，零写操作结束。")
        return 0

    failed: list[str] = []
    total_written = 0
    for i, kid in enumerate(kids, start=1):
        print(f"[{i}/{len(kids)}] reimport {kid} ...", flush=True)
        try:
            read_n, write_n = reimport_one(args.milvus_uri, kid, args.src, args.dst)
            total_written += write_n
            print(f"  [ok] {read_n} -> {write_n} 切片", flush=True)
        except Exception as e:  # noqa: BLE001 — 单条失败不断批（幂等可重跑）
            failed.append(kid)
            print(f"  [FAIL] {kid}: {e}", file=sys.stderr)
        if i < len(kids):
            time.sleep(args.interval)

    if failed:
        print(f"[FAIL] {len(failed)} 条失败（可对失败子集重跑，幂等）：{failed}", file=sys.stderr)
        return 1
    print(f"[done] 全部重灌完成，共写入 {total_written} 切片。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
