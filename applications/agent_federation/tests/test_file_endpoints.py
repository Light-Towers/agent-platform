"""A 类 ``py/path-injection`` 收口：federation 文件端点的越界拒绝与出站脱敏回归测试。

覆盖 Batch 3 改动的 4 个端点（upload / download / files 列目录）：所有路径校验必须
经 kernel ``agent_core.guardrails.fs``，越界一律 403，出站文案固定不回显异常原文。

直接调用路由处理函数而非经 TestClient：本批变更全在 handler 的路径校验逻辑里，
而 ``api.server`` 的中间件装配取决于**模块导入时**的 ``API_KEY`` / ``DISABLE_AUTH``
env（本机环境会漂移），鉴权组合另由 ``test_auth.py`` 覆盖。

注意：``api.server`` 顶层 ``from agent.main_agent import run_deep_agent``（其模块级构造
model），故沿用 ``tests/unit/test_tool_registry.py`` 已验证的做法：导入前注入 dummy
LLM env。不用 sys.modules 替身——那会让同 session 内后续用例拿到假 ``agent.main_agent``。
"""

import asyncio
import io
import os
from pathlib import Path

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("OPENAI_BASE_URL", "http://localhost:9999/v1")

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.responses import FileResponse

from api import server  # noqa: E402


@pytest.fixture
def fs_roots(tmp_path, monkeypatch):
    """把服务端基准目录指向 tmp_path，避免污染仓库 ``output/`` / ``updated/``。"""
    out = tmp_path / "output"
    out.mkdir()
    updated = tmp_path / "updated"
    updated.mkdir()
    monkeypatch.setattr(server, "output_dir", out)
    monkeypatch.setattr(server, "updated_dir", updated)
    return out, updated


def _upload(filename: str, payload: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(payload), filename=filename)


# ---------------------------------------------------------------------------
# /api/download
# ---------------------------------------------------------------------------


def test_download_accepts_relative_path_inside_base(fs_roots):
    out, _ = fs_roots
    target = out / "sub"
    target.mkdir()
    f = target / "report.md"
    f.write_text("hi", encoding="utf-8")
    resp = asyncio.run(server.download_file(f"sub/{f.name}"))
    assert isinstance(resp, FileResponse)
    assert Path(resp.path) == f.resolve()


def test_download_accepts_absolute_path_inside_base(fs_roots):
    """契约兼容：``/api/files`` 回传的是绝对路径，``resolve_within`` 必须放行 base 内绝对入口。"""
    out, _ = fs_roots
    f = out / "a.txt"
    f.write_text("x", encoding="utf-8")
    resp = asyncio.run(server.download_file(str(f)))
    assert Path(resp.path) == f.resolve()


@pytest.mark.parametrize(
    "user_path",
    [
        "../secret.txt",
        "sub/../../secret.txt",
    ],
)
def test_download_rejects_traversal(fs_roots, tmp_path, user_path):
    out, _ = fs_roots
    (tmp_path / "secret.txt").write_text("topsecret", encoding="utf-8")
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(server.download_file(user_path))
    assert excinfo.value.status_code == 403
    assert "topsecret" not in str(excinfo.value.detail)


def test_download_rejects_absolute_path_outside_base(fs_roots, tmp_path):
    out, _ = fs_roots
    outside = tmp_path.parent / f"outside_{tmp_path.name}.txt"
    outside.write_text("nope", encoding="utf-8")
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(server.download_file(str(outside)))
    assert excinfo.value.status_code == 403


@pytest.mark.parametrize("user_path", ["", "   ", "a\x00b"])
def test_download_rejects_empty_or_nul_path(fs_roots, user_path):
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(server.download_file(user_path))
    assert excinfo.value.status_code == 403


def test_download_missing_file_returns_404(fs_roots):
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(server.download_file("not-there.md"))
    assert excinfo.value.status_code == 404


