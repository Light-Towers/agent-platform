"""SQL 白名单守卫：复用 agent_core.sql.guard，保留 app 专属的 detect_dialect。"""

from agent_core.sql.guard import validate_sql  # noqa: F401 — re-export


def detect_dialect(dsn: str) -> str:
    if dsn.startswith("sqlite"):
        return "sqlite"
    if dsn.startswith("postgres"):
        return "postgres"
    if dsn.startswith("mysql"):
        return "mysql"
    return "postgres"
