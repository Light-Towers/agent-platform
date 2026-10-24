"""多轮上下文继承（§5.13 M1-M6）：改写器 + 节点 + 仓储形状。"""

from __future__ import annotations

from nl2sql_service.services.query_rewriter import (
    apply_inheritance,
    detect_substitution_types,
    extract_time_window,
)


class TestDetectSubstitution:
    def test_referent(self):
        assert detect_substitution_types("上述三个城市呢") == ["referent"]

    def test_time(self):
        assert detect_substitution_types("那上个月呢") == ["time"]

    def test_both(self):
        assert set(detect_substitution_types("那上述城市上个月呢")) == {"referent", "time"}

    def test_none(self):
        assert detect_substitution_types("查一下今天的订单") == []


class TestExtractTimeWindow:
    def test_year_month_cn(self):
        assert extract_time_window("2026年3月的订单") == "2026-03"

    def test_iso(self):
        assert extract_time_window("统计 2025-12 销售额") == "2025-12"

    def test_month_only(self):
        assert extract_time_window("3月的订单") == "03月"

    def test_none(self):
        assert extract_time_window("查订单") == ""


class TestApplyInheritance:
    def test_no_quadruple_is_identity(self):
        q = "那上个月呢"
        assert apply_inheritance(q, None) == (q, [])

    def test_referent_appends_entities(self):
        q = "上述城市呢"
        eff, subs = apply_inheritance(q, {"entities": ["北京", "上海"]})
        assert subs == ["referent"]
        assert "北京" in eff and "上海" in eff
        assert eff.startswith(q)  # 原始 query 前缀保留（未改写，只追加）
        assert q == "上述城市呢"  # 原始 query 未被 mutate

    def test_time_appends_window(self):
        eff, subs = apply_inheritance("那上个月呢", {"time_window": "2026-10"})
        assert subs == ["time"] and "2026-10" in eff

    def test_marker_present_but_no_data_is_identity(self):
        # 有指代词但四元组无实体 ⇒ 不改写（不塞空提示）
        eff, subs = apply_inheritance("上述呢", {"entities": []})
        assert eff == "上述呢" and subs == []


class TestInheritContextNode:
    async def test_no_session_id_is_noop(self):
        from nl2sql_service.agent.nodes.inherit_context import inherit_context

        out = await inherit_context({"query": "查订单"})
        assert out == {"turn": 1}  # M1：单轮零变更（除 turn 初值）

    async def test_no_meta_repo_is_noop(self):
        from unittest.mock import MagicMock

        from nl2sql_service.agent.nodes.inherit_context import inherit_context

        out = await inherit_context({"query": "q", "session_id": "s1", "context": MagicMock(meta_repository=None)})
        assert out == {"turn": 1}

    async def test_loads_and_substitutes(self):
        from unittest.mock import AsyncMock, MagicMock

        from nl2sql_service.agent.nodes.inherit_context import inherit_context

        meta = MagicMock()
        meta.get_session = AsyncMock(
            return_value={"turn": 2, "quadruple": {"entities": ["北京"], "time_window": "2026-10"}}
        )
        ctx = MagicMock(meta_repository=meta)
        out = await inherit_context(
            {"query": "那上述城市上个月呢", "session_id": "s1", "datasource_id": "dw", "context": ctx}
        )
        assert out["turn"] == 3
        assert set(out["substitutions"]) == {"referent", "time"}
        assert "effective_query" in out
        assert "北京" in out["effective_query"]

    async def test_cross_source_no_session_row(self):
        """M4：换 datasource = 另一行；get_session 返回 None ⇒ 不继承。"""
        from unittest.mock import AsyncMock, MagicMock

        from nl2sql_service.agent.nodes.inherit_context import inherit_context

        meta = MagicMock()
        meta.get_session = AsyncMock(return_value=None)  # 该 (session, ds) 无行
        ctx = MagicMock(meta_repository=meta)
        out = await inherit_context(
            {"query": "那上述呢", "session_id": "s1", "datasource_id": "other", "context": ctx}
        )
        assert out == {"turn": 1}
        meta.get_session.assert_awaited_once_with("s1", "other", tenant_id="", workspace_id="")


