# -*- coding: utf-8 -*-
"""hot_text 单测：内容变即重读、缺失回退、符号链接切换（模拟 CM ..data）。"""
from __future__ import annotations

import os
import pytest

from agent_core.hot_text import clear_hot_text_cache, load_hot_text


def test_reloads_on_content_change(tmp_path):
    clear_hot_text_cache()
    p = tmp_path / "prompt.txt"
    p.write_text("v1", encoding="utf-8")
    assert load_hot_text(p, "fallback") == "v1"

    p.write_text("v2-change", encoding="utf-8")
    assert load_hot_text(p, "fallback") == "v2-change"


def test_missing_returns_fallback(tmp_path):
    clear_hot_text_cache()
    assert load_hot_text(tmp_path / "missing.txt", "FB") == "FB"


@pytest.mark.skipif(
    not hasattr(os, "symlink") or os.name == "nt",
    reason="Windows 开发环境无 symlink 特权；Linux(CI/生产)才跑这条",
)
def test_symlink_switch_reloads(tmp_path):
    """模拟 ConfigMap volume：符号链接指向 ..data 目录里的真实文件，切换即生效。"""
    clear_hot_text_cache()
    d1 = tmp_path / "..2026_01_01"
    d1.mkdir()
    f1 = d1 / "prompt.txt"
    f1.write_text("old-prompt", encoding="utf-8")

    link = tmp_path / "prompt.txt"
    link.symlink_to(f1)
    assert load_hot_text(link, "") == "old-prompt"

    # kubelet 换目标文件（新目录 + 重指向），内容/尺寸可能相同也要感知（靠 inode）
    d2 = tmp_path / "..2026_01_02"
    d2.mkdir()
    f2 = d2 / "prompt.txt"
    f2.write_text("new-prompt", encoding="utf-8")
    tmp_link = tmp_path / "..data_tmp"
    tmp_link.symlink_to(d2, target_is_directory=True)
    os.replace(tmp_link, tmp_path / "..data") if (tmp_path / "..data").exists() else tmp_link.rename(tmp_path / "..data")
    # 直接重指向测试文件（简化：真实 CM 是 ..data 目录符号链接，这里等价验证 inode 变化）
    os.unlink(link)
    link.symlink_to(f2)
    assert load_hot_text(link, "") == "new-prompt"


def test_same_content_uses_cache(tmp_path):
    clear_hot_text_cache()
    p = tmp_path / "p.txt"
    p.write_text("stable", encoding="utf-8")
    assert load_hot_text(p, "") == "stable"
    st = p.stat()
    os.utime(p, (st.st_atime, st.st_mtime))  # 内容/mtime 不变
    assert load_hot_text(p, "") == "stable"
