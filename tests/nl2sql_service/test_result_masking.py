"""L3 结果层脱敏（§5.9）。"""

from __future__ import annotations

from nl2sql_service.services.result_masking import (
    is_masked_role,
    mask_sensitive_columns,
    mask_value,
)


class TestMaskValue:
    def test_keep_head_tail(self):
        assert mask_value("13812345678", keep=1) == "1*********8"

    def test_full_mask_when_keep_zero(self):
        assert mask_value("secret", keep=0) == "******"

    def test_short_value_full_mask(self):
        assert mask_value("ab", keep=1) == "**"  # len(2) <= keep*2 → 全掩码
        assert mask_value("abc", keep=1) == "a*c"  # len(3) > keep*2 → 保留首尾

    def test_none_passthrough(self):
        assert mask_value(None) is None

    def test_non_str(self):
        assert mask_value(123456, keep=1) == "1****6"


class TestMaskSensitiveColumns:
    def test_masks_only_sensitive_bare_name(self):
        rows = [{"phone": "13812345678", "name": "张三"}]
        out = mask_sensitive_columns(rows, {"users.phone"}, keep=1)
        assert out[0]["phone"] == "1*********8"
        assert out[0]["name"] == "张三"  # 非敏感列不动
        assert rows[0]["phone"] == "13812345678"  # 不改入参

    def test_empty_sensitive_noop(self):
        rows = [{"phone": "138"}]
        assert mask_sensitive_columns(rows, set()) is rows

    def test_non_list_noop(self):
        assert mask_sensitive_columns(None, {"x"}) is None

    def test_case_insensitive(self):
        out = mask_sensitive_columns([{"Phone": "13812345678"}], {"users.phone"}, keep=1)
        assert out[0]["Phone"] == "1*********8"


class TestIsMaskedRole:
    def test_admin_not_masked(self):
        assert is_masked_role("admin", ["admin"]) is False
        assert is_masked_role("ADMIN", ["admin"]) is False  # 大小写不敏感

    def test_non_admin_masked(self):
        assert is_masked_role("analyst", ["admin"]) is True
        assert is_masked_role("", ["admin"]) is True  # 空角色按最小权限脱敏


class TestExecuteSqlMasking:
    async def test_execute_masks_sensitive_for_analyst(self):
        from unittest.mock import AsyncMock, MagicMock

        from nl2sql_service.agent.nodes.execute_sql import execute_sql

        dw = MagicMock()
        dw.execute_readonly = AsyncMock(return_value=[{"phone": "13812345678", "name": "张三"}])
        ctx = MagicMock()
        ctx.dw_repository = dw
        out = await execute_sql(
            {
                "sql": "SELECT phone, name FROM users",
                "context": ctx,
                "sensitive_columns": ["users.phone"],
                "user_role": "analyst",
                "admin_roles": ["admin"],
                "result_masking_enabled": True,
                "mask_keep_chars": 1,
            }
        )
        assert out["result"][0]["phone"] == "1*********8"
        assert out["result"][0]["name"] == "张三"

    async def test_execute_no_mask_for_admin(self):
        from unittest.mock import AsyncMock, MagicMock

        from nl2sql_service.agent.nodes.execute_sql import execute_sql

        dw = MagicMock()
        dw.execute_readonly = AsyncMock(return_value=[{"phone": "13812345678"}])
        ctx = MagicMock()
        ctx.dw_repository = dw
        out = await execute_sql(
            {
                "sql": "SELECT phone FROM users",
                "context": ctx,
                "sensitive_columns": ["users.phone"],
                "user_role": "admin",
                "admin_roles": ["admin"],
            }
        )
        assert out["result"][0]["phone"] == "13812345678"  # admin 看全量
