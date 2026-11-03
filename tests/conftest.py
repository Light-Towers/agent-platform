"""测试夹具：清理环境变量与 settings 缓存，保证用例隔离。"""

import os

# 根套件的语义是「无外部依赖」，但 huggingface_hub 在 import 期之后会在调用路径里
# **同步**抓它的 agent harness registry（utils/_detect_agent.py 的 _fetch_registry，
# httpx 无超时）：本机有缓存文件所以不发请求，离线/无缓存的机器（如 126 容器）会
# 卡在 SYN_SENT 直到 TCP 放弃——表现是「套件挂死」而不是「用例失败」。
# 该开关是 import 期求值的常量，所以必须在任何被测模块被导入之前落定：放在 conftest
# 顶部（pytest 先导入 conftest，再导入测试模块）。
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import pytest  # noqa: E402

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
    from agent_runtime.cache import reset_cache_config, reset_cache_for_tests
    from agent_server.config import get_settings

    for var in _CLEARED_VARS:
        monkeypatch.delenv(var, raising=False)
    # 根套件默认不依赖外部 Valkey：显式关闭缓存。缓存行为由专门用例自行装配。
    monkeypatch.setenv("CACHE_BACKEND", "disabled")
    reset_cache_config()
    reset_cache_for_tests()
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
    reset_cache_config()
    reset_cache_for_tests()


# 2026-09-23：dialogue-framework 已移除（孤儿框架，能力已被 agent_server 吸收）。
# nl2sql_service 模块经 Makefile 独立 session 跑（避免根 session conftest 冲突）。
collect_ignore_glob: list[str] = []
