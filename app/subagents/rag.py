"""RAG 子能力：混合检索证据收集。"""

from app.config import get_settings
from app.infra.db import get_pool
from app.rag.store import retrieve_chunks


async def rag_query(query: str, workspace_id: str = "default") -> list[str]:
    pool = get_pool()
    if pool is None:
        return ["知识库未启用（DATABASE_URL 未配置）"]
    chunks = await retrieve_chunks(pool, query, get_settings().rag_top_k, workspace_id)
    if not chunks:
        return ["知识库中未检索到相关内容"]
    return [
        f"[来源: {c['source']} / {c['heading'] or '无标题'}] {c['content']}" for c in chunks
    ]
