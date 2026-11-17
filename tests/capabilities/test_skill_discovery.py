"""Capability Discovery + permissions 测试（Plan-F 组合治理）。

覆盖：discover 的 metadata 过滤 / 权限过滤 / 关键词打分 / top_k 截断，
permissions 字段默认值，to_tool_schemas 批量生成。
"""

from __future__ import annotations

from agent_runtime.capabilities.function import as_function_capability
from agent_runtime.capabilities.registry import Capability, CapabilityKind, CapabilityRegistry


async def _noop(**kwargs):
    return None


def _capability(
    name: str,
    description: str,
    *,
    permissions: set[str] | None = None,
    metadata: dict | None = None,
) -> Capability:
    return Capability(
        name=name,
        description=description,
        kind=CapabilityKind.FUNCTION,
        executor=_noop,
        permissions=frozenset(permissions) if permissions else frozenset(),
        metadata=metadata or {},
    )


def _build_registry() -> CapabilityRegistry:
    reg = CapabilityRegistry()
    reg.register(_capability("web_search", "联网搜索网页信息", metadata={"category": "search"}))
    reg.register(_capability("rag_retrieve", "知识库检索文档", metadata={"category": "retrieval"}))
    reg.register(_capability("sql_query", "SQL 数据库查询", metadata={"category": "data"}))
    reg.register(
        _capability("admin_op", "管理员操作", permissions={"admin"}, metadata={"category": "admin"})
    )
    return reg


# ---------- permissions 字段 ----------


def test_capability_permissions_default_empty():
    capability = as_function_capability("x", "X", _noop)
    assert capability.permissions == frozenset()


def test_capability_permissions_set_via_factory():
    capability = as_function_capability("x", "X", _noop, permissions={"read", "write"})
    assert capability.permissions == frozenset({"read", "write"})


# ---------- discover: 无 query ----------


def test_discover_no_query_returns_all_sorted():
    reg = _build_registry()
    result = reg.discover()
    assert [s.name for s in result] == ["admin_op", "rag_retrieve", "sql_query", "web_search"]


def test_discover_top_k_limit():
    reg = _build_registry()
    result = reg.discover(top_k=2)
    assert len(result) == 2


# ---------- discover: metadata 过滤 ----------


def test_discover_metadata_filter():
    reg = _build_registry()
    result = reg.discover(metadata_filter={"category": "search"})
    assert [s.name for s in result] == ["web_search"]


def test_discover_metadata_filter_no_match():
    reg = _build_registry()
    result = reg.discover(metadata_filter={"category": "nonexistent"})
    assert result == []


# ---------- discover: 权限过滤 ----------


def test_discover_permissions_public_always_allowed():
    """permissions 为空的公开能力始终通过权限过滤。"""
    reg = _build_registry()
    result = reg.discover(caller_permissions=set())
    names = [s.name for s in result]
    assert "web_search" in names
    assert "admin_op" not in names


def test_discover_permissions_restricted_denied():
    """调用方不持所需权限时被过滤掉。"""
    reg = _build_registry()
    result = reg.discover(caller_permissions={"read"})
    assert "admin_op" not in [s.name for s in result]


def test_discover_permissions_restricted_allowed():
    """调用方持有全部所需权限时通过。"""
    reg = _build_registry()
    result = reg.discover(caller_permissions={"admin", "read"})
    assert "admin_op" in [s.name for s in result]


# ---------- discover: 关键词打分 ----------


def test_discover_keyword_scoring():
    """query 词与 name/description 重合的 Capability 排前。"""
    reg = _build_registry()
    result = reg.discover("search web")
    assert result[0].name == "web_search"


def test_discover_keyword_no_match_returns_all():
    """query 无匹配时仍返回全部（按名排序）。"""
    reg = _build_registry()
    result = reg.discover("xyz")
    assert len(result) == 4


# ---------- to_tool_schemas 批量 ----------


def test_to_tool_schemas_batch():
    reg = _build_registry()
    capabilities = reg.list()
    schemas = CapabilityRegistry.to_tool_schemas(capabilities)
    assert len(schemas) == 4
    assert all(s["type"] == "function" for s in schemas)


# ---------- 中文分词 ----------


def test_discover_chinese_keyword_scoring():
    """连续中文段按字符拆分，query 中文词能匹配 description 中的中文字符。"""
    reg = CapabilityRegistry()
    reg.register(_capability("web_search", "联网搜索网页信息"))
    reg.register(_capability("sql_query", "数据库SQL查询"))
    result = reg.discover("搜索")
    assert result[0].name == "web_search"


def test_discover_chinese_mixed_keyword():
    """中英混合 query：英文词 + 中文字符共同打分。"""
    reg = CapabilityRegistry()
    reg.register(_capability("web_search", "联网搜索web网页"))
    reg.register(_capability("rag", "知识库检索"))
    result = reg.discover("search 网页")
    assert result[0].name == "web_search"
