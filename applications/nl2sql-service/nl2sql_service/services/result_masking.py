"""结果层投影脱敏（§5.9 L3）：确需返回的敏感列按角色投影。

L1（账号 GRANT + 脱敏视图）在 DB 侧、最可靠，但**改不动存量、且精细到人的
可见度只能在这一层**：同一张表，管理员看全量、分析师看掩码。本层在
`execute_sql` 之后、答案合成与响应返回之前，对结果行里的敏感列做投影。

**角色来源是服务端断言，不是客户端请求体**——1c 起 role 由内部签名头的 `r`
键承载，能力判定在 `execute_sql._apply_masking` 经
`agent_runtime.authorization.has_feature(role, "data.unmasked")` 单一解释；
缺 `r` / 未知码一律收敛到 viewer ⇒ 无条件脱敏（fail-closed）。

只脱敏**列名命中敏感清单**的字段；列名大小写不敏感；非字符串值（数字/
None）按字符串掩码规则处理（手机号等常以字符串存，数字型敏感列少见）。
本模块只保留无状态的列掩码原语，不再解释角色词汇表。
"""

from __future__ import annotations

from typing import Any


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


__all__ = ["mask_sensitive_columns", "mask_value"]
