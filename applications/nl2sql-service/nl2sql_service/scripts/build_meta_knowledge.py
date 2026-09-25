"""元知识构建 CLI 脚本。

用法：python -m nl2sql_service.scripts.build_meta_knowledge --dsn $META_DB_DSN
"""

import argparse
import asyncio


async def main_async(dsn: str, config_path: str = "") -> None:
    from nl2sql_service.clients.postgres_client_manager import PostgresClientManager
    from nl2sql_service.conf.settings import get_settings
    from nl2sql_service.repositories.postgres.meta.meta_repository import MetaRepository
    from nl2sql_service.services.meta_knowledge_service import MetaKnowledgeService

    settings = get_settings()
    pg = PostgresClientManager(dsn)
    await pg.connect()
    try:
        meta_repo = MetaRepository(pool=pg.pool, table_prefix=settings.table_prefix)
        MetaKnowledgeService(meta_repo=meta_repo)
        print(f"meta knowledge service ready (dsn={dsn[:30]}...)")
        print("use the service API to build meta knowledge from DDL/documents")
    finally:
        await pg.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="构建元知识库")
    parser.add_argument("--dsn", required=True, help="元知识库 Postgres DSN")
    parser.add_argument("--config", default="", help="配置文件路径")
    args = parser.parse_args()
    asyncio.run(main_async(args.dsn, args.config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
