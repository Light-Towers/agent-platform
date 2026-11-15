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


def test_data_permission_unknown_key_raises():
    """1c/D5 + R8：残留角色键启动期具名报错，不静默忽略（合成违规能咬）。"""
    from nl2sql_service.conf.settings import _data_permission_overrides

    for legacy in ("admin_roles", "default_query_role", "typo_key"):
        with pytest.raises(ValueError, match="未知键"):
            _data_permission_overrides({"data_permission": {legacy: "x"}})
    with pytest.raises(ValueError, match="必须是映射"):
        _data_permission_overrides({"data_permission": ["not", "a", "map"]})


def test_data_permission_current_tree_is_clean_and_judged():
    """真面参与判决：仓库现版 YAML 的三键真被判定且零违规（不是扫不到所以绿）。"""
    from pathlib import Path

    from nl2sql_service.conf.settings import _data_permission_overrides, _load_yaml

    app_yaml = _load_yaml(
        Path(__file__).resolve().parents[2]
        / "applications/nl2sql-service/nl2sql_service/conf/app_config.yaml"
    )
    out = _data_permission_overrides(app_yaml)
    assert set(out) == {
        "sensitive_columns",
        "result_masking_enabled",
        "mask_keep_chars",
    }


_RETIRED_ROLE_ENV_KEYS = frozenset({"ADMIN_ROLES", "DEFAULT_QUERY_ROLE"})


def _active_env_keys(text: str) -> set[str]:
    """模板里真正生效的键（排除注释行），供「下线键不得回流」判据使用。"""
    return {
        line.split("=", 1)[0].strip()
        for line in text.splitlines()
        if "=" in line and line.strip() and not line.strip().startswith("#")
    }


def test_retired_role_keys_absent_from_env_template():
    """1c/D5：已下线角色键不得留在 .env.example（配了没人读 / 部署漂移）。

    真面参与判决：模板必须被真读到且非空，不能「扫不到对象所以绿」（硬规矩 #8）。
    """
    from pathlib import Path

    text = (
        Path(__file__).resolve().parents[2]
        / "applications/nl2sql-service/.env.example"
    ).read_text(encoding="utf-8-sig")
    keys = _active_env_keys(text)
    assert "SENSITIVE_COLUMNS" in keys, "现版 .env.example 必须真被判过且非空"
    assert not keys & _RETIRED_ROLE_ENV_KEYS, (
        f"已下线角色键回流: {sorted(keys & _RETIRED_ROLE_ENV_KEYS)}"
    )


def test_retired_role_key_gate_can_bite():
    """合成违规能咬：把旧键塞回模板形状，判据必须命中两个（注释里的旧键不算）。"""
    injected = (
        'SENSITIVE_COLUMNS=[]\n# ADMIN_ROLES 在注释里不算\n'
        'ADMIN_ROLES=["admin"]\nDEFAULT_QUERY_ROLE=analyst\n'
    )
    keys = _active_env_keys(injected)
    assert keys & _RETIRED_ROLE_ENV_KEYS == _RETIRED_ROLE_ENV_KEYS
    assert "SENSITIVE_COLUMNS" in keys


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
