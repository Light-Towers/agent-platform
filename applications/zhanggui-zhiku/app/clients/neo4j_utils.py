import logging
import os

logger = logging.getLogger(__name__)

_neo4j_driver = None


def get_neo4j_driver():
    """获取 Neo4j 驱动单例（惰性初始化，环境变量缺失时返回 None）。

    注意：neo4j 驱动为重型依赖，刻意不在模块顶层 import（遵循框架无关 /
    可选依赖护栏，避免无 neo4j 环境下导入 app.clients.neo4j_utils 即失败）。
    """
    global _neo4j_driver
    if _neo4j_driver is not None:
        return _neo4j_driver
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USERNAME")
    pwd = os.getenv("NEO4J_PASSWORD")
    if not uri:
        logger.warning("NEO4J_URI 未配置，Neo4j 检索不可用")
        return None
    try:
        from neo4j import GraphDatabase

        _neo4j_driver = GraphDatabase.driver(uri, auth=(user, pwd))
        return _neo4j_driver
    except Exception as e:
        logger.warning("Neo4j 驱动初始化失败: %s", e)
        _neo4j_driver = None
        return None


def query_kg(query: str, item_names: list | None = None, limit: int = 8) -> list[dict]:
    """知识图谱实体/关系检索，返回标准化 doc 列表（与向量召回同构）。

    通用 schema（与写入端约定）：``Entity`` 节点携带 ``name`` / ``content`` /
    ``item_name`` 属性，关系任意。查询按 item_name 限定知识库范围（若提供），
    并匹配实体 ``name`` 或 ``content`` 包含查询词；无命中退化返回空。

    无连接 / 查询异常 / 空库一律返回 ``[]``，绝不抛错（KG 是增强通道，
    失败不应阻断主检索链路）。

    Returns:
        [{"chunk_id", "content", "item_name", "score"}, ...]
    """
    driver = get_neo4j_driver()
    if driver is None:
        return []

    cypher = """
    MATCH (e:Entity)
    WHERE ($item_names IS NULL OR e.item_name IN $item_names)
      AND (toLower(e.name) CONTAINS toLower($q)
           OR toLower(e.content) CONTAINS toLower($q))
    RETURN e.name AS name, e.content AS content, e.item_name AS item_name
    LIMIT $limit
    """
    params = {"q": query, "item_names": item_names, "limit": limit}
    try:
        with driver.session(database=os.getenv("NEO4J_DATABASE", "neo4j")) as session:
            records = session.run(cypher, params)
            docs = []
            for rec in records:
                content = rec.get("content") or ""
                if not content:
                    continue
                docs.append({
                    "chunk_id": f"kg::{rec.get('item_name')}::{rec.get('name')}",
                    "content": content,
                    "item_name": rec.get("item_name") or "",
                    "score": 1.0,
                })
            return docs
    except Exception as e:
        logger.warning("query_kg 失败，降级为空: %s", e)
        return []
