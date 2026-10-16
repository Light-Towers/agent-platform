"""P13 身份装配覆盖门禁的治理用例（roadmap 阶段2 #11「6/6 覆盖；门禁生效」）。

沿用 `tests/governance/` 范式（同 L-5 那份）：对门禁函数出**正反例**，而不是只跑一次全仓绿。
没有反例的门禁分不清"确实合规"与"判据失效"。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _load_script(module_name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(module_name, _ROOT / relative_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lint = _load_script("lint_architecture", "scripts/lint_architecture.py")

# 每个服务在临时树里应写入的「装配痕迹」——与登记表一一对应，漏写即视为未装。
_MARKERS = {
    "agent_server": "app.add_middleware(IdentityMiddleware)\n",
    "agent_federation": "mount_identity_middleware(app)\n",
    "kefu-service": "mount_identity_gate(app, \"kefu-service\")\n",
    "nl2sql-service": "mount_identity_gate(app, \"nl2sql-service\")\n",
    "knowledge-service": "app.add_middleware(TenantHeaderMiddleware)\n",
    "exhibition-agent": "ctx = resolve_execution_context(headers)\n",
}


def _build_tree(tmp_path, monkeypatch, overrides: dict[str, str]) -> None:
    """按登记表造一棵临时 applications/ 树：默认每个服务写它自己的装配痕迹，
    overrides 指定的服务改写（用于构造漏装形态）。"""
    for name, marker in _MARKERS.items():
        d = tmp_path / "applications" / name
        d.mkdir(parents=True)
        (d / "entry.py").write_text(overrides.get(name, marker), encoding="utf-8")
    monkeypatch.setattr(lint, "ROOT", tmp_path)


def test_current_tree_has_gate_on_every_service():
    """现状必须 6/6 有身份装配点（kefu/nl2sql 由 2026-10-16 接入；退回去即本用例红）。"""
    assert lint.check_identity_assembly_coverage() == []


def test_missing_assembly_is_named(tmp_path, monkeypatch):
    """真实探测「存在但没装」分支：6 个 app 都在，唯独 nl2sql-service 没有装配痕迹。"""
    _build_tree(tmp_path, monkeypatch, {"nl2sql-service": "pass\n"})
    violations = lint.check_identity_assembly_coverage()
    assert len(violations) == 1, violations
    assert violations[0].startswith("applications/nl2sql-service")
    assert "无身份装配点" in violations[0]
    assert "mount_identity_gate" in violations[0], "修复提示必须给出共享装配入口"


def test_commented_out_gate_counts_as_missing(tmp_path, monkeypatch):
    """痕迹被注释掉 ⇒ 不算装配（`_is_code_line` 生效，防止"注释即在线"）。"""
    _build_tree(tmp_path, monkeypatch, {"kefu-service": '# mount_identity_gate(app, "kefu-service")\n'})
    violations = lint.check_identity_assembly_coverage()
    assert any("kefu-service" in v for v in violations), violations


def test_import_without_call_counts_as_missing(tmp_path, monkeypatch):
    """**只 import 装配函数而不调用** ⇒ 仍算漏装。

    这条来自 2026-10-16 的真实树变异反证：正则最初写成裸名字，
    「注释掉调用、留着 import」时 P13 依然全绿——即"看起来接了其实没接"的形状。
    正则改为调用形后本用例转红，故它是把那次失误钉住的锚。
    """
    _build_tree(
        tmp_path,
        monkeypatch,
        {
            "kefu-service": (
                "from agent_runtime.identity_assembly import mount_identity_gate\n\n"
                "app = object()\n"
            )
        },
    )
    violations = lint.check_identity_assembly_coverage()
    assert any("kefu-service" in v for v in violations), (
        "import 未调用被当成已装配 ⇒ 正则不是调用形，P13 会被'留着 import'蒙过"
    )


def test_registry_mismatch_fails_closed(monkeypatch):
    """登记表与 applications/ 枚举不符 ⇒ 走自检分支，且明确拒绝"放宽本条"。"""
    shrunk = dict(lint._IDENTITY_ASSEMBLY)
    shrunk.pop("knowledge-service")
    monkeypatch.setattr(lint, "_IDENTITY_ASSEMBLY", shrunk)
    violations = lint.check_identity_assembly_coverage()
    assert len(violations) == 1
    assert "自检失败" in violations[0]
    assert "knowledge-service" in violations[0] and "_IDENTITY_ASSEMBLY" in violations[0]


def test_registry_covers_the_documented_six_services():
    """登记表的服务名必须与 _PLATFORM_APPS（= AGENTS.md 目录表的 6 个应用工程）完全一致。"""
    assert set(lint._IDENTITY_ASSEMBLY) == set(lint._PLATFORM_APPS)


def test_implementation_ownership_ledger_is_pinned():
    """钉住「哪几家用共享实现、哪两家还带着自己的实现」这张账。

    收敛 fork 到共享实现时必须同时改这里与登记表——这不是形式主义：
    「6/6 覆盖」这句话的含义（4 shared + 2 fork）会因此显式变化，
    防止把"都装了个门卫"讲成"都用同一个门卫"。
    """
    owners = {app: spec[0] for app, spec in lint._IDENTITY_ASSEMBLY.items()}
    assert owners == {
        "agent_server": "shared",
        "agent_federation": "shared",
        "kefu-service": "shared",
        "nl2sql-service": "shared",
        "knowledge-service": "fork:tenant_identity",
        "exhibition-agent": "fork:execution_context_middleware",
    }, owners
