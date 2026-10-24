"""配置优先级回归（env > YAML > 默认）：Q18 配置漂移的根因修复守护。

背景：`get_settings()` 曾把 app_config.yaml 的值作为 init kwargs 传给
`Settings(**...)`——init kwargs 优先级最高，盖过 env/.env，使根 `.env` 的
`EMBEDDING_*`/`VECTOR_DIM` 成为死配置（真库端到端里显形：维度/模型二义）。
修复：`get_settings` 剔除 env/.env 已提供的字段，让它们走 pydantic 的 env 源。

这几条钉住修复后的优先级语义，防回归。
"""

from __future__ import annotations

import pytest
from nl2sql_service.conf.settings import _env_provided_fields, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """get_settings 是 lru_cache；每条用例前后清缓存，避免相互污染。"""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_env_var_overrides_yaml(monkeypatch):
    """env 显式设置的字段胜出 app_config.yaml（env > YAML）。

    app_config.yaml 的 sql.max_rows=1000；env 设 777 应胜出。
    """
    monkeypatch.setenv("SQL_MAX_ROWS", "777")
    assert get_settings().sql_max_rows == 777


def test_yaml_used_when_env_absent(monkeypatch):
    """env 未提供的字段仍走 YAML（YAML > 默认）。"""
    monkeypatch.delenv("SQL_MAX_ROWS", raising=False)
    # SQL_MAX_ROWS 不在根 .env 里，故走 app_config.yaml 的 1000
    assert get_settings().sql_max_rows == 1000


def test_env_provided_fields_includes_environ_and_dotenv():
    """_env_provided_fields 同时覆盖进程 env 与 .env 文件键（大写）。"""
    import os

    os.environ["_NL2SQL_TEST_PROBE"] = "x"
    try:
        provided = _env_provided_fields(env_file=".env")
        assert "_NL2SQL_TEST_PROBE" in provided
    finally:
        del os.environ["_NL2SQL_TEST_PROBE"]


def test_dotenv_embedding_overrides_yaml_when_present():
    """根 .env 若提供 EMBEDDING_MODEL，应胜出 app_config.yaml（死配置修复的核心）。

    仅在根 .env 确有该键时断言（CI 无 .env 时跳过，不制造假通过）。
    """
    from pathlib import Path

    dotenv = Path(".env")
    if not dotenv.is_file() or "EMBEDDING_MODEL=" not in dotenv.read_text(encoding="utf-8-sig"):
        pytest.skip("根 .env 未提供 EMBEDDING_MODEL")
    dotenv_val = next(
        line.split("=", 1)[1].strip()
        for line in dotenv.read_text(encoding="utf-8-sig").splitlines()
        if line.strip().startswith("EMBEDDING_MODEL=")
    )
    assert get_settings().embedding_model == dotenv_val
