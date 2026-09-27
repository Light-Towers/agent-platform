"""身份参数红线（ADR-0007 §4.3 / plan A2）：LLM 不得经 tool/skill 参数指定身份。

背景：`tenant_id` 由 LLM 填（曾 `capabilities.py` 把 `tenant_id` 列为 remote skill 的
required 参数）→ 模型幻觉或提示注入（MINJA / OWASP ASI06）可把检索/写入打到任意租户。
身份（tenant_id/user_id/api_key）**不得作为 LLM 可填的 tool/skill 入参**，一律服务端
从断言源注入。

本测试 AST 扫描"定义 skill/tool 的源文件"里的 **JSON-Schema 字面量**（含 `properties`
的 dict）：若 `properties` 的键、或 `required` 列表的元素命中 {tenant_id, user_id,
api_key} → 红。

已知边界（非收窄，而是精确锁定攻击面）：
- 只看 schema 的参数**键 / required 项**，不看 description 文本（描述里提"tenant_id"
  不产生可填参数，非攻击面）；
- pydantic 模型字段（如 `shared_schemas.QueryRequest.tenant_id`）不是 JSON-Schema
  `properties` dict，天然不在此红线范围（其收口由 A5 的"服务端断言值覆盖"处理）；
- 仅扫描"含 skill/tool 注册标记"的源文件，避开无关 dict 字面量误报。
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# 定义 skill/tool 的注册标记；命中其一的文件才纳入扫描。
_TOOL_MARKERS = (
    "as_function_skill",
    "as_remote_skill",
    "as_dag_skill",
    "input_schema",
    "@tool",
    "parameters=",
)

# 身份类参数键：出现在 LLM 可填 schema 即红线。
_IDENTITY_KEYS = frozenset({"tenant_id", "user_id", "api_key"})

# 扫描范围（源码，排除测试/评测目录）。
_SCAN_DIRS = ("applications", "packages")
_SKIP_PARTS = {"tests", "eval", "evaluation", "__pycache__", ".venv"}


def _iter_files():
    for base in _SCAN_DIRS:
        root = REPO / base
        if not root.is_dir():
            continue
        for py in root.rglob("*.py"):
            if _SKIP_PARTS & set(py.parts):
                continue
            yield py


def _schema_dicts_with_properties(tree: ast.AST) -> list[ast.Dict]:
    """返回含 `properties` 键的 dict 字面量（JSON-Schema 对象形态）。"""
    out: list[ast.Dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and k.value == "properties":
                    out.append(node)
                    break
    return out


def _string_keys(props_dict: ast.Dict) -> set[str]:
    return {k.value for k in props_dict.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}


def _required_identity(schema: ast.Dict) -> list[str]:
    """schema 顶层 `required` 列表里命中的身份键。"""
    for k, v in zip(schema.keys, schema.values):
        if isinstance(k, ast.Constant) and k.value == "required" and isinstance(v, (ast.List, ast.Tuple)):
            return [
                e.value for e in v.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str) and e.value in _IDENTITY_KEYS
            ]
    return []


def test_no_identity_params_in_llm_tool_schemas():
    offenders: list[str] = []
    for py in _iter_files():
        try:
            src = py.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if not any(m in src for m in _TOOL_MARKERS):
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for schema in _schema_dicts_with_properties(tree):
            # 找该 schema 的 properties dict
            props_node = None
            for k, v in zip(schema.keys, schema.values):
                if isinstance(k, ast.Constant) and k.value == "properties" and isinstance(v, ast.Dict):
                    props_node = v
            if props_node is not None:
                bad = _string_keys(props_node) & _IDENTITY_KEYS
                for key in sorted(bad):
                    offenders.append(f"{py.relative_to(REPO)}: schema property '{key}' 不得由 LLM 填")
            for key in _required_identity(schema):
                offenders.append(f"{py.relative_to(REPO)}: schema required 含身份键 '{key}'")
    assert not offenders, (
        "LLM tool/skill 参数 schema 中不得出现身份键（ADR-0007 §4.3，防幻觉/提示注入越权）：\n"
        + "\n".join(offenders)
    )


def test_sanitize_identity_strips_llm_supplied_identity():
    """行为级：即便 LLM 惯性输出 tenant_id/user_id/api_key，也被剔除，租户取服务端断言源。"""
    from agent_server.capabilities import _sanitize_identity

    out = _sanitize_identity(
        {"query": "x", "tenant_id": "OTHER_TENANT", "user_id": "spoof", "api_key": "leak"}
    )
    # 非租户身份键一律不透传下游
    assert "user_id" not in out and "api_key" not in out
    # 租户绝不等于 LLM 传入值，而是服务端断言（A3 前=部署级 default）
    assert out["tenant_id"] != "OTHER_TENANT"
    from agent_runtime.workspace_registry import server_tenant_id
    from agent_server.config import get_settings

    assert out["tenant_id"] == server_tenant_id(get_settings().default_tenant_id)
