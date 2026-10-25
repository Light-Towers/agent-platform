"""L-5 观测装配存在性门禁的治理用例（roadmap 阶段2 #12「漏装即 CI 失败」）。

沿用 `tests/governance/` 既有范式：对门禁函数本身出**正反例**，而不是只跑一次全仓绿。
一条没有反例的门禁无法区分"确实合规"与"判据失效"——本轮实施时就被这一点抓到过：
最初用 `applications/*/pyproject.toml` 认"一个 app"，会静默漏掉 agent_server
（它是根 workspace 成员、自身无 pyproject.toml），若无自检就成了永绿门禁。

不改动工作区文件：通过 monkeypatch `_PLATFORM_APPS` 构造"应有但没装"与"枚举不符"两种形态。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _load_script(module_name: str, relative_path: str):
    """与 tests/governance/ 既有范式一致：scripts/ 不是包，按文件路径加载。"""
    spec = importlib.util.spec_from_file_location(module_name, _ROOT / relative_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lint = _load_script("lint_architecture", "scripts/lint_architecture.py")


def test_current_tree_is_fully_assembled():
    """现状必须 6/6 有装配点（kefu/nl2sql 由 #12 补齐；退回去即本用例红）。"""
    assert lint.check_observability_assembly_coverage() == []


def test_missing_assembly_is_named(tmp_path, monkeypatch):
    """真实探测「存在但没装」分支：造一棵临时树，6 个 app 都在，唯独一个没有装配点。

    不能靠往 _PLATFORM_APPS 里塞假名字来模拟——那样会先命中自检分支（清单与枚举不符），
    测到的就不是漏装检测了。第一版就是这么写错的，改回按文件系统构造。
    """
    apps_root = tmp_path / "applications"
    for name in sorted(lint._PLATFORM_APPS):
        d = apps_root / name
        d.mkdir(parents=True)
        body = (
            "pass\n"  # 故意漏装
            if name == "kefu-service"
            else 'init_tracing(service_name="x")\n'
        )
        (d / "entry.py").write_text(body, encoding="utf-8")
    monkeypatch.setattr(lint, "ROOT", tmp_path)

    violations = lint.check_observability_assembly_coverage()
    assert any(
        v.startswith("applications/kefu-service") and "无 init_tracing 装配点" in v
        for v in violations
    ), violations
    # 已装的 5 个不应被牵连
    assert not any("agent_server" in v for v in violations), violations


def test_enumeration_mismatch_fails_closed(monkeypatch):
    """枚举与已知清单不符 ⇒ 走自检分支，且明确拒绝"放宽阈值"。

    这是防永绿的要害：目录改名/新增服务未登记/判据失效三种情况都会让枚举少一个，
    若本条只是"数一数有没有装"，漏掉的那个会因不在枚举里而永远不会被要求装配。
    """
    monkeypatch.setattr(lint, "_PLATFORM_APPS", frozenset({"agent_server", "不存在的app"}))
    violations = lint.check_observability_assembly_coverage()
    assert len(violations) == 1
    assert "自检失败" in violations[0]
    assert "枚举" in violations[0] and "_PLATFORM_APPS" in violations[0]


def test_platform_apps_list_matches_agents_md_six_services():
    """清单本身也得钉住：AGENTS.md 目录表列的 6 个应用工程。"""
    assert lint._PLATFORM_APPS == frozenset(
        {
            "agent_server",
            "agent_federation",
            "kefu-service",
            "nl2sql-service",
            "knowledge-service",
            "exhibition-agent",
        }
    )
