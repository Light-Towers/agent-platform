# -*- coding: utf-8 -*-
"""
会展知识语料导入脚本。

用法：
    # 首期 5 份（默认）
    python -m knowledge_service.scripts.import_exhibition_corpus --base-url http://192.168.100.126:8000

    # 指定语料目录
    python -m knowledge_service.scripts.import_exhibition_corpus --base-url http://192.168.100.126:8000 --corpus-dir "D:/0-mingyang/文档"

    # dry-run（只打印计划，不实际上传）
    python -m knowledge_service.scripts.import_exhibition_corpus --dry-run

    # 指定单份语料
    python -m knowledge_service.scripts.import_exhibition_corpus --base-url http://192.168.100.126:8000 --files "搭建商手册/2024中国进口博览会搭建商手册.pdf"

功能：
1. 遍历首期 5 份语料（或指定文件）
2. 对每份语料调用 POST /upload（multipart/form-data），传入 metadata
3. 轮询 /status/{task_id} 直到 completed/failed
4. 输出导入报告（成功/失败/耗时）
"""

import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import requests


@dataclass
class CorpusItem:
    """单份语料的元数据描述。"""

    relative_path: str
    authority: str
    effective_from: str = "2025-01-01"
    effective_to: str = ""
    version: str = "v1"
    description: str = ""


@dataclass
class ImportResult:
    """单份语料的导入结果。"""

    relative_path: str
    task_id: str = ""
    status: str = ""
    elapsed_s: float = 0.0
    error: str = ""
    done_list: List[str] = field(default_factory=list)


# 首期 5 份语料（F03 §2 首期建议，覆盖报馆流程+国标+参展协议）
FIRST_BATCH: List[CorpusItem] = [
    CorpusItem(
        relative_path="搭建商手册/2024中国进口博览会搭建商手册.pdf",
        authority="进口博览会组委会",
        description="报馆/搭建流程",
    ),
    CorpusItem(
        relative_path="搭建商手册/【国家会议中心】2021年服贸会展览搭建服务手册2.0版.pdf",
        authority="国家会议中心",
        description="搭建服务手册",
    ),
    CorpusItem(
        relative_path="展会GB标准/GBT+33490-2025展览展示工程服务基本要求.pdf",
        authority="国家标准化管理委员会",
        description="国标：展览展示工程服务基本要求",
    ),
    CorpusItem(
        relative_path="展会GB标准/GBT+30521-2025经济贸易展览会数据统计规则.pdf",
        authority="国家标准化管理委员会",
        description="国标：数据统计规则",
    ),
    CorpusItem(
        relative_path="博博会/0506第十一届博博会参展协议（博物馆）.docx",
        authority="博博会组委会",
        description="参展协议",
    ),
]

# 导入 metadata 常量（首期统一标注）
SCOPE_TYPE = "PUBLIC"
TENANT_ID = "exhibition"
TENANT_TYPE = "enterprise"
STATUS = "PUBLISHED"
ENABLE_ITEM_NAME_RECOGNITION = False
EFFECTIVE_TO = "2099-12-31"
EXHIBITION_ID = "general"

# 轮询配置
POLL_INTERVAL_S = 5
POLL_TIMEOUT_S = 600


def resolve_corpus_dir() -> Path:
    """默认语料目录。"""
    return Path("D:/0-mingyang/文档")


def upload_one(
    base_url: str,
    file_abs_path: Path,
    item: CorpusItem,
    api_key: str = "",
) -> str:
    """上传单份语料，返回 task_id。"""
    url = f"{base_url}/upload"

    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key

    with open(file_abs_path, "rb") as f:
        files = {"files": (file_abs_path.name, f, "application/octet-stream")}
        knowledge_id = f"exhibition_{file_abs_path.stem[:50]}"
        data = {
            "scope_type": SCOPE_TYPE,
            "tenant_id": TENANT_ID,
            "tenant_type": TENANT_TYPE,
            "effective_from": item.effective_from,
            "effective_to": EFFECTIVE_TO,
            "version": item.version,
            "authority": item.authority,
            "status": STATUS,
            "enable_item_name_recognition": str(ENABLE_ITEM_NAME_RECOGNITION).lower(),
            "knowledge_id": knowledge_id,
            "exhibition_id": EXHIBITION_ID,
        }
        resp = requests.post(url, headers=headers, files=files, data=data, timeout=120)

    if resp.status_code != 200:
        raise RuntimeError(f"上传失败 HTTP {resp.status_code}: {resp.text}")

    body = resp.json()
    task_ids = body.get("task_ids", [])
    if not task_ids:
        raise RuntimeError(f"响应无 task_ids: {body}")
    return task_ids[0]


