# -*- coding: utf-8 -*-
"""上传大小上限（P11：100MB · KS 侧唯一硬校验）单元测试。

钉四件事：
1. 上限内文件正常拷贝，返回写入字节数；
2. 超 1 字节即抛 UploadTooLarge（> 不是 ≥：恰好等于上限允许通过）；
3. 超限即停写：残留文件是**截断的前缀**，不是半截完整文件，且不抛一半再写一半；
4. 缺省 max_bytes = MAX_UPLOAD_BYTES = 100 MiB（P11 数值钉死——有人改这里必须过目）。
"""

from __future__ import annotations

import io

import pytest

from knowledge_service.utils.upload_limit import MAX_UPLOAD_BYTES, UploadTooLarge, copy_with_limit


def test_default_limit_is_100mib():
    """P11 数值钉死：100 MiB。改这个值 = 改拍板，必须显式过目而不是静默漂移。"""
    assert MAX_UPLOAD_BYTES == 100 * 1024 * 1024


def test_within_limit_copies_fully(tmp_path):
    src = io.BytesIO(b"hello world")
    dst = tmp_path / "a.pdf"
    written = copy_with_limit(src, str(dst), max_bytes=11)
    assert written == 11
    assert dst.read_bytes() == b"hello world"


def test_exactly_at_limit_passes(tmp_path):
    """> 判定：恰好等于上限合法（100MB 整文件必须传得上去）。"""
    payload = b"x" * 10
    dst = tmp_path / "a.pdf"
    assert copy_with_limit(io.BytesIO(payload), str(dst), max_bytes=10) == 10


def test_one_byte_over_raises_and_stops_writing(tmp_path):
    """超 1 字节即抛，且文件只含截断前缀（不假装拷贝成功、不继续写完整文件）。"""
    payload = b"x" * 11
    dst = tmp_path / "a.pdf"
    with pytest.raises(UploadTooLarge):
        copy_with_limit(io.BytesIO(payload), str(dst), max_bytes=10)
    assert dst.stat().st_size <= 10, "超限即停写（残留是截断前缀，不是完整半截）"
