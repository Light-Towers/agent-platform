"""
08+16 knowledge-service 通用化测试。

覆盖：
  1. item_name 节点可插拔（导入图 route_after_split / 查询图 route_entry）
  2. Metadata 参数化（state 字段透传）
  3. 生命周期状态机集成（非 PUBLISHED 不进检索）
  4. 多租户隔离（build_retrieval_filter 构造 tenant_id+scope_type 复合过滤）

设计：仅测纯逻辑，不依赖 Milvus/MinIO/LLM 等外部服务。
"""

from __future__ import annotations

import pytest

# zhanggui-zhiku 单向依赖 exhibition-agent（monorepo sibling），可安全 import
from zhanggui_zhiku.core.knowledge_lifecycle_integration import (
    build_lifecycle_metadata,
    should_publish_to_production,
    transition_status,
)
from zhanggui_zhiku.import_process.agent.state import create_default_state, get_default_state
from zhanggui_zhiku.utils.milvus_filter_utils import (
    build_item_name_filter,
    build_retrieval_filter,
    build_tenant_filter,
)

# ---------- 1. item_name 节点可插拔 ----------


class TestItemNameNodePluggable:
    """item_name NER / confirm 节点可插拔：不配置时图跳过该节点。"""

    def test_import_graph_route_after_split_enabled_by_default(self):
        """默认 enable_item_name_recognition=True → 走商品名识别（向后兼容）。"""
        from zhanggui_zhiku.import_process.agent.main_graph import route_after_split

        state = create_default_state(task_id="t1")
        assert route_after_split(state) == "node_item_name_recognition"

    def test_import_graph_route_after_split_disabled(self):
        """enable_item_name_recognition=False → 跳过商品名识别，直接进 BGE 向量化。"""
        from zhanggui_zhiku.import_process.agent.main_graph import route_after_split

        state = create_default_state(task_id="t1", enable_item_name_recognition=False)
        assert route_after_split(state) == "node_bge_embedding"

    def test_query_graph_route_entry_enabled_by_default(self):
        """默认 enable_item_name_confirm=True → 走商品名确认（向后兼容）。"""
        from zhanggui_zhiku.query_process.agent.main_graph import route_entry

        state = {"session_id": "s1", "original_query": "q"}
        assert route_entry(state) == "node_item_name_confirm"

    def test_query_graph_route_entry_disabled(self):
        """enable_item_name_confirm=False → 跳过商品名确认，直接进多路检索。"""
        from zhanggui_zhiku.query_process.agent.main_graph import route_entry

        state = {"session_id": "s1", "original_query": "q", "enable_item_name_confirm": False}
        assert route_entry(state) == "node_multi_search"

    def test_import_graph_compiled_with_conditional_edge(self):
        """导入图编译成功，含 node_item_name_recognition 节点（可插拔不等于移除注册）。"""
        from zhanggui_zhiku.import_process.agent.main_graph import kb_import_app

        # LangGraph 编译后节点可通过 graph.nodes 访问
        node_names = set(kb_import_app.get_graph().nodes.keys())
        assert "node_item_name_recognition" in node_names
        assert "node_bge_embedding" in node_names

    def test_query_graph_compiled_with_entry_virtual_node(self):
        """查询图编译成功，入口为虚拟节点 node_entry_query。"""
        from zhanggui_zhiku.query_process.agent.main_graph import query_app

        node_names = set(query_app.get_graph().nodes.keys())
        assert "node_entry_query" in node_names
        assert "node_item_name_confirm" in node_names
        assert "node_multi_search" in node_names


# ---------- 2. Metadata 参数化 ----------