class TestFinalizeNode:
    def test_build_quadruple(self):
        from nl2sql_service.agent.nodes.finalize import build_quadruple

        q = build_quadruple(
            {
                "query": "2026年3月北京上海的订单",
                "value_matched": ["北京", "上海"],
                "tables": [{"table_name": "orders"}],
                "sql": "SELECT * FROM orders",
            }
        )
        assert q["time_window"] == "2026-03"
        assert set(q["entities"]) >= {"北京", "上海", "orders"}
        assert q["candidate_tables"] == ["orders"]
        assert q["generated_sql"] == "SELECT * FROM orders"

    def test_build_trace_counts_rows(self):
        from nl2sql_service.agent.nodes.finalize import build_trace

        t = build_trace({"result": [{"a": 1}, {"a": 2}], "sql": "SELECT 1", "query": "q"}, latency_ms=12.5)
        assert t["result_rows"] == 2
        assert t["latency_ms"] == 12.5
        assert t["dict_hit"] is False

    async def test_finalize_no_meta_noop(self):
        from unittest.mock import MagicMock

        from nl2sql_service.agent.nodes.finalize import finalize

        assert await finalize({"context": MagicMock(meta_repository=None)}) == {}

    async def test_finalize_writes_trace_and_session(self):
        from unittest.mock import AsyncMock, MagicMock

        from nl2sql_service.agent.nodes.finalize import finalize

        meta = MagicMock()
        meta.insert_trace = AsyncMock()
        meta.upsert_session = AsyncMock()
        ctx = MagicMock(meta_repository=meta)
        await finalize(
            {"context": ctx, "session_id": "s1", "datasource_id": "dw", "query": "q", "sql": "SELECT 1", "turn": 2}
        )
        meta.insert_trace.assert_awaited_once()
        meta.upsert_session.assert_awaited_once()

    async def test_finalize_trace_only_without_session(self):
        from unittest.mock import AsyncMock, MagicMock

        from nl2sql_service.agent.nodes.finalize import finalize

        meta = MagicMock()
        meta.insert_trace = AsyncMock()
        meta.upsert_session = AsyncMock()
        ctx = MagicMock(meta_repository=meta)
        await finalize({"context": ctx, "query": "q", "sql": "SELECT 1"})  # 无 session_id
        meta.insert_trace.assert_awaited_once()
        meta.upsert_session.assert_not_awaited()


class TestMetaRepositorySessionTrace:
    """meta_repository 的 session/trace 方法：SQL 形状与参数化（用 fake 池）。"""

    async def test_get_session_returns_none_when_empty(self):
        from unittest.mock import AsyncMock, MagicMock

        from nl2sql_service.repositories.postgres.meta.meta_repository import MetaRepository

        cur = MagicMock()
        cur.fetchone = AsyncMock(return_value=None)
        conn = MagicMock()
        conn.execute = AsyncMock(return_value=cur)
        pool = MagicMock()
        pool.connection = MagicMock(return_value=_AsyncCtx(conn))
        repo = MetaRepository(pool=pool)
        assert await repo.get_session("s1", "dw") is None

    async def test_upsert_session_parameterized(self):
        from unittest.mock import AsyncMock, MagicMock

        from nl2sql_service.repositories.postgres.meta.meta_repository import MetaRepository

        conn = MagicMock()
        conn.execute = AsyncMock()
        pool = MagicMock()
        pool.connection = MagicMock(return_value=_AsyncCtx(conn))
        repo = MetaRepository(pool=pool)
        await repo.upsert_session("s1", "dw", {"entities": ["x"]}, [], 3)
        sql, params = conn.execute.call_args[0]
        assert "session_state" in sql and "ON CONFLICT" in sql
        # JSONB 两列走 Json 适配器，标量列是普通字符串
        assert params[2] == "s1" and params[3] == "dw" and params[4] == 3


class _AsyncCtx:
    def __init__(self, obj):
        self._obj = obj

    async def __aenter__(self):
        return self._obj

    async def __aexit__(self, *a):
        return False
