"""F-S1-03 防复发守卫：memory/__init__.py 模块级禁止硬依赖 langgraph / langchain_core。

背景（审核 N5）：红线 3「内核零宿主依赖」。2026-09-21 已把 memory/__init__.py 的
MongoCheckpointer 惰性化（__getattr__ + 函数内 import），但 CI 环境恒装 langgraph，
若有人加回模块级 import，运行时不会报警，P0 会静默复发。

本测试用 AST 静态扫描（零运行时依赖，任何环境可跑）：
- 禁止模块级 import langgraph* / langchain*；
- 禁止模块级 import 可选子模块 agent_core.memory.mongo_checkpointer
  （其基类 BaseCheckpointSaver 需要 langgraph，导入即硬依赖）。
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

_FORBIDDEN_MODULE_PREFIXES = ("langgraph", "langchain")
_FORBIDDEN_MODULES = {"agent_core.memory.mongo_checkpointer", "mongo_checkpointer"}


def _memory_init_path() -> Path:
    spec = importlib.util.find_spec("agent_core.memory")
    assert spec is not None and spec.origin, "无法定位 agent_core.memory"
    return Path(spec.origin)


def _iter_module_level_import_modules(tree: ast.Module):
    """产出 __init__.py 模块级（ast 直接子节点）import 的模块名。

    仅扫描 ast.Module 顶层语句，函数/类体内的 import（惰性导入）不在守卫范围。
    """
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            yield node.module or ""


def test_memory_init_module_level_imports_are_lazy_safe():
    """memory/__init__.py 模块级 import 不得引入 langgraph/langchain_core/mongo_checkpointer。"""
    tree = ast.parse(_memory_init_path().read_text(encoding="utf-8"))
    for module in _iter_module_level_import_modules(tree):
        assert not module.startswith(_FORBIDDEN_MODULE_PREFIXES), (
            f"红线 3 违规：agent_core/memory/__init__.py 模块级 import 了 {module!r}；"
            "langgraph/langchain_core 必须保持函数内惰性导入（F-S1-03 回归守卫）"
        )
        assert module not in _FORBIDDEN_MODULES, (
            f"红线 3 违规：memory/__init__.py 模块级 import 了可选模块 {module!r}，"
            "会连带硬依赖 langgraph；请改用 __getattr__ 惰性入口或函数内 import"
        )


def test_importing_memory_pulls_no_heavy_deps():
    """子进程隔离验证：import agent_core.memory 后 sys.modules 无 langgraph/langchain/可选子模块。

    比 AST 扫描更强的**传递依赖**守卫（审核建议）：即便某个子模块（base/backend/semantic…）
    日后新增模块级 langgraph import，本断言也会失败。子进程确保不受同套件其他测试
    已导入的重型依赖污染。
    """
    code = (
        "import sys, agent_core.memory; "
        "bad = [m for m in sys.modules "
        "if m.startswith(('langgraph', 'langchain')) "
        "or m == 'agent_core.memory.mongo_checkpointer']; "
        "assert not bad, f'import agent_core.memory 拉起了重型依赖: {bad}'"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"子进程断言失败（红线 3：import agent_core.memory 不得拉起 langgraph/langchain）：\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
