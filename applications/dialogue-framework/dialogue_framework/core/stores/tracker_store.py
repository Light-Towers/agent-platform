"""tracker_store 工厂：按 STORE_BACKEND 环境变量切换 JSON/Postgres 实现。"""

from dialogue_framework.shared.config import get_settings


async def build_store():
    """构建 Store 实例。json=JsonStore（默认），postgres=PostgresStore。"""
    settings = get_settings()
    if settings.store_backend == "postgres":
        from psycopg import AsyncConnection

        from dialogue_framework.core.stores.postgres_store import PostgresStore

        conn = await AsyncConnection.connect(settings.database_url)
        return PostgresStore(conn)
    from dialogue_framework.core.stores.json_store import JsonStore

    return JsonStore()
