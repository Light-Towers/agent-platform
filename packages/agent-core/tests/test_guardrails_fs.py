# -*- coding: utf-8 -*-
"""路径安全护栏（CodeQL py/path-injection 收口）单元测试。

覆盖内核 ``agent_core.guardrails.fs`` 三个入口的契约边界：
- ``safe_join``：拼接语义，绝对片段 / ``..`` / NUL / 空一律拒绝；
- ``resolve_within``：解析语义，绝对入口宽容但结果必须仍在 base 内；
- ``safe_filename``：文件名净化，剥离目录成分与非法字符。

另含四条安全属性断言：异常消息不回带入参原文（防经 ``detail=str(e)`` 外泄）、
服务端日志不落任何路径文本（入参原文与部署绝对路径都不落）、明显越界的输入不进入
``resolve()``、符号链接逃逸被拒（POSIX；Windows 建软链需特权，故跳过）。

**跨平台契约**：Windows 绝对/穿越形式（``C:\\`` / ``..\\`` / UNC）的用例在两个宿主
都必须被拒——``pathlib`` 只认宿主分隔符，这些用例是 CI 的 Linux runner 实测拦住
宿主依赖写法后补上的，故不得改成 ``skipif`` 只跑一边。
"""

import logging
import os
import sys
from pathlib import Path

import pytest

from agent_core.guardrails.fs import (
    PathTraversalError,
    resolve_within,
    safe_filename,
    safe_join,
)

# ---------------------------------------------------------------------------
# safe_join：正常拼接
# ---------------------------------------------------------------------------


def test_safe_join_returns_child_of_base(tmp_path):
    result = safe_join(tmp_path, "session_user-abc", "report.md")
    assert result == (tmp_path / "session_user-abc" / "report.md").resolve()
    assert result.is_relative_to(tmp_path.resolve())


def test_safe_join_accepts_nested_relative_fragment(tmp_path):
    result = safe_join(tmp_path, "sub/dir/file.txt")
    assert result.is_relative_to(tmp_path.resolve())


def test_safe_join_without_parts_returns_base(tmp_path):
    assert safe_join(tmp_path) == tmp_path.resolve()


