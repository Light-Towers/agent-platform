# -*- coding: utf-8 -*-
"""视觉模型客户端构造测试：不能带 enable_thinking（硅基流动 Qwen3-VL-8B 不支持，400）。"""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def node_md_img_module(monkeypatch):
    """import 时屏蔽 minio_utils 的模块级连接（本机无 MinIO）。"""
    stub = ModuleType("knowledge_service.clients.minio_utils")
    stub.get_minio_client = lambda: MagicMock()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "knowledge_service.clients.minio_utils", stub)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-vl")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.siliconflow.cn/v1")
    from knowledge_service.conf.lm_config import lm_config
    monkeypatch.setattr(lm_config, "api_key", "sk-test-vl", raising=False)
    sys.modules.pop("knowledge_service.import_process.agent.nodes.node_md_img", None)
    import knowledge_service.import_process.agent.nodes.node_md_img as m
    return m


def test_vl_client_no_enable_thinking(node_md_img_module):
    client = node_md_img_module._get_vl_client()
    # ChatOpenAI 把额外 kwargs 放 model_kwargs；enable_thinking 绝不能出现
    kwargs = getattr(client, "model_kwargs", {}) or {}
    assert "enable_thinking" not in kwargs
    assert "enable_thinking" not in str(client.model_dump() if hasattr(client, "model_dump") else "")


def test_vl_client_uses_vl_model(node_md_img_module):
    client = node_md_img_module._get_vl_client()
    from knowledge_service.conf.lm_config import lm_config
    assert client.model_name == lm_config.lv_model
