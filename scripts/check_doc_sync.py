#!/usr/bin/env python3
"""文档同步防漂移 CI 脚本。

校验项目文档与代码/配置的一致性，在 CI 中拦截文档漂移。

校验项：
  1. AGENTS.md 目录表列出的路径是否存在
  2. README.md 安装命令一致性（uv sync --all-packages --extra dev）
  3. 文档中引用的 pyproject.toml 包名与实际一致
  4. ARCHITECTURE.md 目录树路径存在
  5. applications/*/pyproject.toml 包名与目录名匹配
  6. Makefile test session 数 == AGENTS.md 声称数
  7. agent_federation FastAPI title 一致性

用法：
  python scripts/check_doc_sync.py          # 校验，0=通过 1=有漂移
  python scripts/check_doc_sync.py --verbose # 详细输出
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

ERRORS: list[str] = []
WARNINGS: list[str] = []


def err(msg: str) -> None:
    ERRORS.append(msg)


def warn(msg: str) -> None:
    WARNINGS.append(msg)


def check_path_exists(doc: str, line_no: int, path_str: str, base: Path = REPO_ROOT) -> None:
    p = base / path_str
    if not p.exists():
        err(f"{doc}:{line_no}: 路径不存在 '{path_str}'")


def check_agents_md_paths() -> None:
    agents = REPO_ROOT / "AGENTS.md"
    if not agents.exists():
        err("AGENTS.md 不存在")
        return
    for i, line in enumerate(agents.read_text(encoding="utf-8").splitlines(), 1):
        m = re.match(r"\|\s*`([^`]+)`\s*\|", line)
        if m:
            path_str = m.group(1)
            if "/" in path_str and not path_str.startswith("http"):
                check_path_exists("AGENTS.md", i, path_str)


def check_readme_install_cmd() -> None:
    readme = REPO_ROOT / "README.md"
    if not readme.exists():
        err("README.md 不存在")
        return
    content = readme.read_text(encoding="utf-8")
    if "pip install -e " in content and "uv sync --all-packages" in content:
        for i, line in enumerate(content.splitlines(), 1):
            if "pip install -e " in line and "dev" in line:
                err(f"README.md:{i}: 安装命令不一致，应统一为 'uv sync --all-packages --extra dev'，实际为 '{line.strip()}'")


def check_pyproject_package_names() -> None:
    for pyproj in REPO_ROOT.rglob("pyproject.toml"):
        if ".venv" in str(pyproj) or "node_modules" in str(pyproj):
            continue
        try:
            data = tomllib.loads(pyproj.read_text(encoding="utf-8"))
        except Exception:
            continue
        project = data.get("project", {})
        name = project.get("name", "")
        if not name:
            continue
        parent = pyproj.parent
        if parent == REPO_ROOT:
            continue
        dir_name = parent.name
        expected_dir = name
        if dir_name != expected_dir and not (
            dir_name in {"agent-core", "agent-runtime", "shared-schemas"}
            or dir_name.endswith("-agent")
            or dir_name.endswith("-service")
            or dir_name.endswith("-framework")
            or dir_name == "agent_federation"
            or dir_name == "agent_server"
            or dir_name == "kefu-service"
            or dir_name == "nl2sql-service"
            or dir_name == "knowledge-service"
            or dir_name == "exhibition-agent"
        ):
            warn(f"{pyproj.relative_to(REPO_ROOT)}: 包名 '{name}' 与目录名 '{dir_name}' 不匹配")


def check_architecture_paths() -> None:
    arch = REPO_ROOT / "ARCHITECTURE.md"
    if not arch.exists():
        return
    in_code_block = False
    current_parent = ""
    for i, line in enumerate(arch.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            current_parent = ""
            continue
        # 反引号包裹的路径（如 `applications/agent_server/`）
        for m in re.finditer(r"`([^`]+/[^`]+)`", line):
            path_str = m.group(1)
            if path_str.startswith("http") or "." not in path_str.split("/")[-1]:
                if not path_str.endswith("/"):
                    continue
            if path_str.endswith("/"):
                check_path_exists("ARCHITECTURE.md", i, path_str)
        # 代码块内目录树路径（F1 增强：检测 applications/ packages/ 下子目录漂移）
        if in_code_block:
            m = re.search(r"[├└]──\s+(\S+)", line)
            if m:
                name = m.group(1)
                is_top_level = not line.startswith("│") and not line.startswith(" ")
                if is_top_level and name.endswith("/"):
                    current_parent = name
                elif current_parent in ("applications/", "packages/") and name.endswith("/"):
                    check_path_exists("ARCHITECTURE.md", i, current_parent + name)


def check_federation_title() -> None:
    server = REPO_ROOT / "applications/agent_federation/api/server.py"
    if not server.exists():
        return
    content = server.read_text(encoding="utf-8")
    if 'title="DeepAgents API"' in content:
        err("agent_federation/api/server.py: FastAPI title 仍为 'DeepAgents API'，应为 'agent_federation API'")


def check_session_count() -> None:
    makefile = REPO_ROOT / "Makefile"
    agents = REPO_ROOT / "AGENTS.md"
    if not makefile.exists() or not agents.exists():
        return

    mk_content = makefile.read_text(encoding="utf-8")
    in_test = False
    mk_sessions = 0
    for line in mk_content.splitlines():
        if line.startswith("test:"):
            in_test = True
            continue
        if in_test:
            if line.startswith("\tuv run pytest "):
                mk_sessions += 1
            elif line and not line.startswith("\t") and not line.startswith("#"):
                in_test = False

    agents_content = agents.read_text(encoding="utf-8")
    declared = set()
    for m in re.finditer(r"(\d+)\s*(?:个\s*)?pytest\s*session", agents_content):
        declared.add(int(m.group(1)))
    for m in re.finditer(r"(\d+)\s*session\s*pytest", agents_content):
        declared.add(int(m.group(1)))
    for m in re.finditer(r"全量\s*(\d+)\s*session", agents_content):
        declared.add(int(m.group(1)))

    if mk_sessions == 0:
        warn("Makefile: 未找到 test session 行")
        return

    if declared and mk_sessions not in declared:
        err(f"session 数不一致: Makefile 有 {mk_sessions} 个 session，AGENTS.md 声称 {sorted(declared)}")
    elif not declared:
        warn("AGENTS.md: 未找到 session 数声明")


def main() -> bool:
    verbose = "--verbose" in sys.argv

    check_agents_md_paths()
    check_readme_install_cmd()
    check_pyproject_package_names()
    check_architecture_paths()
    check_federation_title()
    check_session_count()

    if WARNINGS:
        if verbose:
            print(f"\n⚠️  {len(WARNINGS)} 个警告：")
            for w in WARNINGS:
                print(f"  {w}")
        else:
            print(f"⚠️  {len(WARNINGS)} 个警告（--verbose 查看）")

    if ERRORS:
        print(f"\n❌ {len(ERRORS)} 个文档漂移：")
        for e in ERRORS:
            print(f"  {e}")
        return False

    print(f"✅ 文档同步校验通过（{len(WARNINGS)} 警告）")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