def test_safe_join_tolerates_relative_base(tmp_path, monkeypatch):
    """base 传相对路径时先 resolve，不因 cwd 语义产生假越界。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "out").mkdir()
    assert safe_join("out", "a.txt") == (tmp_path / "out" / "a.txt").resolve()


# ---------------------------------------------------------------------------
# safe_join：拒绝面
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fragment",
    [
        "../secret.txt",
        "../../etc/passwd",
        "a/../../secret.txt",
        "..\\..\\win.ini",
        os.path.join("..", "..", "escape"),
    ],
)
def test_safe_join_rejects_traversal(tmp_path, fragment):
    with pytest.raises(PathTraversalError):
        safe_join(tmp_path, fragment)


@pytest.mark.parametrize(
    "fragment",
    [
        "/etc/passwd",
        "C:\\Windows\\win.ini",
        "C:/Windows/win.ini",
        "\\\\server\\share\\x",
    ],
)
def test_safe_join_rejects_absolute_fragment(tmp_path, fragment):
    """绝对形式按**两套**分隔符判，不随部署宿主变（POSIX 的 ``Path`` 不认盘符与反斜杠）。"""
    with pytest.raises(PathTraversalError):
        safe_join(tmp_path, fragment)


def test_safe_join_rejects_even_benign_double_dot(tmp_path):
    """``..`` 片段一律拒绝（比"解析后仍在 base 内"更严），调用方须先归一化。"""
    (tmp_path / "a").mkdir()
    with pytest.raises(PathTraversalError):
        safe_join(tmp_path, "a/../b.txt")


@pytest.mark.parametrize("fragment", ["", "a\x00b"])
def test_safe_join_rejects_empty_or_nul(tmp_path, fragment):
    with pytest.raises(PathTraversalError):
        safe_join(tmp_path, fragment)


def test_safe_join_error_message_does_not_leak_input(tmp_path):
    """异常消息不含入参原文，避免被 ``detail=str(e)`` 之类写法带进出站响应。"""
    secretish = tmp_path.parent / "topsecret.txt"
    with pytest.raises(PathTraversalError) as excinfo:
        safe_join(tmp_path, os.path.relpath(secretish, tmp_path))
    assert "topsecret" not in str(excinfo.value)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows 建符号链接需特权/开发者模式")
def test_safe_join_rejects_symlink_escape(tmp_path):
    """base 内软链指向外部：resolve 后落在 base 外，必须被拒。"""
    outside = tmp_path.parent / f"outside_{tmp_path.name}"
    outside.mkdir()
    link = tmp_path / "escape_link"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(PathTraversalError):
        safe_join(tmp_path, "escape_link", "x.txt")


# ---------------------------------------------------------------------------
# resolve_within：解析语义（对外契约兼容面）
# ---------------------------------------------------------------------------


def test_resolve_within_accepts_relative_input(tmp_path):
    (tmp_path / "sub").mkdir()
    assert resolve_within(tmp_path, "sub/a.txt") == (tmp_path / "sub" / "a.txt").resolve()


def test_resolve_within_accepts_absolute_input_inside_base(tmp_path):
    """既有消费者把 ``/api/files`` 返回的绝对路径原样传回，故绝对入口须被接受。"""
    target = tmp_path / "out.txt"
    target.write_text("x", encoding="utf-8")
    assert resolve_within(tmp_path, str(target)) == target.resolve()


@pytest.mark.parametrize(
    "user_path",
    [
        "/etc/passwd",
        "C:\\Windows\\win.ini",
        "../outside.txt",
        "..\\..\\outside.txt",
        "sub/../../outside.txt",
        "",
        "   ",
        "a\x00b",
    ],
)
def test_resolve_within_rejects_outside_or_invalid(tmp_path, user_path):
    with pytest.raises(PathTraversalError):
        resolve_within(tmp_path, user_path)


def test_resolve_within_allows_benign_double_dot_inside_base(tmp_path):
    """与 safe_join 的分工：解析语义下只要结果在 base 内即放行。"""
    (tmp_path / "a").mkdir()
    assert resolve_within(tmp_path, "a/../b.txt") == (tmp_path / "b.txt").resolve()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows 建符号链接需特权/开发者模式")
def test_resolve_within_rejects_symlink_escape(tmp_path):
    outside = tmp_path.parent / f"outside_rw_{tmp_path.name}"
    outside.mkdir()
    (outside / "secret.txt").write_text("s", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(PathTraversalError):
        resolve_within(tmp_path, "link/secret.txt")


def test_resolve_within_is_subclass_of_value_error():
    """宿主既有 ``except ValueError`` 仍能兜住，不因新异常类型漏网。"""
    assert issubclass(PathTraversalError, ValueError)


# ---------------------------------------------------------------------------
# safe_filename
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("report.md", "report.md"),
        ("月度 总结 v2.xlsx", "月度 总结 v2.xlsx"),
        ("a/b/c.txt", "c.txt"),
        ("..\\..\\windows\\win.ini", "win.ini"),
        ("C:\\Windows\\System32\\cmd.exe", "cmd.exe"),
        ("/etc/passwd", "passwd"),
        ("we<i>rd:na?me|x.txt", "we_i_rd_na_me_x.txt"),
    ],
)
def test_safe_filename_strips_directory_and_illegal_chars(raw, expected):
    assert safe_filename(raw) == expected


@pytest.mark.parametrize("raw", [".", "..", "", None])
def test_safe_filename_normalizes_dangerous_basics(raw):
    assert safe_filename(raw) == "_"


def test_safe_filename_output_is_single_path_fragment(tmp_path):
    """净化结果恒为单个片段（无目录成分），可安全喂给 ``safe_join``。"""
    for name in ("../../a.txt", "sub/dir.md", "..", ".hidden", "C:\\x\\y.log"):
        cleaned = safe_filename(name)
        assert "/" not in cleaned and "\\" not in cleaned and os.sep not in cleaned
    # 净化 + 拼接双重防护：即使原始入参是穿越式路径，落点仍在 base 内
    escaped = safe_join(tmp_path, safe_filename("../../etc/passwd"))
    assert escaped == (tmp_path / "passwd").resolve()


# ---------------------------------------------------------------------------
# 日志信息最小化与守卫顺序（Batch 7：真修而非 dismiss）
# 实证结论：只去掉 base 后两处仍被告警，说明被判 secret 的是入参本身（路径里常含
# 凭证派生的会话目录名），故契约从「留痕含原文」改为「不落任何路径文本」。
# ---------------------------------------------------------------------------


class _RecordingHandler(logging.Handler):
    """直接挂到模块 logger：``agent_core.logging`` 可能关掉 propagate，caplog 不可靠。"""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@pytest.fixture
def fs_logs():
    from agent_core.guardrails import fs as fs_mod

    handler = _RecordingHandler()
    fs_mod.logger.addHandler(handler)
    yield handler
    fs_mod.logger.removeHandler(handler)


def test_reject_log_keeps_reason_but_drops_path_text(tmp_path, fs_logs):
    """拒绝日志只留原因与结构摘要：部署基准目录与入参原文都不落（官方口径：敏感数据不应写日志）。"""
    with pytest.raises(PathTraversalError):
        resolve_within(tmp_path, "/etc/passwd")
    blob = " ".join(fs_logs.messages)
    assert str(tmp_path.resolve()) not in blob
    assert "etc/passwd" not in blob
    # 仍可区分与关联：拒绝原因 + 不携带原文的数值型摘要
    assert "路径越出基准目录" in blob
    assert "len=" in blob


def test_ensure_within_log_drops_resolved_absolute_path(tmp_path, fs_logs):
    """解析后落在 base 外时，既不打拼出来的绝对路径，也不打入参原文。"""
    (tmp_path / "a").mkdir()
    with pytest.raises(PathTraversalError):
        resolve_within(tmp_path, "a/../../outside.txt")
    blob = " ".join(fs_logs.messages)
    assert str(tmp_path.resolve()) not in blob
    assert "outside.txt" not in blob
    assert "len=" in blob


def test_lexical_escape_rejected_before_touching_filesystem(tmp_path, monkeypatch):
    """词法 containment 前置：明显越界的输入不得进入 ``resolve()``。"""
    resolved_calls: list[str] = []
    real_resolve = Path.resolve

    def spy(self, *args, **kwargs):
        resolved_calls.append(str(self))
        return real_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", spy)
    with pytest.raises(PathTraversalError):
        resolve_within(tmp_path, "/etc/passwd")
    # base 自身的规范化允许（那是服务端目录，非用户输入）；用户输入不得被解析
    assert not any("passwd" in c for c in resolved_calls)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows 建符号链接需特权/开发者模式")
def test_symlink_escape_still_rejected_after_lexical_guard(tmp_path):
    """词法上安全（base 内软链）的输入仍须被解析后的复检拒掉——前置守卫不得放宽接受集。"""
    outside = tmp_path.parent / f"outside_lex_{tmp_path.name}"
    outside.mkdir()
    (outside / "secret.txt").write_text("x", encoding="utf-8")
    (tmp_path / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PathTraversalError):
        resolve_within(tmp_path, "link/secret.txt")
