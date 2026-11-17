# -*- coding: utf-8 -*-
"""KS PUBLISHED 文档重灌进平台共享 Milvus 集合（plan-knowledge-base-model 步骤 3 配套）。

背景：集合 schema 升 v2（新增 knowledge_id / workspace_id 两个字段，两侧镜像见
agent_runtime/document_store.py 与 KS node_import_milvus.create_collection），且平台
默认集合名换为 platform_doc_v2_bge_m3（不复用 product_manual_v1_bge_m3——老集合缺
v2 字段、老数据未分库）。已 PUBLISHED 的登记文档要按新管线重跑一遍，共享集合里
才有可按 knowledge_id 过滤的切片（老数据选库模式不召回）。

用法（**本批不执行**，仅提供；执行属部署/运维动作）::

    python scripts/reimport_kb_to_milvus.py --ks-url http://<ks-host>:8900 [--yes]

行为：
- 不带 ``--yes`` = dry-run：只列出将重灌的 knowledge_id，零写操作（默认安全态）；
- ``--yes`` 才逐个 POST /reimport（status 沿用 PUBLISHED，生命周期字段从登记
  metadata 回带），每次间隔 ``--interval`` 秒（默认 3s）——/reimport 重跑完整
  导入管线，连发会打挂 KS；
- 租户：经 ``agent_runtime.identity.sign_internal_header`` 签 ``X-Internal-Tenant``
  （INTERNAL_HMAC_KEY 必须与 KS 部署一致；KS 侧只认签名头断言，不收表单租户）；
- 退出码：dry-run 成功 0；执行中出现任一失败非 0（幂等：可对失败子集重跑）。
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import httpx
from agent_runtime.identity import sign_internal_header

_DOCS_LIMIT = 100
_REIMPORT_TIMEOUT_S = 300.0


def _internal_headers() -> dict[str, str]:
    """构造 KS 签名头（与 kb_router._internal_headers 同一签名件，不抄第二遍逻辑）。"""
    from agent_runtime.workspace_registry import asserted_user_id

    tenant_id = os.environ.get("REIMPORT_TENANT_ID", "default")
    headers = {"X-Internal-Tenant": sign_internal_header(tenant_id, asserted_user_id())}
    api_key = os.environ.get("KNOWLEDGE_SERVICE_KEY", "")
    if api_key:
        headers["X-API-Key"] = api_key
    return headers


def list_published(ks_url: str) -> list[dict]:
    """拉 KS /documents（updated_at 降序），取 PUBLISHED 且 knowledge_id 非空的条目。"""
    resp = httpx.get(
        f"{ks_url.rstrip('/')}/documents",
        params={"limit": _DOCS_LIMIT},
        headers=_internal_headers(),
        timeout=_REIMPORT_TIMEOUT_S,
    )
    resp.raise_for_status()
    docs = (resp.json() or {}).get("documents") or []
    return [
        d for d in docs
        if str(d.get("knowledge_id") or "").strip()
        and str(d.get("status") or "").upper() == "PUBLISHED"
    ]


def reimport_one(ks_url: str, doc: dict) -> None:
    """对单个 PUBLISHED 文档重跑导入管线（生命周期字段从登记 metadata 回带）。"""
    meta = doc.get("metadata") or {}
    resp = httpx.post(
        f"{ks_url.rstrip('/')}/reimport",
        data={
            "knowledge_id": doc["knowledge_id"],
            "status": "PUBLISHED",
            "authority": str(meta.get("authority", "") or ""),
            "effective_from": str(meta.get("effective_from", "") or ""),
            "effective_to": str(meta.get("effective_to", "") or ""),
        },
        headers=_internal_headers(),
        timeout=_REIMPORT_TIMEOUT_S,
    )
    resp.raise_for_status()


def main() -> int:
    parser = argparse.ArgumentParser(description="PUBLISHED 文档重灌共享 Milvus 集合（默认 dry-run）")
    parser.add_argument("--ks-url", required=True, help="knowledge-service 基址，如 http://<ks-host>:8900")
    parser.add_argument("--interval", type=float, default=3.0, help="两次 /reimport 的间隔秒数（默认 3）")
    parser.add_argument("--yes", action="store_true", help="真实执行（缺省 = dry-run，只列清单）")
    args = parser.parse_args()

    try:
        docs = list_published(args.ks_url)
    except Exception as e:  # noqa: BLE001 — 运维脚本的顶层出口：报原因、给非零退出码
        print(f"[FAIL] 拉取登记列表失败：{e}", file=sys.stderr)
        return 1

    print(f"[plan] PUBLISHED 且已登记的 knowledge_id 共 {len(docs)} 条：")
    for d in docs:
        print(f"  - {d['knowledge_id']}  ({d.get('filename', '?')})")

    if not args.yes:
        print("[dry-run] 未传 --yes，零写操作结束。确认上面清单后加 --yes 执行。")
        return 0

    failed: list[str] = []
    for i, d in enumerate(docs, start=1):
        kid = d["knowledge_id"]
        print(f"[{i}/{len(docs)}] reimport {kid} ...", flush=True)
        try:
            reimport_one(args.ks_url, d)
        except Exception as e:  # noqa: BLE001 — 单条失败不断批（幂等可重跑）
            failed.append(kid)
            print(f"  [FAIL] {kid}: {e}", file=sys.stderr)
        else:
            print("  [ok]")
        if i < len(docs):
            time.sleep(args.interval)

    if failed:
        print(f"[FAIL] {len(failed)} 条失败（可对失败子集重跑，/reimport 幂等）：{failed}", file=sys.stderr)
        return 1
    print("[done] 全部重灌完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
