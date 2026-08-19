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
    from agent_server.config import get_settings

    for var in _CLEARED_VARS:
        monkeypatch.delenv(var, raising=False)
    # 强制内存模式：pydantic-settings 中环境变量优先级高于 .env，
    # 故显式置空 DATABASE_URL 可覆盖 .env 里的 postgres 配置，
    # 保证 smoke 测试在「无外部依赖」的内存模式下运行。
    monkeypatch.setenv("DATABASE_URL", "")
    # 同理：.env 里的 LLM_API_KEY 非空会让 llm_enabled=True，
    # 置空后 /health 才返回 llm=False，匹配内存模式冒烟语义。
    monkeypatch.setenv("LLM_API_KEY", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
