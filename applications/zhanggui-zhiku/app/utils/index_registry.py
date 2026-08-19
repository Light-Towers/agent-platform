# -*- coding: utf-8 -*-
"""
索引 registry：集合 ↔ 构建配置 ↔ 评测得分 的登记文件（M2，方案 §5.4）。

数据文件：``data/index_registry.json``（相对项目根），结构为「集合名 → 记录」：

.. code-block:: json

    {
      "product_manual_v1_bge_m3": {
        "created_at": "2026-01-01T00:00:00Z",
        "embedding_model": "BAAI/bge-m3",
        "chunk_version": "v1-title-aware",
        "chunk_params": { "max_len": null, "merge_short": true },
        "doc_count": null,
        "chunk_count": null,
        "eval": { "recall@5": null, "mrr": null, "ndcg@10": null, "run_id": null }
      }
    }

约定（诚实声明口径）：
- 除 ``created_at``（登记时间）与 ``embedding_model`` / ``chunk_version`` / ``chunk_params``
  （构建配置事实）外，**doc_count / chunk_count 及 eval 内全部指标一律 null**，待实测后回填，
  禁止预填任何数字（方案 §13「所有数字必须实测后填写」）。
- ``register_index`` 由 import 流程在入库成功后调用（node_import_milvus）。
- ``backfill_eval_scores`` 由 eval/run_eval.py 在评测跑完后调用，把得分回填到对应集合条目。

实现说明：
- 采用最小 JSON 文件实现，不引入新组件（方案 §5.4）。
- 写操作带进程内锁，防止并发登记时互相覆盖（单进程足够；多进程部署下仍以文件系统原子替换保证不撕裂）。
"""

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.config import PROJECT_ROOT

# registry 数据文件路径（相对项目根）
REGISTRY_PATH: Path = PROJECT_ROOT / "data" / "index_registry.json"

# 进程内写锁：避免同一进程内并发登记互相覆盖
_registry_lock = threading.Lock()

# eval 指标字段固定清单（M2 必跑指标，M3 起可扩展）
_EVAL_FIELDS: tuple = ("recall@5", "mrr", "ndcg@10", "run_id")


def _ensure_registry_dir() -> None:
    """确保 registry 所在目录存在。"""
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)


def _utc_now_iso() -> str:
    """当前 UTC 时间的 ISO8601 字符串（秒级）。"""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def read_registry() -> Dict[str, Any]:
    """
    读取索引 registry。

    返回：
        Dict[str, Any] - 集合名 → 记录 的映射；文件不存在时返回空 dict。
    异常：
        RuntimeError - registry 文件存在但损坏（JSON 解析失败），显式暴露而非静默丢数据。
    """
    _ensure_registry_dir()
    if not REGISTRY_PATH.exists():
        return {}
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as e:
        raise RuntimeError(f"索引 registry 读取失败（{REGISTRY_PATH}）: {e}") from e


def write_registry(registry: Dict[str, Any]) -> None:
    """
    将整个 registry 原子写回数据文件（先写临时文件再替换，避免写一半损坏）。
    """
    _ensure_registry_dir()
    tmp_path = REGISTRY_PATH.with_name(REGISTRY_PATH.name + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp_path.replace(REGISTRY_PATH)


def _new_eval_entry() -> Dict[str, Any]:
    """返回 eval 字段空模板（全部 null，禁止预填指标数字）。"""
    return {field: None for field in _EVAL_FIELDS}


def register_index(
    collection_name: str,
    *,
    embedding_model: str,
    chunk_version: str,
    chunk_params: Optional[Dict[str, Any]] = None,
    doc_count: Optional[int] = None,
    chunk_count: Optional[int] = None,
    created_at: Optional[str] = None,
) -> Dict[str, Any]:
    """
    import 流程入库成功后登记一条索引记录（幂等：同集合名覆盖）。

    参数：
        collection_name: 版本化集合名（如 product_manual_v1_bge_m3）
        embedding_model: 向量产出模型标识
        chunk_version: 切分策略版本
        chunk_params: 切分参数快照（缺省 {"max_len": null, "merge_short": true}）
        doc_count: 文档数（运行时已知则填，未知留 None 待实测）
        chunk_count: 切片数（运行时已知则填，未知留 None 待实测）
        created_at: 登记时间（缺省取当前 UTC）

    返回：
        新写入的记录 dict。
    """
    entry: Dict[str, Any] = {
        "created_at": created_at or _utc_now_iso(),
        "embedding_model": embedding_model,
        "chunk_version": chunk_version,
        "chunk_params": chunk_params if chunk_params is not None else {"max_len": None, "merge_short": True},
        "doc_count": doc_count,
        "chunk_count": chunk_count,
        "eval": _new_eval_entry(),
    }
    with _registry_lock:
        registry = read_registry()
        registry[collection_name] = entry
        write_registry(registry)
    return entry


def backfill_eval_scores(
    collection_name: str,
    *,
    recall5: Optional[float] = None,
    mrr: Optional[float] = None,
    ndcg10: Optional[float] = None,
    run_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    eval/run_eval.py 跑完后把得分回填到对应集合条目。

    参数：
        collection_name: 版本化集合名
        recall5 / mrr / ndcg10: 实测得分；None 表示本次不更新该指标
        run_id: 评测 run 目录名（如 20260712_120000_ab12cd34）

    返回：
        回填后的集合记录 dict；集合不存在时返回 None（不自动创建，避免伪造索引条目）。
    """
    with _registry_lock:
        registry = read_registry()
        if collection_name not in registry:
            return None
        entry = registry[collection_name]
        eval_entry = entry.setdefault("eval", _new_eval_entry())
        if recall5 is not None:
            eval_entry["recall@5"] = float(recall5)
        if mrr is not None:
            eval_entry["mrr"] = float(mrr)
        if ndcg10 is not None:
            eval_entry["ndcg@10"] = float(ndcg10)
        if run_id is not None:
            eval_entry["run_id"] = run_id
        write_registry(registry)
    return entry
