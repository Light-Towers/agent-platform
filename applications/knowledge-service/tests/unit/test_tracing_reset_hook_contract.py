# -*- coding: utf-8 -*-
"""shim 重导出契约：``_reset_for_tests`` 必须能从 ks 旧路径解析到。

背景（2026-10-03 B7b 收尾定性，见 docs/TODO.md §5 与 CHANGELOG「B7b 收尾衍生项」）：
``tests/unit/test_tracing.py`` 的 autouse fixture 以 ``tracing._reset_for_tests()``
形式调用 kernel 的**私有**测试钩子，而该名字能进 shim 命名空间，靠的是

    knowledge_service/core/tracing.py  →  ``from agent_core.tracing import *``
    agent_core/tracing.py             →  ``__all__`` 里显式列举了 ``"_reset_for_tests"``

这条链条全仓原先**没有任何用例钉住**。一旦有人「清理」掉 ``__all__`` 里的私有项，
或在 shim 改成显式再导出，``test_tracing.py`` 的 15 条用例会在 **setup 阶段整片
error**（AttributeError 被 pytest 报成 fixture 错，堆栈不指向本契约），排查成本
与现象严重不符——本文件就是把这个「静默断裂点」变成一条直白失败的断言。

判据只增不减：本文件不碰产品代码，且**与 OTel SDK 是否在场所无关**（两种 extras
形态都必须通过，见 testing-playbook §2.2）。
"""

import ast
from pathlib import Path

import pytest
from agent_core import tracing as kernel_tracing

from knowledge_service.core import tracing as shim_tracing

# .../unit/test_x.py → parents[4] = monorepo 根（_SHIM_REL 等路径均相对仓库根）
_REPO_ROOT = Path(__file__).resolve().parents[4]
_SHIM_REL = "applications/knowledge-service/knowledge_service/core/tracing.py"


def test_kernel_all_declares_the_private_test_hook():
    """``import *`` 只搬运 ``__all__`` 列出的名字 ⇒ 私有钩子必须显式在册。"""
    assert "_reset_for_tests" in kernel_tracing.__all__


def test_shim_reexports_the_same_object_as_kernel():
    """shim 解析到的必须是 kernel 的**同一个**函数对象，不是本地同名替身。"""
    hook = getattr(shim_tracing, "_reset_for_tests", None)
    assert hook is not None, "shim 未重导出 _reset_for_tests，test_tracing.py 将整片 setup error"
    assert hook is kernel_tracing._reset_for_tests


def test_hook_is_callable_and_idempotent():
    """钩子本体可调用且重复调用不抛（它是 fixture 的前后置各一次必经路径）。"""
    shim_tracing._reset_for_tests()
    shim_tracing._reset_for_tests()
    assert kernel_tracing.get_tracing_status()["status"] == "UNINITIALIZED"


def test_shim_declares_star_reexport():
    """回归锁：shim 若被改成「只有显式再导出块」，本契约即失效，必须在此处立刻红。

    剥掉 ``import *`` 的两种未来改法都要落到本断言上——那时 ``_reset_for_tests``
    需要被显式加进 shim 的再导出列表，而不是等到 ks 套件整片 error 才发现。
    """
    src = (_REPO_ROOT / _SHIM_REL).read_text(encoding="utf-8-sig")
    tree = ast.parse(src, filename=_SHIM_REL)
    # star import 在 AST 里是 ``alias(name="*")``（不是 ast.Starred，那用于赋值左侧解包）
    star_imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "agent_core.tracing"
        and any(a.name == "*" for a in node.names)
    ]
    assert star_imports, f"{_SHIM_REL} 已不再 ``from agent_core.tracing import *``"


def test_tracing_suite_fixture_depends_on_the_hook():
    """契约的消费方确实还在用这个钩子（避免「用例守着一个没人调的名字」的空转）。"""
    suite = _REPO_ROOT / "applications/knowledge-service/tests/unit/test_tracing.py"
    tree = ast.parse(suite.read_text(encoding="utf-8-sig"), filename=suite.name)
    users = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(sub, ast.Attribute) and sub.attr == "_reset_for_tests"
            for sub in ast.walk(node)
        )
    ]
    assert "_reset_tracing" in users


@pytest.mark.parametrize("public_name", ["init_tracing", "get_tracer", "force_flush"])
def test_shim_still_reexports_public_api(public_name):
    """顺带兜住公共面：shim 的老 import 路径不得因治理改动而退化。"""
    assert getattr(shim_tracing, public_name) is getattr(kernel_tracing, public_name)
