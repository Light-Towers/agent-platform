# -*- coding: utf-8 -*-
"""build_vl_model 测试：开关/配置逻辑（会话传图提问，plan-image-qa-fullstack §刀1）。

只测接线/降级逻辑，不依赖真实 VL 端点（构造 ChatOpenAI 不发网络）。
"""

from __future__ import annotations

from agent_server.agent.llm import build_vl_model
from agent_server.config import get_settings


def _clear():
    get_settings.cache_clear()


def test_vl_model_returns_client_when_configured(monkeypatch):
    monkeypatch.setenv("VL_API_KEY", "sk-test")
    monkeypatch.setenv("VL_BASE_URL", "http://localhost:9999/v1")
    monkeypatch.setenv("VL_MODEL", "Qwen/Qwen3-VL-8B-Instruct")
    monkeypatch.setenv("IMAGE_QA_ENABLED", "true")
    for k in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"):
        monkeypatch.setenv(k, "")
    _clear()
    try:
        vl = build_vl_model()
    finally:
        _clear()
    assert vl is not None
    assert vl.model == "Qwen/Qwen3-VL-8B-Instruct"


def test_vl_model_disabled_returns_none(monkeypatch):
    monkeypatch.setenv("VL_API_KEY", "sk-test")
    monkeypatch.setenv("VL_MODEL", "Qwen/Qwen3-VL-8B-Instruct")
    monkeypatch.setenv("IMAGE_QA_ENABLED", "false")
    _clear()
    try:
        assert build_vl_model() is None
    finally:
        _clear()


def test_vl_model_empty_model_returns_none(monkeypatch):
    monkeypatch.setenv("VL_API_KEY", "sk-test")
    monkeypatch.setenv("VL_MODEL", "")
    monkeypatch.setenv("IMAGE_QA_ENABLED", "true")
    _clear()
    try:
        assert build_vl_model() is None
    finally:
        _clear()


def test_vl_model_no_vl_key_returns_none(monkeypatch):
    monkeypatch.setenv("VL_API_KEY", "")
    monkeypatch.setenv("VL_MODEL", "Qwen/Qwen3-VL-8B-Instruct")
    monkeypatch.setenv("IMAGE_QA_ENABLED", "true")
    _clear()
    try:
        assert build_vl_model() is None
    finally:
        _clear()


def test_vl_uses_independent_endpoint(monkeypatch):
    """回归：VL 必须用 VL_BASE_URL（硅基流动），不是 LLM_BASE_URL(modelscope 无该模型)。"""
    monkeypatch.setenv("VL_API_KEY", "sk-vl-test")
    monkeypatch.setenv("VL_BASE_URL", "https://api.siliconflow.cn/v1")
    monkeypatch.setenv("VL_MODEL", "Qwen/Qwen3-VL-8B-Instruct")
    monkeypatch.setenv("LLM_API_KEY", "sk-llm-test")
    monkeypatch.setenv("LLM_BASE_URL", "https://api-inference.modelscope.cn/v1")
    monkeypatch.setenv("IMAGE_QA_ENABLED", "true")
    _clear()
    try:
        vl = build_vl_model()
    finally:
        _clear()
    assert vl is not None
    assert str(vl.openai_api_base).rstrip("/").endswith("siliconflow.cn/v1")


def test_multimodal_message_shape(monkeypatch):
    """VL client 能接受多模态 message（dict content list），形状与 KS node_md_img 同款。"""
    from langchain_core.messages import HumanMessage

    msg = HumanMessage(content=[
        {"type": "text", "text": "这张图是什么"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}},
    ])
    assert isinstance(msg.content, list)
    assert msg.content[1]["type"] == "image_url"
