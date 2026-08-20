"""Skill Discovery + permissions 测试（Plan-F 组合治理）。

覆盖：discover 的 metadata 过滤 / 权限过滤 / 关键词打分 / top_k 截断，
permissions 字段默认值，to_tool_schemas 批量生成。
"""

from __future__ import annotations

from agent_runtime.skills.function import as_function_skill
from agent_runtime.skills.registry import Skill, SkillKind, SkillRegistry


async def _noop(**kwargs):
    return None


def _skill(
    name: str,
    description: str,
    *,
    permissions: set[str] | None = None,
    metadata: dict | None = None,
) -> Skill:
    return Skill(
        name=name,
        description=description,
        kind=SkillKind.FUNCTION,
        executor=_noop,
        permissions=frozenset(permissions) if permissions else frozenset(),
        metadata=metadata or {},
    )


def _build_registry() -> SkillRegistry:
    reg = SkillRegistry()
    reg.register(_skill("web_search", "联网搜索网页信息", metadata={"category": "search"}))
    reg.register(_skill("rag_retrieve", "知识库检索文档", metadata={"category": "retrieval"}))
    reg.register(_skill("sql_query", "SQL 数据库查询", metadata={"category": "data"}))
    reg.register(
        _skill("admin_op", "管理员操作", permissions={"admin"}, metadata={"category": "admin"})
    )
    return reg


# ---------- permissions 字段 ----------


def test_skill_permissions_default_empty():
    skill = as_function_skill("x", "X", _noop)
    assert skill.permissions == frozenset()


def test_skill_permissions_set_via_factory():
    skill = as_function_skill("x", "X", _noop, permissions={"read", "write"})
    assert skill.permissions == frozenset({"read", "write"})


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
    """query 词与 name/description 重合的 Skill 排前。"""
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
    skills = reg.list()
    schemas = SkillRegistry.to_tool_schemas(skills)
    assert len(schemas) == 4
    assert all(s["type"] == "function" for s in schemas)