def poll_status(base_url: str, task_id: str, api_key: str = "") -> dict:
    """轮询任务状态直到 completed/failed 或超时。"""
    url = f"{base_url}/status/{task_id}"
    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key

    start = time.time()
    while time.time() - start < POLL_TIMEOUT_S:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            time.sleep(POLL_INTERVAL_S)
            continue
        data = resp.json()
        status = data.get("status", "")
        if status in ("completed", "failed"):
            return data
        time.sleep(POLL_INTERVAL_S)

    return {"status": "timeout", "task_id": task_id}


def run_import(
    base_url: str,
    corpus_dir: Path,
    items: List[CorpusItem],
    api_key: str = "",
) -> List[ImportResult]:
    """执行导入并返回结果列表。"""
    results: List[ImportResult] = []

    for i, item in enumerate(items, 1):
        file_abs_path = corpus_dir / item.relative_path
        print(f"\n[{i}/{len(items)}] {item.relative_path}")
        print(f"  描述: {item.description}")
        print(f"  权威: {item.authority}")
        print(f"  路径: {file_abs_path}")

        if not file_abs_path.exists():
            result = ImportResult(relative_path=item.relative_path, status="file_not_found")
            print("  ❌ 文件不存在")
            results.append(result)
            continue

        file_size_mb = file_abs_path.stat().st_size / (1024 * 1024)
        print(f"  大小: {file_size_mb:.1f} MB")

        start = time.time()
        try:
            task_id = upload_one(base_url, file_abs_path, item, api_key)
            print(f"  task_id: {task_id}")

            status_data = poll_status(base_url, task_id, api_key)
            elapsed = time.time() - start

            result = ImportResult(
                relative_path=item.relative_path,
                task_id=task_id,
                status=status_data.get("status", ""),
                elapsed_s=elapsed,
                done_list=status_data.get("done_list", []),
            )
            if result.status == "completed":
                print(f"  ✅ 完成 ({elapsed:.1f}s) — 节点: {result.done_list}")
            elif result.status == "failed":
                print(f"  ❌ 失败 ({elapsed:.1f}s)")
            else:
                print(f"  ⏰ 超时 ({elapsed:.1f}s)")

        except Exception as e:
            elapsed = time.time() - start
            result = ImportResult(
                relative_path=item.relative_path,
                status="error",
                elapsed_s=elapsed,
                error=str(e),
            )
            print(f"  ❌ 异常: {e}")

        results.append(result)

    return results


def print_report(results: List[ImportResult]) -> None:
    """打印导入报告。"""
    print("\n" + "=" * 60)
    print("导入报告")
    print("=" * 60)

    success = [r for r in results if r.status == "completed"]
    failed = [r for r in results if r.status != "completed"]

    for r in results:
        icon = "✅" if r.status == "completed" else "❌"
        print(f"  {icon} {r.relative_path} — {r.status} ({r.elapsed_s:.1f}s)")
        if r.error:
            print(f"      error: {r.error}")

    print(f"\n成功: {len(success)}/{len(results)}")
    if failed:
        print(f"失败: {len(failed)}/{len(results)}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="会展知识语料导入")
    parser.add_argument("--base-url", default="http://192.168.100.126:8000", help="knowledge-service 地址")
    parser.add_argument("--corpus-dir", default="", help="语料根目录（默认 D:/0-mingyang/文档）")
    parser.add_argument("--api-key", default="", help="KNOWLEDGE_API_KEY（鉴权开启时需要）")
    parser.add_argument("--files", nargs="*", help="指定文件相对路径（默认首期 5 份）")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不实际上传")
    args = parser.parse_args()

    corpus_dir = Path(args.corpus_dir) if args.corpus_dir else resolve_corpus_dir()

    if args.files:
        items = [CorpusItem(relative_path=f, authority="manual") for f in args.files]
    else:
        items = FIRST_BATCH

    print(f"语料目录: {corpus_dir}")
    print(f"目标服务: {args.base_url}")
    print(f"语料数量: {len(items)}")
    print(f"Metadata: scope_type={SCOPE_TYPE}, tenant_id={TENANT_ID}, status={STATUS}")

    if args.dry_run:
        print("\n[dry-run] 不实际上传")
        for i, item in enumerate(items, 1):
            file_abs_path = corpus_dir / item.relative_path
            exists = file_abs_path.exists()
            size = f"{file_abs_path.stat().st_size / 1024 / 1024:.1f} MB" if exists else "N/A"
            print(f"  [{i}] {item.relative_path} — {'✅' if exists else '❌'} {size}")
        return

    results = run_import(args.base_url, corpus_dir, items, args.api_key)
    print_report(results)


if __name__ == "__main__":
    main()
