"""P5：工具注册表（动态子 Agent / 角色规约）。

把「role -> 该角色所需工具集」集中声明，供 LLM 根据任务动态选取主管携带的工具，
而非固定全量挂载。配合 `main_agent.get_main_agent_for_task` 的 LRU 缓存，
既保证动态性又避免重复构造开销。

设计要点：
- ``TOOL_REGISTRY``：工具名 -> ``"module:attr"`` 延迟定位串（避免在 import 期硬依赖
  外部 SDK，如 tavily；缺失只在真正需要时触发，符合现有 lazy import 风格）。
- ``ROLE_TOOLS``：角色名 -> 工具名列表（声明式，便于扩 Role）。
- ``get_tools_for_roles``：按 role 列表解析实际工具对象（首次用时 importlib 加载）。
- ``build_subagents``：保留原 3 个 subagent 的构建（动态模式不改变委派拓扑）。
"""
from __future__ import annotations

import importlib

# 工具名 -> "module.attr" 延迟定位串（module 相对 agent_federation 包）
TOOL_REGISTRY: dict[str, str] = {
    "generate_markdown": "tools.markdown_tools:generate_markdown",
    "convert_md_to_pdf": "tools.pdf_tools:convert_md_to_pdf",
    "read_file_content": "tools.upload_file_read_tool:read_file_content",
    "execute_sql_query": "tools.db_tools:execute_sql_query",
    "internet_search": "tools.tavily_tool:internet_search",
    "zhiku_retrieve": "tools.zhiku_tools:zhiku_retrieve",
}

# 角色 -> 该角色默认挂载的工具名列表
ROLE_TOOLS: dict[str, list[str]] = {
    "files": ["generate_markdown", "convert_md_to_pdf", "read_file_content"],
    "data": ["execute_sql_query", "read_file_content"],
    "search": ["internet_search", "read_file_content"],
    "knowledge": ["zhiku_retrieve", "read_file_content"],
}

# 基础角色始终挂载（任何模式都需要文件读写能力）
BASE_ROLES = ["files"]
ALL_ROLES = sorted(set(BASE_ROLES + list(ROLE_TOOLS.keys())))

# 工具对象缓存（避免重复 importlib 解析开销）
_RESOLVED: dict[str, object] = {}


def _resolve(name: str) -> object | None:
    """按 name 延迟解析工具对象；缺失依赖时返回 None（并记录一次 warning）。"""
    if name in _RESOLVED:
        return _RESOLVED[name]
    spec = TOOL_REGISTRY.get(name)
    if not spec:
        return None
    module_path, _, attr = spec.partition(":")
    try:
        mod = importlib.import_module(module_path)
        obj = getattr(mod, attr)
    except Exception as exc:  # 缺失 SDK / 导入失败：该工具不参与角色
        import logging
        logging.getLogger(__name__).warning(
            "[tool-registry] 工具 %s 加载失败（缺失依赖？）: %s", name, exc
        )
        _RESOLVED[name] = None
        return None
    _RESOLVED[name] = obj
    return obj


def get_tools_for_roles(roles: list[str] | None) -> list[object]:
    """按角色列表解析出实际工具对象；None 或空 -> 全量工具（回退静态模式）。"""
    if not roles:
        names = list(TOOL_REGISTRY.keys())
    else:
        selected: list[str] = []
        for role in roles:
            selected.extend(ROLE_TOOLS.get(role, []))
        # 去重保序
        seen: set[str] = set()
        names = [n for n in selected if not (n in seen or seen.add(n))]

    tools = []
    for n in names:
        obj = _resolve(n)
        if obj is not None:
            tools.append(obj)
    return tools


def normalize_roles(raw: list[str] | None) -> list[str]:
    """规整 LLM 输出的 role 列表：仅保留已知 role，至少保留 BASE_ROLES。

    防止 LLM 返回未知 role 导致工具集为空（主管无任何工具 = 不可用）。
    """
    if not raw:
        return list(ALL_ROLES)
    known = [r for r in raw if r in ROLE_TOOLS]
    roles = list(BASE_ROLES)
    for r in known:
        if r not in roles:
            roles.append(r)
    return roles
