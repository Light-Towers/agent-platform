# -*- coding: utf-8 -*-
"""prompt 加载与渲染用例（#116：缓存键含文件身份，恢复热改能力）。

**背景**：`load_prompt` 此前用 `lru_cache(maxsize=None)`——只按参数名缓存，
改 prompt 文件不重启不生效（热改能力被悄悄取消，线上改 prompt 像没生效一样）。
修法：缓存键从"参数名"改为"(mtime_ns, size)"——内容变才重读，不变不读。

另钉 render 的白名单槽位语义（#108 立的规矩不回归）：字面花括号与未知槽位
原样保留，渲染永不因模板内容抛异常。
"""

from __future__ import annotations

import os

import pytest
from nl2sql_service.agent.nodes import _prompt
from nl2sql_service.agent.nodes._prompt import load_prompt, render


@pytest.fixture
def prompt_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(_prompt, "_PROMPT_DIR", tmp_path)
    _prompt._PROMPT_CACHE.clear()
    yield tmp_path
    _prompt._PROMPT_CACHE.clear()


def test_loads_file(prompt_dir):
    (prompt_dir / "generate_sql").write_text("SELECT 模板", encoding="utf-8")
    assert load_prompt("generate_sql") == "SELECT 模板"


def test_cached_when_unchanged(prompt_dir):
    (prompt_dir / "generate_sql").write_text("v1", encoding="utf-8")
    assert load_prompt("generate_sql") == "v1"
    # 同身份二次加载走缓存（不改文件 ⇒ 不重读；直接改缓存值验证命中）
    _prompt._PROMPT_CACHE["generate_sql"] = ((1, 2), "来自缓存")
    (prompt_dir / "generate_sql").write_text("v2", encoding="utf-8")
    # ns=(atime_ns, mtime_ns)——身份撞缓存键 ((1,2)) ⇒ 命中缓存不重读
    os.utime(prompt_dir / "generate_sql", ns=(0, 1))
    assert load_prompt("generate_sql") == "来自缓存"


def test_hot_reload_on_content_change(prompt_dir):
    """#116 本体：改文件内容 ⇒ 下次加载拿到新内容（不等重启）。"""
    path = prompt_dir / "correct_sql"
    path.write_text("v1", encoding="utf-8")
    assert load_prompt("correct_sql") == "v1"
    path.write_text("v2 改过的模板", encoding="utf-8")
    # 显式推 mtime：文件系统 mtime 粒度不保证 ns 级差异，测试不能靠"写完自然变"
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    assert load_prompt("correct_sql") == "v2 改过的模板"


def test_missing_file_returns_fallback(prompt_dir):
    assert load_prompt("no_such_prompt", fallback="降级模板") == "降级模板"
    assert load_prompt("no_such_prompt") == ""


def test_render_whitelist_slots_and_literal_braces():
    """#108 语义不回归：白名单槽位替换；字面花括号/未知槽位原样保留。"""
    template = '问：{query} 字面 {"sql": 1} 未知 {unknown_slot}'
    assert render(template, query="销售") == '问：销售 字面 {"sql": 1} 未知 {unknown_slot}'


def test_render_missing_value_renders_empty():
    assert render("值：{query}", query="") == "值："
