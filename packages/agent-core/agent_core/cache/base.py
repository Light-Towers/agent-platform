# -*- coding: utf-8 -*-
"""语义缓存统一契约：``BaseSemanticCache`` Protocol 与 key 构造单一真相。

零依赖（仅 stdlib）。双轨（``app`` 的 ``PgSemanticCache`` / ``deepagents`` 的
``SemanticCache``）各自实现该协议，但**不跨后端共享缓存数据**（向量空间/
存储引擎不一致，现状保留）。本模块只定义接口与 key 构造的单一来源，避免
deepagents 与未来 app 重构各写一份 hash 逻辑导致漂移。

参考：``docs/architecture-improvement-plan.md`` §6 TB-4（M5 语义缓存统一专项）。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class BaseSemanticCache(Protocol):
    """语义缓存统一接口（仅签名，零依赖）。

    双轨缓存实现（app PgSemanticCache / deepagents SemanticCache）应在类或
    模块上体现该协议的语义。``get`` / ``set`` 的入参因后端而异（app 用
    question+pool+embedding，deepagents 用 intent+rewritten_query+query_vec），
    故此处以 StructRag 风格声明最小公共契约，不强制参数形状——
    重点是 ``get_stats`` / ``reset_stats`` 统计接口统一、``build_cache_key``
    key 构造单一真相。
    """

    def get_stats(self) -> dict[str, Any]:
        """返回命中率统计快照（``CacheStats.snapshot()`` 形态）。"""
        ...

    def reset_stats(self) -> None:
        """重置统计。"""
        ...


def build_cache_key(
    intent: str,
    rewritten_query: str,
    kb_versions: dict[str, str] | None = None,
    tenant_id: str = "",
    gray_pct: float = 0.0,
) -> str:
    """构造语义缓存 key（单一真相，纯函数）。

    与 deepagents 既有实现保持完全一致：
    ``sha256(intent|rewritten_query|kb_versions_json|tenant_id|gray_pct)``。

    :param intent: 意图标签
    :param rewritten_query: 改写后的 query
    :param kb_versions: 各子服务 KB 版本（影响 key，版本变更自动失效旧缓存）
    :param tenant_id: 租户隔离
    :param gray_pct: 灰度比例（影响 key，避免灰度/正式缓存串味）
    :return: 64 位十六进制 sha256
    """
    kb_versions = kb_versions or {}
    kb_str = json.dumps(kb_versions, sort_keys=True)
    raw = f"{intent}|{rewritten_query}|{kb_str}|{tenant_id}|{gray_pct}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


__all__ = ["BaseSemanticCache", "build_cache_key"]
