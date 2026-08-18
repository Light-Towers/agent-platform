"""Embedding 客户端：统一委托内核 agent_core.memory.embedder.get_embedder()。

app 不直接实现 embedding 逻辑（避免与子项目各自为政），仅负责把 app 配置
（shared-schemas 的 ``embedding_*`` 字段）映射为内核 get_embedder() 期望的环境变量，
随后复用内核的统一提供方：

  - ``embedding_mode=mock``（或 auto 且无密钥）→ MockEmbedder（确定性 hash，零成本）
  - ``embedding_mode=remote`` 或配了 ``embedding_api_key`` → 通用远程（OpenAI 兼容 /embeddings）
  - 否则 → 本地 sentence-transformers（BAAI/bge-small-zh-v1.5，512 维）

公开 API 保持 ``embed_texts`` / ``embed_query``（async），供 store.py / schema_store.py /
routes.py 直接 import，调用方零改动。
"""

import os

from agent_core.memory.embedder import get_embedder

from app.config import get_settings


def _sync_env() -> None:
    """把 app 配置映射为内核 get_embedder() 期望的环境变量（强制覆盖，保证 app 配置优先）。"""
    s = get_settings()
    os.environ["EMBEDDING_MODE"] = s.embedding_mode
    if s.embedding_api_key:
        os.environ["EMBEDDING_API_KEY"] = s.embedding_api_key
    if s.embedding_base_url:
        os.environ["EMBEDDING_BASE_URL"] = s.embedding_base_url
    if s.embedding_model:
        os.environ["EMBEDDING_MODEL"] = s.embedding_model
    os.environ["EMBEDDING_DIM"] = str(s.vector_dim)


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    _sync_env()
    provider = get_embedder(force=True)
    # 优先异步路径（RemoteEmbedder/MockEmbedder 均支持 aembed），避免事件循环内阻塞
    if hasattr(provider, "aembed"):
        return await provider.aembed(texts)
    # 本地 sentence-transformers 仅同步，但内部为 CPU 推理，开销可控
    return provider.embed(texts)


async def embed_query(text: str) -> list[float]:
    return (await embed_texts([text]))[0]
