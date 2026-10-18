"""结果层投影脱敏（§5.9 L3）：确需返回的敏感列按角色投影。

L1（账号 GRANT + 脱敏视图）在 DB 侧、最可靠，但**改不动存量、且精细到人的
可见度只能在这一层**：同一张表，管理员看全量、分析师看掩码。本层在
`execute_sql` 之后、答案合成与响应返回之前，对结果行里的敏感列做投影。

**角色来源是服务端断言，不是客户端请求体**——`role` 若可从请求体传入，
攻击者直接传 `admin` 即绕过。本服务当前未接 ADR-0007 身份门，故 role 取
`settings.default_query_role`（默认 `analyst`，最小权限）；接入身份门后改为
从断言身份取，本函数的入参形状不变。

只脱敏**列名命中敏感清单**的字段；列名大小写不敏感；非字符串值（数字/
None）按字符串掩码规则处理（手机号等常以字符串存，数字型敏感列少见）。
"""

from __future__ import annotations

from typing import Any


def is_masked_role(role: str, admin_roles: list[str]) -> bool:
    """该角色是否走脱敏（不在 admin 名单即脱敏——最小权限默认）。"""
    return (role or "").strip().lower() not in {(r or "").strip().lower() for r in (admin_roles or [])}


def mask_value(value: Any, keep: int = 1) -> Any:
    """掩码单个值：保留首尾各 keep 个字符，中间打 *；短值全掩码。

    keep<=0 = 全掩码。None 原样返回（空值不含信息，不必掩）。
    """
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    if keep <= 0 or len(text) <= keep * 2:
        return "*" * len(text)
    return f"{text[:keep]}{'*' * (len(text) - keep * 2)}{text[-keep:]}"


def mask_sensitive_columns(
    rows: list[dict[str, Any]] | None,
    sensitive_columns: set[str],
    keep: int = 1,
) -> list[dict[str, Any]] | None:
    """对结果行里的敏感列投影掩码（返回新 list，不改入参行）。

    - `sensitive_columns` 是**裸列名**集合（小写）——结果行只有列名，没有表限定，
      故按列名匹配（配置侧仍建议写 `table.column`，这里取 `.` 后段做匹配）；
    - 空敏感清单 / 非 list 行 ⇒ 原样返回（零开销快路）。
    """
    if not rows or not sensitive_columns or not isinstance(rows, list):
        return rows
    # 配置形如 "users.phone"，结果行键是裸列名 ⇒ 取每段的末段建裸名集合
    bare = {c.rsplit(".", 1)[-1].lower() for c in sensitive_columns if c}
    if not bare:
        return rows
    masked: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            masked.append(row)
            continue
        new_row = dict(row)
        for key in new_row:
            if key.lower() in bare:
                new_row[key] = mask_value(new_row[key], keep)
        masked.append(new_row)
    return masked


__all__ = ["is_masked_role", "mask_sensitive_columns", "mask_value"]
