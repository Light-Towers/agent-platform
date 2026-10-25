# -*- coding: utf-8 -*-
"""SQL 标识符白名单（S4 / P0-10 的单一正则，agent-core 落点）。

背景：`docs/tech-debt/tech-debt-audit-2026-09-22.md:228-237` 登记的 S4——
表名/列名被 f-string 拼进 SQL 的位置共四处，正面范本是
`agent_runtime/db.py:164-169` 的 `_IDENT` 正则。本模块把该正则收敛到
agent-core（三服务共用的最底层包）：agent-runtime 与各应用都 import 它，
不再各写一份、也不再靠"记得校验"。

约定：**值永远参数化，标识符永远过白名单**——两者是不同防线，缺一不可。
"""

from __future__ import annotations

import re

#: 与 agent_runtime/db.py 原 `_IDENT` 逐字节同语义（小写开头，[a-z0-9_]）
IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def validate_identifier(name: str, what: str = "标识符") -> str:
    """单个标识符过白名单；不匹配直接抛错（不静默放过）。"""
    if not name or not IDENT_RE.match(name):
        raise ValueError(f"{what}: 非法标识符 {name!r}（仅允许 [a-z_][a-z0-9_]*）")
    return name


def validate_identifier_list(raw: str, what: str = "列清单") -> list[str]:
    """逗号分隔列清单逐个校验；空项/非法项都抛错。"""
    cols = [c.strip() for c in str(raw).split(",")]
    if not cols or any(not c for c in cols):
        raise ValueError(f"{what}: 含空项 {raw!r}")
    return [validate_identifier(c, what) for c in cols]


def validate_prefixed_table(table: str, prefix: str = "", what: str = "表名") -> str:
    """`{prefix}{body}` 两段都过白名单（前缀来自配置，同样是外部输入）。"""
    if prefix:
        validate_identifier(prefix.rstrip("_") or prefix, "表前缀")
    body = table[len(prefix) :] if prefix and table.startswith(prefix) else table
    validate_identifier(body, what)
    return table


__all__ = ["IDENT_RE", "validate_identifier", "validate_identifier_list", "validate_prefixed_table"]