def test_download_directory_returns_404(fs_roots):
    """目录不被当作文件回传（旧实现 ``exists()`` 判定会放行目录）。"""
    out, _ = fs_roots
    (out / "adir").mkdir()
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(server.download_file("adir"))
    assert excinfo.value.status_code == 404


# ---------------------------------------------------------------------------
# /api/files
# ---------------------------------------------------------------------------


def test_list_files_returns_entries_under_base(fs_roots):
    out, _ = fs_roots
    sub = out / "session_user-x"
    sub.mkdir()
    (sub / "a.md").write_text("1", encoding="utf-8")
    (out / "b.md").write_text("2", encoding="utf-8")
    result = asyncio.run(server.list_files("."))
    names = sorted(f["name"] for f in result["files"])
    assert names == ["a.md", "b.md"]
    base = out.resolve()
    for entry in result["files"]:
        assert Path(entry["path"]).resolve().is_relative_to(base)


def test_list_files_rejects_escape(fs_roots, tmp_path):
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(server.list_files("../"))
    assert excinfo.value.status_code == 403
    assert str(tmp_path) not in str(excinfo.value.detail)


def test_list_files_missing_dir_returns_404(fs_roots):
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(server.list_files("nope"))
    assert excinfo.value.status_code == 404


def test_list_files_error_detail_is_fixed_text(fs_roots, monkeypatch):
    """目录列举中途异常（竞态/权限等）：固定文案，不回显 ``str(e)``。"""
    out, _ = fs_roots
    target = out / "listing"
    target.mkdir()

    def _boom(*args, **kwargs):
        raise OSError("disk on fire /home/secret/path")

    monkeypatch.setattr(Path, "rglob", lambda self, pattern: _boom())
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(server.list_files("listing"))
    assert excinfo.value.status_code == 500
    assert excinfo.value.detail == "文件列表读取失败"
    assert "secret" not in str(excinfo.value.detail)


# ---------------------------------------------------------------------------
# /api/upload
# ---------------------------------------------------------------------------


def test_upload_sanitizes_traversal_filename(fs_roots, tmp_path, monkeypatch):
    """上传文件名含穿越：净化后落在会话目录内，仓库外零落盘。"""
    _, updated = fs_roots
    monkeypatch.setattr(server, "resolve_thread_id", lambda client_id: client_id or "dev")
    result = asyncio.run(
        server.upload_files([_upload("../../etc/passwd", b"boom")], thread_id="user-x")
    )
    assert result["status"] == "uploaded"
    assert result["files"] == ["passwd"]
    assert (updated / "session_user-x" / "passwd").read_bytes() == b"boom"
    assert not (tmp_path / "etc").exists()
    assert not (tmp_path.parent / "etc").exists()


def test_upload_keeps_illegal_chars_replaced(fs_roots, monkeypatch):
    _, updated = fs_roots
    monkeypatch.setattr(server, "resolve_thread_id", lambda client_id: client_id or "dev")
    result = asyncio.run(
        server.upload_files([_upload('we<i>rd:na?me.txt', b"ok")], thread_id="user-x")
    )
    assert result["files"] == ["we_i_rd_na_me.txt"]
    assert (updated / "session_user-x" / "we_i_rd_na_me.txt").read_bytes() == b"ok"


def test_upload_escapable_thread_id_stays_in_updated_dir(fs_roots, tmp_path, monkeypatch):
    """客户端可控 thread_id 含穿越：会话目录名净化后仍在 ``updated/`` 内。"""
    _, updated = fs_roots
    monkeypatch.setattr(server, "resolve_thread_id", lambda client_id: client_id or "dev")
    result = asyncio.run(
        server.upload_files([_upload("a.txt", b"x")], thread_id="../../escape")
    )
    assert result["status"] == "uploaded"
    assert list(updated.glob("session_escape/a.txt"))
    assert not (tmp_path / "escape").exists()
    assert not (tmp_path.parent / "escape").exists()