class TestMetadataParameterization:
    """Metadata 参数化：scope_type/tenant_id/status/... 作为入参传入 state，非硬编码。"""

    def test_default_state_has_metadata_defaults(self):
        """默认 state 含全部 metadata 字段，且 status 默认 DRAFT（未发布不进生产检索）。"""
        state = get_default_state()
        assert state["scope_type"] == "PRIVATE"
        assert state["status"] == "DRAFT"
        assert state["tenant_id"] == ""
        assert state["authority"] == ""
        assert state["enable_item_name_recognition"] is True

    def test_create_state_with_metadata_overrides(self):
        """create_default_state 接受 metadata 覆盖，透传到 state。"""
        state = create_default_state(
            task_id="t1",
            scope_type="PUBLIC",
            tenant_id="tenant_001",
            tenant_type="enterprise",
            effective_from="2026-01-01",
            effective_to="2027-01-01",
            version="v1",
            authority="admin@corp",
            status="PUBLISHED",
            constraint_kind="commercial",
            knowledge_id="k_001",
            enable_item_name_recognition=False,
        )
        assert state["scope_type"] == "PUBLIC"
        assert state["tenant_id"] == "tenant_001"
        assert state["tenant_type"] == "enterprise"
        assert state["effective_from"] == "2026-01-01"
        assert state["effective_to"] == "2027-01-01"
        assert state["version"] == "v1"
        assert state["authority"] == "admin@corp"
        assert state["status"] == "PUBLISHED"
        assert state["constraint_kind"] == "commercial"
        assert state["knowledge_id"] == "k_001"
        assert state["enable_item_name_recognition"] is False

    def test_import_router_metadata_aggregation(self):
        """/upload 路由聚合 metadata 字段逻辑（直接验证字段集合，不启动 FastAPI）。"""
        # 模拟 /upload form 字段 → metadata dict 的聚合逻辑
        form_fields = {
            "scope_type": "PUBLIC",
            "tenant_id": "tenant_A",
            "tenant_type": "enterprise",
            "effective_from": "2026-01-01",
            "effective_to": "2027-01-01",
            "version": "v1",
            "authority": "admin",
            "status": "PUBLISHED",
            "constraint_kind": "free",
            "enable_item_name_recognition": True,
            "knowledge_id": "k_002",
        }
        # 与 import_router.py 中 metadata 聚合一致
        metadata = {
            "scope_type": form_fields["scope_type"],
            "tenant_id": form_fields["tenant_id"],
            "tenant_type": form_fields["tenant_type"],
            "effective_from": form_fields["effective_from"],
            "effective_to": form_fields["effective_to"],
            "version": form_fields["version"],
            "authority": form_fields["authority"],
            "status": form_fields["status"],
            "constraint_kind": form_fields["constraint_kind"],
            "enable_item_name_recognition": form_fields["enable_item_name_recognition"],
            "knowledge_id": form_fields["knowledge_id"],
        }
        # 验证聚合后可注入 state
        state = get_default_state()
        for key in (
            "enable_item_name_recognition",
            "knowledge_id",
            "scope_type",
            "tenant_id",
            "tenant_type",
            "effective_from",
            "effective_to",
            "version",
            "authority",
            "status",
            "constraint_kind",
        ):
            if key in metadata and metadata[key] is not None:
                state[key] = metadata[key]
        assert state["tenant_id"] == "tenant_A"
        assert state["status"] == "PUBLISHED"
        assert state["scope_type"] == "PUBLIC"


# ---------- 3. 生命周期状态机集成 ----------


