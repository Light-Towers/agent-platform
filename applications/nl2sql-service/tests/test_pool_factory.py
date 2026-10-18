# -*- coding: utf-8 -*-
"""nl2sql 侧池装配用例：共享件 import 冒烟 + 配置面 + 观测路由。

工厂本体（配额/只读/统计）的用例已随 2026-10-18 上移搬到
`packages/agent-runtime/tests/test_pool_factory.py`（方案 §5.12.2）。
本文件只留 nl2sql 应用层职责：① 共享件 import 可达（防依赖面断裂）；
② 本服务的 pool 配置面（YAML→Settings）；③ 本服务的观测路由装配。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from nl2sql_service.clients.postgres_client_manager import redact_dsn
from nl2sql_service.conf.settings import Settings


# ---------------------------------------------------------------------------
# 共享件 import 冒烟（nl2sql 已不持有池工厂本地副本）
# ---------------------------------------------------------------------------
def test_pool_factory_is_importable_from_runtime():
    from agent_runtime.pool_factory import create_pool, pool_stats

    assert callable(create_pool) and callable(pool_stats)


def test_cli_build_entry_is_importable():
    """CLI 构建入口必须可 import。

    2026-10-18 教训：该文件曾因 `from psycopg import AsyncConnectionPool`
    （psycopg 无此属性）一 import 即炸，而测试套件零覆盖 CLI 路径——
    潜伏到运行 `build_meta_knowledge.py` 才爆。本条把 CLI 路径钉进测试。
    """
    import importlib

    module = importlib.import_module("nl2sql_service.scripts.build_meta_knowledge")
    assert hasattr(module, "main") or hasattr(module, "run")


# ---------------------------------------------------------------------------
# S-4 DSN 脱敏
# ---------------------------------------------------------------------------
def test_redact_dsn_strips_password_from_url_form():
    """URL 格式 DSN 的密码就在前 30 字符内——`dsn[:30]` 那种截断等于明文泄露。"""
    out = redact_dsn("postgres://appuser:sup3rsecret@10.0.0.9:5432/nl2sql_meta")
    assert "sup3rsecret" not in out
    assert out == "appuser@10.0.0.9:5432/nl2sql_meta"


def test_redact_dsn_handles_keyword_form():
    out = redact_dsn("host=db.internal user=app password=s3cret dbname=meta")
    assert "s3cret" not in out
    assert "app@" in out


def test_redact_dsn_degrades_to_placeholder_not_raw():
    """解析失败返回占位符，绝不回退到打印原文。"""
    assert redact_dsn("not a dsn at all") == "<unparsable-dsn>"


# ---------------------------------------------------------------------------
# Settings 配置面
# ---------------------------------------------------------------------------
def test_pool_overrides_maps_yaml_keys_to_fields():
    """YAML `pool:` 段 → Settings 字段；显式键才覆盖，缺项回落 Field 默认。"""
    from nl2sql_service.conf.settings import _pool_overrides

    out = _pool_overrides(
        {
            "pool": {
                "meta": {"max_size": 8},
                "dw": {"statement_timeout_ms": 60000},
            }
        }
    )
    assert out == {
        "meta_db_pool_max_size": 8,
        "dw_db_statement_timeout_ms": 60000,
    }


def test_pool_overrides_rejects_unknown_key():
    """错字键必须炸，不能静默丢弃——否则又是一个"配了不生效"的坑。"""
    from nl2sql_service.conf.settings import _pool_overrides

    with pytest.raises(ValueError, match="未知键"):
        _pool_overrides({"pool": {"meta": {"maxsize": 8}}})


def test_pool_overrides_handles_empty_pool_section():
    from nl2sql_service.conf.settings import _pool_overrides

    assert _pool_overrides({}) == {}
    assert _pool_overrides({"pool": None}) == {}
    assert _pool_overrides({"pool": {"meta": None, "dw": None}}) == {}


def test_settings_pool_quota_defaults_are_ordered_and_positive():
    s = Settings()
    for prefix in ("meta_db", "dw_db"):
        lo = getattr(s, f"{prefix}_pool_min_size")
        hi = getattr(s, f"{prefix}_pool_max_size")
        timeout = getattr(s, f"{prefix}_pool_timeout")
        stmt = getattr(s, f"{prefix}_statement_timeout_ms")
        assert 0 < lo <= hi, f"{prefix} 配额非法: {lo}-{hi}"
        assert timeout > 0, f"{prefix} 取连接超时必须为正: {timeout}"
        assert stmt > 0, f"{prefix} 语句超时必须为正: {stmt}"
    # dw 是 OLAP 长查询画像：连接更少、语句超时更长
    assert s.dw_db_pool_max_size < s.meta_db_pool_max_size
    assert s.dw_db_statement_timeout_ms > s.meta_db_statement_timeout_ms
    assert s.dw_db_connection_read_only is True


def test_env_example_documents_every_pool_key():
    """新增池字段若忘了进 .env.example，正向齐全用例会红——这里提前给出可读定位。"""
    template = Path(__file__).resolve().parents[1] / ".env.example"
    documented = {
        line.split("=", 1)[0].strip()
        for line in template.read_text(encoding="utf-8-sig").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    pool_keys = {name.upper() for name in Settings.model_fields if "pool" in name or "statement_timeout" in name}
    missing = sorted(pool_keys - documented)
    assert not missing, f"池相关键未进 .env.example（照模板部署会静默取代码默认值）: {missing}"


# ---------------------------------------------------------------------------
# 路由装配
# ---------------------------------------------------------------------------
def test_pools_route_is_mounted_and_degrades_to_empty():
    """`GET /api/pools` 已挂载；lifespan 未建池时返回 {"pools": {}} 而非 500。"""
    from fastapi.testclient import TestClient
    from nl2sql_service.api.server import create_app

    client = TestClient(create_app())
    resp = client.get("/api/pools")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"pools": {}}
