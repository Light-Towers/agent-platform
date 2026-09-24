"""ToolResultCompressor 单元测试：头尾截断 + 关键字段 + 外置引用。"""

from __future__ import annotations

import json

import pytest

from agent_runtime.context.tool_result import (
    ToolResultCompressor,
    is_tool_result_ref,
    normalize_result,
    read_tool_result,
)


def test_normalize_result_none():
    assert normalize_result(None) == ""


def test_normalize_result_string():
    assert normalize_result("hello") == "hello"


def test_normalize_result_dict():
    result = normalize_result({"a": 1, "b": 2})
    assert json.loads(result) == {"a": 1, "b": 2}


def test_normalize_result_list():
    result = normalize_result([1, 2, 3])
    assert json.loads(result) == [1, 2, 3]


def test_normalize_result_object():
    class Obj:
        def __str__(self):
            return "obj_str"
    assert normalize_result(Obj()) == "obj_str"


def test_compress_under_threshold():
    c = ToolResultCompressor(max_tokens=9999)
    out = c.compress("short result")
    assert out["truncated"] is False
    assert out["text"] == "short result"
    assert out["ref"] == ""


def test_compress_over_threshold_string():
    c = ToolResultCompressor(max_tokens=1)
    long_text = "x" * 5000
    out = c.compress(long_text)
    assert out["truncated"] is True
    assert out["ref"] != ""
    assert "[完整结果已外置" in out["text"]
    assert "省略" in out["text"]


def test_compress_over_threshold_list():
    c = ToolResultCompressor(max_tokens=1)
    data = [{"id": i, "name": f"item_{i}"} for i in range(100)]
    out = c.compress(data)
    assert out["truncated"] is True
    assert "其余" in out["text"] or "省略" in out["text"]


def test_compress_empty_result():
    c = ToolResultCompressor(max_tokens=100)
    out = c.compress("")
    assert out["text"] == ""
    assert out["truncated"] is False


def test_compress_writes_to_store_dir(tmp_path):
    c = ToolResultCompressor(max_tokens=1, store_dir=tmp_path)
    out = c.compress("x" * 5000)
    assert out["truncated"] is True
    assert out["full_path"] != ""
    content = read_tool_result(out["ref"], tmp_path)
    assert content == "x" * 5000


def test_read_tool_result_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_tool_result("nonexistent_ref", tmp_path)


def test_is_tool_result_ref_valid():
    assert is_tool_result_ref("tool_result_abcdef123456_abc123") is True


def test_is_tool_result_ref_invalid():
    assert is_tool_result_ref("not_a_ref") is False
    assert is_tool_result_ref("tool_result_short_abc") is False
    assert is_tool_result_ref("") is False
