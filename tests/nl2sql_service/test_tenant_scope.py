"""租户/工作区作用域解析（P1-1 / A 方案前置）：断言优先 + 单租户 dev 向后兼容。"""

from __future__ import annotations

from nl2sql_service.services.tenant_scope import resolve_scope


class TestResolveScope:
    def test_single_tenant_dev_defaults_empty(self):
        """无断言、无请求体、default 空 ⇒ ('','')，匹配 DDL 默认 '' 行（向后兼容）。"""
        scope = resolve_scope(request_tenant=None, request_workspace=None, default_tenant="", default_workspace="")
        assert scope.tenant_id == "" and scope.workspace_id == ""

    def test_request_tenant_used_when_no_assertion(self):
        scope = resolve_scope(request_tenant="t1", request_workspace="w1", default_tenant="", default_workspace="")
        assert scope.tenant_id == "t1" and scope.workspace_id == "w1"

    def test_default_tenant_fallback(self):
        scope = resolve_scope(request_tenant=None, request_workspace=None, default_tenant="default", default_workspace="ws")
        assert scope.tenant_id == "default" and scope.workspace_id == "ws"

    def test_assertion_overrides_request_body(self):
        """ADR-0007：服务端断言 > 客户端 body——客户端伪造 tenant 不得胜出。"""
        from agent_runtime.workspace_registry import bind_tenant_context, reset_tenant_context

        token = bind_tenant_context("asserted-tenant")
        try:
            scope = resolve_scope(request_tenant="spoofed", request_workspace="w", default_tenant="")
            assert scope.tenant_id == "asserted-tenant"
        finally:
            reset_tenant_context(token)

    def test_whitespace_stripped(self):
        scope = resolve_scope(request_tenant="  t1  ", request_workspace="  ", default_tenant="", default_workspace="d")
        assert scope.tenant_id == "t1" and scope.workspace_id == "d"  # 空 workspace 回落 default


class TestRecallScopeFilter:
    """召回节点把 tenant/workspace/datasource 恒注入过滤（隔离边界，空值匹配 '' 行）。"""

    async def test_recall_column_filters_by_scope(self):
        from unittest.mock import MagicMock

        from nl2sql_service.agent.nodes.recall_column import recall_column

        captured = {}

        async def _recall(keywords, *, embedding=None, top_k=10, score_margin=0.0, filters=()):
            captured["filters"] = filters
            return []

        ctx = MagicMock()
        ctx.column_repository = MagicMock(recall=_recall)
        ctx.meta_repository = None  # 跳过别名主路，直达向量路看 filters
        ctx.embedding_client = None
        await recall_column(
            {
                "keywords": ["订单"],
                "context": ctx,
                "datasource_id": "dw",
                "tenant_id": "t1",
                "workspace_id": "w1",
                "retrieval_top_k": 10,
            }
        )
        # D8 摘键（006，2026-10-23）：workspace 摘出召回过滤——元知识全企业共享
        assert captured["filters"] == (("tenant_id", "t1"), ("datasource_id", "dw"))
        assert ("workspace_id", "w1") not in captured["filters"]

    async def test_recall_relation_passes_scope_to_meta(self):
        from unittest.mock import AsyncMock, MagicMock

        from nl2sql_service.agent.nodes.recall_relation import recall_relation

        meta = MagicMock()
        meta.list_relations = AsyncMock(return_value=[])
        ctx = MagicMock(meta_repository=meta)
        await recall_relation({"context": ctx, "datasource_id": "dw", "tenant_id": "t1", "workspace_id": "w1"})
        meta.list_relations.assert_awaited_once_with("dw", tenant_id="t1", workspace_id="w1")
