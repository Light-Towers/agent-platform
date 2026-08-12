"""测试夹具：清理环境变量与 settings 缓存，保证用例隔离。"""

import pytest

_CLEARED_VARS = [
    "DATABASE_URL",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "SEARCH_API_KEY",
    "SQL_DSN",
    "API_KEY",
    "EMBEDDING_API_KEY",
    "EMBEDDING_MODE",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_HOST",
    "CACHE_ENABLED",
    "MEMORY_ENABLED",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    from app.config import get_settings

    for var in _CLEARED_VARS:
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
