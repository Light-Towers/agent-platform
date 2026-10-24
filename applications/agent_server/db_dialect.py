"""业务库方言探测（按 DSN scheme）。

从退役的 `agent_server/sql/guard.py` 迁出（A 方案 Stage ③）：该模块随
agent_server/sql 整包退役，但 `/health` 的 `sql_backend` 标志仍需要方言
探测——那是运维可见性，不属于 Text-to-SQL 能力本身。
"""

from __future__ import annotations


def detect_dialect(dsn: str) -> str:
    """按 DSN scheme 探测方言；未知 scheme 返回 "unknown"（不猜）。"""
    if dsn.startswith("sqlite"):
        return "sqlite"
    if dsn.startswith("postgres"):
        return "postgres"
    if dsn.startswith("mysql"):
        return "mysql"
    return "unknown"
