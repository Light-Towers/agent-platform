"""治理红线（W-2，2026-09-25）：记忆动词禁止 ``tenant_id`` 默认落 ``default``。

背景：内核与门面五动词曾签名 ``tenant_id: str = "default"``——身份传播 bug
会静默落共享 default 桶（多租户下即跨租户可见）。现已全链收紧为哨兵
``_TENANT_UNSET``（漏传 fail-fast，见 ``agent_core/memory/_tenant_gate.py``）。
本测试用 AST 断言该默认值形态不在记忆模块回潮；新增记忆动词必须显式要求
租户（哨兵）或显式必填。
"""

from __future__ import annotations

import ast
from pathlib import Path

# 扫描范围：内核记忆模块 + 两个宿主门面（租户决策点）
SCAN_PATHS = [
    "packages/agent-core/agent_core/memory",
    "applications/agent_server/memory",
    "applications/agent_federation/agent/memory",
]

# 白名单：构造期配置参数（一次构造长期使用，租户由部署配置决定），
# 与「逐调用身份传播」不同类；其隔离能力声明由 CapabilityReport/probe 负责。
# vector_backend 的 tenant_id 列语义（schema 有列但 VectorMemoryStore 声明
# 不支持隔离）存在矛盾，另立子任务审计，不在本红线范围。
WHITELIST = {
    ("mongo_checkpointer.py", "__init__"),
    ("mongo_checkpointer.py", "create_mongo_checkpointer"),
    ("vector_backend.py", "__init__"),
    ("vector_backend.py", "create_memory_backend"),
}


def _tenant_default_offenders(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        a = node.args
        pairs: list[tuple[ast.arg, ast.expr | None]] = []
        pos, ndef = a.args, len(a.defaults)
        for arg, default in zip(pos[len(pos) - ndef :], a.defaults):
            pairs.append((arg, default))
        for arg, default in zip(a.kwonlyargs, a.kw_defaults):
            pairs.append((arg, default))
        for arg, default in pairs:
            if (
                arg.arg == "tenant_id"
                and default is not None
                and isinstance(default, ast.Constant)
                and default.value == "default"
            ):
                if (path.name, node.name) in WHITELIST:
                    continue
                hits.append(f"{path.name}:{node.lineno} {node.name}()")
    return hits


def test_memory_verbs_do_not_default_tenant_to_shared_bucket():
    root = Path(__file__).resolve().parents[2]
    offenders: list[str] = []
    for rel in SCAN_PATHS:
        for p in sorted((root / rel).rglob("*.py")):
            offenders.extend(_tenant_default_offenders(p))
    assert not offenders, (
        "记忆动词出现 tenant_id 默认 'default'（漏传即静默落共享桶，W-2 禁止）：\n"
        + "\n".join(offenders)
        + "\n修复：默认值改为 _TENANT_UNSET 哨兵并在函数体首行 resolve_tenant(tenant_id)。"
    )


def test_tenant_gate_sentinel_is_fail_fast():
    """哨兵行为契约：漏传抛 ValueError，显式传原样返回。"""
    import pytest
    from agent_core.memory._tenant_gate import _TENANT_UNSET, resolve_tenant

    with pytest.raises(ValueError, match="显式传入"):
        resolve_tenant(_TENANT_UNSET)
    assert resolve_tenant("tenant-a") == "tenant-a"
    assert resolve_tenant("default") == "default"  # 显式单租户模式合法
