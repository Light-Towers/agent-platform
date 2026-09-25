#!/usr/bin/env python3
"""架构约束 lint：检测违反模块边界的调用模式。

P4-2：收紧 registry.execute 直接可见性。
架构契约：Skill → Skill 组合唯一合法路径是 runtime.delegate()，
禁止在 skills/ 和 planner/ 外部直接调 registry.execute()。

白名单（宿主代码，有意保留）：
- planner/protocol.py（delegate 实现内部）
- agent_server/agent/graph.py（_invoke 回退，向后兼容）
- skills/registry.py（SkillRegistry 自身）
- tests/ / eval/（测试与评测）
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 模式：匹配 registry.execute( 和 get_registry().execute(
_PATTERN = re.compile(r"(?:get_registry\(\)|registry)\.execute\s*\(")

# 白名单：允许直接调用 registry.execute 的文件（相对路径前缀匹配）
_WHITELIST = (
    "packages/agent-runtime/agent_runtime/planner/protocol.py",
    "packages/agent-runtime/agent_runtime/skills/registry.py",
    "applications/agent_server/agent/graph.py",
    "tests/",
    "eval/",
    "scripts/lint_architecture.py",
    # 各包自身测试
    "packages/agent-core/tests/",
    "packages/agent-runtime/tests/",
    "applications/agent_federation/tests/",
    "applications/agent_server/tests/",
    "applications/kefu-service/tests/",
    "applications/exhibition-agent/tests/",
    "applications/knowledge-service/tests/",
    "applications/nl2sql-service/tests/",
)


def check() -> list[str]:
    violations: list[str] = []
    for py_file in ROOT.rglob("*.py"):
        rel = py_file.relative_to(ROOT).as_posix()
        # 跳过 .venv / __pycache__ / .ruff_cache / IDE 临时文件
        if any(p in rel for p in (".venv", "__pycache__", ".ruff_cache", ".egg-info",
                                   ".codeartsdoer", ".codebuddy")):
            continue
        if any(rel.startswith(w) or rel == w for w in _WHITELIST):
            continue
        try:
            for lineno, line in enumerate(py_file.read_text(encoding="utf-8").splitlines(), 1):
                if _PATTERN.search(line):
                    violations.append(f"{rel}:{lineno}: {line.strip()}")
        except Exception:
            pass
    return violations


# ---------------------------------------------------------------------------
# P2 架构不变量：生产 FastAPI app 必须经 agent_core 统一工厂 ``build_api_app``
# 创建，由构造保证注册统一 500 脱敏 handler（仅扫 applications/**）。
# 见 docs/plans/plan-p2-unified-exception-handlers-2026-09-24.md §3.2/§3.3。
# 白名单：knowledge-service main.py（已有自实现 handler，D-3 本轮不迁移）、
# exhibition mock_server（dev fixture、非网关服务）；各 tests/ 已跳。
# ---------------------------------------------------------------------------
_FASTAPI_PATTERN = re.compile(r"\bFastAPI\s*\(")
_FASTAPI_WHITELIST = (
    "applications/knowledge-service/knowledge_service/main.py",
    "applications/exhibition-agent/exhibition_agent/mock_server/warehouse_mock.py",
)


def check_fastapi_apps() -> list[str]:
    violations: list[str] = []
    for py_file in ROOT.rglob("*.py"):
        rel = py_file.relative_to(ROOT).as_posix()
        if not rel.startswith("applications/"):
            continue
        if any(p in rel for p in (".venv", "__pycache__", ".ruff_cache", ".egg-info",
                                   ".codeartsdoer", ".codebuddy")):
            continue
        if "/tests/" in rel:
            continue
        if any(rel == w or rel.startswith(w) for w in _FASTAPI_WHITELIST):
            continue
        try:
            for lineno, line in enumerate(py_file.read_text(encoding="utf-8").splitlines(), 1):
                if _FASTAPI_PATTERN.search(line):
                    violations.append(f"{rel}:{lineno}: {line.strip()}")
        except Exception:
            pass
    return violations


# ---------------------------------------------------------------------------
# P5 架构不变量：workspace 成员间顶层包名不得重复。
# 背景：uv/hatchling editable 安装以朴素 .pth 把成员源码根整体加入 sys.path，
# 源码根下任何含 __init__.py 的子目录都会成为可全局 import 的顶层包；
# 跨成员重名时解析结果取决于 .pth 顺序（隐式遮蔽，曾导致 ks 单测 collection 失败）。
# 历史冲突 eval（agent_federation vs knowledge-service）已于 2026-09-25 消歧义，
# 见 docs/plans/plan-workspace-toplevel-eval-disambiguation-2026-09-25.md。
# 规则：若成员源码根本身是包（含 __init__.py）则只暴露包名；否则暴露其下
# 含 __init__.py 且名为合法标识符的直接子目录（与 .pth 真实暴露机制同源）。
# ---------------------------------------------------------------------------
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _exposed_toplevel_names(source_root: Path) -> set[str]:
    """返回某 sys.path 暴露根下的顶层 regular package 名集合。"""
    if (source_root / "__init__.py").exists():
        # 源码根自身就是包：作为整体被暴露，其子目录已在包命名空间内，不占顶层
        return {source_root.name} if _IDENT_RE.match(source_root.name) else set()
    exposed: set[str] = set()
    for child in source_root.iterdir():
        if (
            child.is_dir()
            and not child.name.startswith((".", "_"))
            and _IDENT_RE.match(child.name)
            and (child / "__init__.py").exists()
        ):
            exposed.add(child.name)
    return exposed


def check_toplevel_package_clashes() -> list[str]:
    """跨 workspace 成员检测顶层包名重复；返回违规描述列表（空=通过）。"""
    with (ROOT / "pyproject.toml").open("rb") as f:
        data = tomllib.load(f)

    # 暴露根 = 各 workspace 成员目录 + 根包 wheel packages 的父目录（如 applications/）
    source_roots: list[Path] = [
        ROOT / m for m in data.get("tool", {}).get("uv", {}).get("workspace", {}).get("members", [])
    ]
    for pkg in data.get("tool", {}).get("hatch", {}).get("build", {}).get("targets", {}).get("wheel", {}).get("packages", []):
        pkg_dir = ROOT / pkg
        if pkg_dir.exists():
            source_roots.append(pkg_dir.parent)

    owners: dict[str, list[Path]] = {}
    seen_roots: set[Path] = set()
    for root in source_roots:
        if not root.is_dir() or root in seen_roots:
            continue
        seen_roots.add(root)
        for name in _exposed_toplevel_names(root):
            owners.setdefault(name, []).append(root)

    violations: list[str] = []
    for name, roots in sorted(owners.items()):
        uniq = sorted({r.relative_to(ROOT).as_posix() for r in roots})
        if len(uniq) > 1:
            violations.append(f"顶层包名 '{name}' 被多个成员同时暴露: {uniq}")
    return violations


# ---------------------------------------------------------------------------
# 批 3 架构不变量：tool 事件上报唯一出口 = agent_core.observability.observe_tool。
# applications/** 生产代码禁止裸调 monitor.report_tool / monitor.report_tool_outcome
# （散点埋点反模式，见 docs/plans/plan-tool-instrumentation-choke-point-2026-09-25.md
# §5 批 3）；outcome 语义经 ToolResult 返回承载（v3.1 定板）。
# 作用域仅 applications/**：kernel（agent_core/observability）为合法实现位；
# tests/ 由作用域排除；evaluation 订阅走 monitor.on 非本模式，天然不命中。
# ---------------------------------------------------------------------------
# 负向前瞻 (?<![\w.])：排除 foo_monitor / self._monitor 等误命中（仍精准匹配裸 monitor）
_TOOL_MONITOR_PATTERN = re.compile(r"(?<![\w.])monitor\.report_tool(?:_outcome)?\s*\(")
_TOOL_MONITOR_WHITELIST: tuple[str, ...] = ()


def check_tool_monitor_scatter() -> list[str]:
    """app 层禁止裸调 monitor.report_tool*（散点埋点）；返回违规描述列表。"""
    violations: list[str] = []
    for py_file in ROOT.rglob("*.py"):
        rel = py_file.relative_to(ROOT).as_posix()
        if not rel.startswith("applications/"):
            continue
        if any(p in rel for p in (".venv", "__pycache__", ".ruff_cache", ".egg-info",
                                   ".codeartsdoer", ".codebuddy")):
            continue
        if "/tests/" in rel:
            continue
        if any(rel == w or rel.startswith(w) for w in _TOOL_MONITOR_WHITELIST):
            continue
        try:
            for lineno, line in enumerate(py_file.read_text(encoding="utf-8").splitlines(), 1):
                if _TOOL_MONITOR_PATTERN.search(line):
                    violations.append(f"{rel}:{lineno}: {line.strip()}")
        except Exception:
            pass
    return violations


_TOOL_REGISTRY_PATH = ROOT / "applications" / "agent_federation" / "agent" / "tool_registry.py"
_DIRECT_IMPORT_PATTERN = re.compile(r"^\s*from\s+tools\.[\w.]*\s+import\s+(.+)$")


def _load_registry_tool_names() -> set[str]:
    """从 TOOL_REGISTRY 解析已注册 @tool 属性名（module:attr 的 attr 即工具名）。"""
    try:
        text = _TOOL_REGISTRY_PATH.read_text(encoding="utf-8")
    except OSError:
        return set()
    names: set[str] = set()
    for m in re.finditer(r'"([\w]+)"\s*:\s*"tools\.[\w]+:([\w]+)"', text):
        names.add(m.group(2))
    return names


def check_tool_direct_import() -> list[str]:
    """禁止经 ``from tools.* import <@tool>`` 直引绕过 tool_registry.get_tool()（C1 根因防回归）。

    批 2 已将六条挂载路径统一经 get_tool() 取用（含 subagent 直引、bridge 直引），
    本检查封死「未来新增工具时直接 import @tool 对象跳过观测包装」的回归面。
    合法例外：tool_registry.py 自身（用字符串延迟定位）、tests/、普通函数
    （如 check_knowledge_health 非 @tool，不在 TOOL_REGISTRY 故不命中）。
    """
    tool_names = _load_registry_tool_names()
    if not tool_names:
        return []
    violations: list[str] = []
    for py_file in ROOT.rglob("*.py"):
        rel = py_file.relative_to(ROOT).as_posix()
        if not rel.startswith("applications/"):
            continue
        if any(p in rel for p in (".venv", "__pycache__", ".ruff_cache", ".egg-info",
                                   ".codeartsdoer", ".codebuddy")):
            continue
        if "/tests/" in rel:
            continue
        if rel == "applications/agent_federation/agent/tool_registry.py":
            continue
        try:
            for lineno, line in enumerate(py_file.read_text(encoding="utf-8").splitlines(), 1):
                m = _DIRECT_IMPORT_PATTERN.match(line)
                if not m:
                    continue
                for part in m.group(1).split(","):
                    sym = part.strip().split(" as ")[0].strip()
                    if sym in tool_names:
                        violations.append(
                            f"{rel}:{lineno}: 直引 @tool '{sym}' 绕过 get_tool()"
                            f"（应经 tool_registry.get_tool 取用，否则缺失 tool 级事件）"
                        )
        except Exception:
            pass
    return violations


def main() -> int:
    rc = 0
    v1 = check()
    if v1:
        print("P4-2 架构约束违反：registry.execute() 仅允许经 delegate() 调用")
        print("白名单文件外的直接调用：")
        for v in v1:
            print(f"  {v}")
        rc = 1
    else:
        print("P4-2 架构约束通过：无白名单外 registry.execute() 调用")

    v2 = check_fastapi_apps()
    if v2:
        print("P2 架构约束违反：生产 FastAPI app 必须经 agent_core build_api_app 创建（裸 FastAPI( 不允许）")
        print("白名单外的裸构造：")
        for v in v2:
            print(f"  {v}")
        rc = 1
    else:
        print("P2 架构约束通过：无白名单外裸 FastAPI() 构造")
    v3 = check_toplevel_package_clashes()
    if v3:
        print("P5 架构约束违反：workspace 成员间顶层包名重复（editable .pth 全暴露，解析取决于安装顺序）")
        print("修复：重命名其中一方或将工具目录收进各自命名空间包（见 plan-workspace-toplevel-eval-disambiguation）：")
        for v in v3:
            print(f"  {v}")
        rc = 1
    else:
        print("P5 架构约束通过：无跨成员顶层包名冲突")

    v4 = check_tool_monitor_scatter()
    if v4:
        print("批 3 架构约束违反：app 层禁止裸调 monitor.report_tool*（散点埋点）")
        print("修复：工具经 tool_registry.get_tool() 取用，outcome 语义经 ToolResult 返回承载：")
        for v in v4:
            print(f"  {v}")
        rc = 1
    else:
        print("批 3 架构约束通过：无白名单外散点 tool 埋点")

    v5 = check_tool_direct_import()
    if v5:
        print("C1 回归面约束违反：经 from tools.* import <@tool> 直引绕过 get_tool()（观测断点）")
        print("修复：统一经 tool_registry.get_tool() 取用：")
        for v in v5:
            print(f"  {v}")
        rc = 1
    else:
        print("C1 回归面约束通过：无 @tool 直引旁路")
    return rc


if __name__ == "__main__":
    sys.exit(main())