class TestLifecycleIntegration:
    """生命周期状态机集成：非 PUBLISHED 不进生产检索。"""

    def test_draft_status_skips_production(self):
        """status=DRAFT → 不入生产入库。"""
        state = create_default_state(task_id="t1", status="DRAFT")
        should, reason = should_publish_to_production(state)
        assert should is False
        assert "DRAFT" in reason

    def test_reviewing_status_skips_production(self):
        """status=REVIEWING → 不入生产入库。"""
        state = create_default_state(task_id="t1", status="REVIEWING")
        should, reason = should_publish_to_production(state)
        assert should is False
        assert "REVIEWING" in reason

    def test_expired_status_skips_production(self):
        """status=EXPIRED → 不入生产入库。"""
        state = create_default_state(task_id="t1", status="EXPIRED")
        should, _ = should_publish_to_production(state)
        assert should is False

    def test_published_with_full_metadata_enters_production(self):
        """status=PUBLISHED + 完整 metadata → 入生产入库。"""
        state = create_default_state(
            task_id="t1",
            status="PUBLISHED",
            knowledge_id="k_001",
            tenant_id="tenant_A",
            scope_type="PUBLIC",
            authority="admin@corp",
            effective_from="2026-01-01",
            effective_to="2027-01-01",
            # exhibition_id 或 venue_id 至少一个非空（validate_metadata 要求）
            exhibition_id="expo_001",
        )
        should, reason = should_publish_to_production(state)
        assert should is True
        assert reason == "PUBLISHED"

    def test_published_missing_authority_skips_production(self):
        """status=PUBLISHED 但缺 authority → 降级跳过生产入库。"""
        state = create_default_state(
            task_id="t1",
            status="PUBLISHED",
            knowledge_id="k_001",
            tenant_id="tenant_A",
            scope_type="PUBLIC",
            authority="",  # 缺授权方
            effective_from="2026-01-01",
            effective_to="2027-01-01",
            exhibition_id="expo_001",
        )
        should, reason = should_publish_to_production(state)
        assert should is False
        assert "metadata" in reason or "校验失败" in reason

    def test_published_missing_effective_window_skips_production(self):
        """status=PUBLISHED 但缺 effective_from/to → 降级跳过。"""
        state = create_default_state(
            task_id="t1",
            status="PUBLISHED",
            knowledge_id="k_001",
            tenant_id="tenant_A",
            scope_type="PUBLIC",
            authority="admin",
            effective_from="",  # 缺生效起始
            effective_to="",
            exhibition_id="expo_001",
        )
        should, reason = should_publish_to_production(state)
        assert should is False
        assert "metadata" in reason or "校验失败" in reason

    def test_published_invalid_scope_type_skips_production(self):
        """status=PUBLISHED 但 scope_type 非法 → 降级跳过。"""
        state = create_default_state(
            task_id="t1",
            status="PUBLISHED",
            knowledge_id="k_001",
            tenant_id="tenant_A",
            scope_type="INVALID",  # 非法
            authority="admin",
            effective_from="2026-01-01",
            effective_to="2027-01-01",
            exhibition_id="expo_001",
        )
        should, reason = should_publish_to_production(state)
        assert should is False
        assert "metadata" in reason or "校验失败" in reason

    def test_build_lifecycle_metadata_extracts_fields(self):
        """build_lifecycle_metadata 从 state 提取生命周期校验字段。"""
        state = create_default_state(
            task_id="t1",
            knowledge_id="k_001",
            tenant_id="tenant_A",
            scope_type="PUBLIC",
            authority="admin",
            effective_from="2026-01-01",
            effective_to="2027-01-01",
        )
        meta = build_lifecycle_metadata(state)
        assert meta["knowledge_id"] == "k_001"
        assert meta["tenant_id"] == "tenant_A"
        assert meta["scope_type"] == "PUBLIC"
        assert meta["authority"] == "admin"
        assert meta["effective_from"] == "2026-01-01"
        assert meta["effective_to"] == "2027-01-01"

    def test_transition_status_writes_audit_and_updates_state(self):
        """transition_status 触发合法迁移并更新 state.status。"""
        state = create_default_state(task_id="t1", status="DRAFT", knowledge_id="k_001")
        updated = transition_status(state, "REVIEWING", actor="tester")
        assert updated["status"] == "REVIEWING"
        assert state["status"] == "REVIEWING"  # 原地更新

    def test_transition_status_illegal_raises(self):
        """非法迁移（PUBLISHED → DRAFT）抛 ValueError。"""
        state = create_default_state(task_id="t1", status="PUBLISHED", knowledge_id="k_001")
        with pytest.raises(ValueError, match="非法迁移"):
            transition_status(state, "DRAFT", actor="tester")


# ---------- 4. 多租户隔离 ----------


class TestMultiTenantIsolation:
    """多租户隔离：build_retrieval_filter 构造 tenant_id+scope_type 复合过滤。"""

    def test_item_name_only_filter(self):
        """仅 item_names → item_name in [...] 过滤。"""
        expr = build_retrieval_filter(item_names=["iPhone15", "华为P60"])
        assert expr is not None
        assert "item_name in [" in expr
        assert "tenant_id" not in expr
        assert "scope_type" not in expr

    def test_tenant_only_filter(self):
        """仅 tenant_id → tenant_id == "..." 过滤。"""
        expr = build_retrieval_filter(tenant_id="tenant_A")
        assert expr == 'tenant_id == "tenant_A"'

    def test_scope_only_filter(self):
        """仅 scope_type → scope_type == "..." 过滤。"""
        expr = build_retrieval_filter(scope_type="PUBLIC")
        assert expr == 'scope_type == "PUBLIC"'

    def test_tenant_and_scope_filter(self):
        """tenant_id + scope_type → and 复合过滤。"""
        expr = build_retrieval_filter(tenant_id="tenant_A", scope_type="PRIVATE")
        assert expr == 'tenant_id == "tenant_A" and scope_type == "PRIVATE"'

    def test_full_composite_filter(self):
        """item_names + tenant_id + scope_type → 完整复合过滤。"""
        expr = build_retrieval_filter(
            item_names=["iPhone15"],
            tenant_id="tenant_A",
            scope_type="PUBLIC",
        )
        assert expr is not None
        assert "item_name in [" in expr
        assert "tenant_id == \"tenant_A\"" in expr
        assert 'scope_type == "PUBLIC"' in expr
        assert " and " in expr
        # 顺序：item_name 先，tenant+scope 后
        assert expr.index("item_name") < expr.index("tenant_id")

    def test_empty_filter_returns_none(self):
        """全空 → None（不做过滤，全库检索）。"""
        assert build_retrieval_filter() is None
        assert build_retrieval_filter(item_names=[], tenant_id="", scope_type="") is None

    def test_tenant_isolation_prevents_cross_tenant_leak(self):
        """跨租户隔离：tenant_A 的查询不会命中 tenant_B 的数据（filter 表达式互斥）。"""
        expr_a = build_retrieval_filter(tenant_id="tenant_A")
        expr_b = build_retrieval_filter(tenant_id="tenant_B")
        assert expr_a != expr_b
        assert 'tenant_A' in expr_a and 'tenant_B' not in expr_a
        assert 'tenant_B' in expr_b and 'tenant_A' not in expr_b

    def test_build_item_name_filter_helper(self):
        """build_item_name_filter 单独构造 item_name 过滤。"""
        assert build_item_name_filter(["a", "b"]) == 'item_name in ["a", "b"]'
        assert build_item_name_filter([]) is None
        assert build_item_name_filter(None) is None

    def test_build_tenant_filter_helper(self):
        """build_tenant_filter 单独构造租户过滤。"""
        assert build_tenant_filter("tenant_A") == 'tenant_id == "tenant_A"'
        assert build_tenant_filter("tenant_A", "PUBLIC") == 'tenant_id == "tenant_A" and scope_type == "PUBLIC"'
        assert build_tenant_filter(None) is None
        assert build_tenant_filter("") is None

    def test_filter_escapes_special_chars(self):
        """特殊字符转义防 Milvus 表达式注入。"""
        expr = build_retrieval_filter(tenant_id='a"b')
        # 双引号被转义，避免表达式语法破坏
        assert 'a\\"b' in expr or 'a""b' in expr


