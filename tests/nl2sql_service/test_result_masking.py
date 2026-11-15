"""L3 结果层脱敏（§5.9）。

1c/D5：脱敏判定从「角色名 + admin 名单」改为「服务端断言 role → feature 集」；
`mask_value` / `mask_sensitive_columns` 两组与角色无关，逐字不动（§7 随动清单）。
"""

from __future__ import annotations

from nl2sql_service.services.result_masking import (
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


class TestExecuteSqlMasking:
    @staticmethod
    def _state(role):
        from unittest.mock import AsyncMock, MagicMock

        dw = MagicMock()
        dw.execute_readonly = AsyncMock(
            return_value=[{"phone": "13812345678", "name": "张三"}]
        )
        ctx = MagicMock()
        ctx.dw_repository = dw
        return {
            "sql": "SELECT phone, name FROM users",
            "context": ctx,
            "sensitive_columns": ["users.phone"],
            "role": role,
            "result_masking_enabled": True,
            "mask_keep_chars": 1,
        }

    async def test_execute_masks_sensitive_for_viewer(self):
        """viewer 无 data.unmasked ⇒ 掩码（与旧 analyst 行为一致）。"""
        from nl2sql_service.agent.nodes.execute_sql import execute_sql

        out = await execute_sql(self._state("viewer"))
        assert out["result"][0]["phone"] == "1*********8"
        assert out["result"][0]["name"] == "张三"

    async def test_execute_no_mask_for_admin(self):
        """admin 有 data.unmasked ⇒ 看全量——这就是 1c 要修的核心行为。"""
        from nl2sql_service.agent.nodes.execute_sql import execute_sql

        out = await execute_sql(self._state("admin"))
        assert out["result"][0]["phone"] == "13812345678"

    async def test_execute_masks_when_role_missing(self):
        """D11 fail-closed：旧调用方 / 无 r 承载 ⇒ role=None ⇒ 无条件脱敏。"""
        from nl2sql_service.agent.nodes.execute_sql import execute_sql

        out = await execute_sql(self._state(None))
        assert out["result"][0]["phone"] == "1*********8"

    async def test_missing_role_records_d9_fallback(self, monkeypatch):
        """真面参与判决：缺 role 时兜底计数必须 +1，不能静默拿空集。"""
        import agent_runtime.authorization as az
        from nl2sql_service.agent.nodes.execute_sql import execute_sql

        monkeypatch.setattr(az, "_fallback_count", 0)
        monkeypatch.setattr(az, "_fallback_warned", set())
        before = az.role_fallback_count()
        await execute_sql(self._state(None))
        assert az.role_fallback_count() == before + 1
