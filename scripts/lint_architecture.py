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
    "applications/kefu-service/tests/",
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


def main() -> int:
    violations = check()
    if violations:
        print("P4-2 架构约束违反：registry.execute() 仅允许经 delegate() 调用")
        print("白名单文件外的直接调用：")
        for v in violations:
            print(f"  {v}")
        return 1
    print("P4-2 架构约束通过：无白名单外 registry.execute() 调用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