# ---------- 5. node_import_milvus 生命周期集成（不实际连 Milvus） ----------


class TestImportMilvusLifecycleGate:
    """node_import_milvus 入口的生命周期门控（不连 Milvus，仅测跳过逻辑）。"""

    def test_draft_state_skips_milvus_insert(self):
        """status=DRAFT 时 node_import_milvus 直接返回，不触发 Milvus 写入。"""
        from zhanggui_zhiku.import_process.agent.nodes.node_import_milvus import node_import_milvus

        state = create_default_state(
            task_id="t1",
            status="DRAFT",
            chunks=[{"content": "x", "dense_vector": [0.1]}],
        )
        # DRAFT → should_publish=False → 节点早返回，不连 Milvus
        result = node_import_milvus(state)
        assert result["status"] == "DRAFT"
        # chunks 未被修改（未进入插入流程）
        assert result["chunks"] == state["chunks"]

    def test_published_state_proceeds_to_milvus(self):
        """status=PUBLISHED + 完整 metadata → 进入 Milvus 流程（连接失败时抛 ValueError）。"""
        from zhanggui_zhiku.import_process.agent.nodes.node_import_milvus import node_import_milvus

        state = create_default_state(
            task_id="t1",
            status="PUBLISHED",
            knowledge_id="k_001",
            tenant_id="tenant_A",
            scope_type="PUBLIC",
            authority="admin",
            effective_from="2026-01-01",
            effective_to="2027-01-01",
            exhibition_id="expo_001",
            chunks=[{"content": "x", "dense_vector": [0.1]}],
        )
        # PUBLISHED → 进入 Milvus 流程 → 无 Milvus 连接 → 抛 ValueError
        with pytest.raises(ValueError, match="Milvus"):
            node_import_milvus(state)


# ---------- 6. 端到端：可插拔 + 多租户 + 生命周期组合 ----------


class TestEndToEndCombination:
    """组合场景：禁用 item_name + 多租户 + 生命周期。"""

    def test_disabled_item_name_with_tenant_and_draft(self):
        """禁用 item_name NER + 多租户 + DRAFT → 跳过 NER，不入生产。"""
        from zhanggui_zhiku.import_process.agent.main_graph import route_after_split

        state = create_default_state(
            task_id="t1",
            enable_item_name_recognition=False,
            tenant_id="tenant_A",
            scope_type="PRIVATE",
            status="DRAFT",
        )
        # 跳过 NER
        assert route_after_split(state) == "node_bge_embedding"
        # DRAFT 不入生产
        should, _ = should_publish_to_production(state)
        assert should is False
        # 多租户 filter 仍可构造
        expr = build_retrieval_filter(tenant_id=state["tenant_id"], scope_type=state["scope_type"])
        assert 'tenant_id == "tenant_A"' in expr
        assert 'scope_type == "PRIVATE"' in expr
