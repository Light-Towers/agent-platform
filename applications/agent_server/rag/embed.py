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

from agent_server.config import get_settings


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


def resolve_provider():
    """映射 app 配置到内核 env 并返回 embedder 实例（含 fail-fast 护栏）。

    async/sync 两条入口共用同一份选型与护栏逻辑——护栏若在调用方各抄一遍，
    迟早出现「一条路有 fail-fast、另一条静默退化」的分叉。

    fail-fast 护栏（审计 P1 #十一）：缺真实 embedding 时返回确定性 hash 向量会让
    RAG/记忆检索完全失去语义，属「静默质量退化」，比硬失败更危险。
    默认关闭（测试/CI/开发保持 mock 兼容）；生产部署设 EMBEDDING_REQUIRE_REAL=true
    后，任何未显式配置真实 backend 的调用都将直接报错，而非静默退化。
    """
    _sync_env()
    if os.getenv("EMBEDDING_REQUIRE_REAL", "").lower() in ("1", "true", "yes"):
        from agent_core.memory.embedder import MockEmbedder

        provider = get_embedder(force=True)
        if isinstance(provider, MockEmbedder):
            raise RuntimeError(
                "EMBEDDING_REQUIRE_REAL=true 但 embedding 退化为 Mock：请配置 "
                "EMBEDDING_API_KEY / SILICONFLOW_API_KEY 或 EMBEDDING_MODE=remote，"
                "否则 RAG/记忆检索将失去语义。"
            )
        return provider
    return get_embedder(force=True)


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    provider = resolve_provider()
    # 优先异步路径（RemoteEmbedder/MockEmbedder 均支持 aembed），避免事件循环内阻塞
    if hasattr(provider, "aembed"):
        return await provider.aembed(texts)
    # 本地 sentence-transformers 仅同步，但内部为 CPU 推理，开销可控
    return provider.embed(texts)


def embed_texts_sync(texts: list[str]) -> list[list[float]]:
    """同步入口，供必须保持 sync 契约的宿主调用点使用（如 memory_backend.embed_memory）。

    刻意不走 ``LocalFnEmbedder.embed()``——其同步入口内部是 ``asyncio.run``，而本函数的
    调用点全在已运行的事件循环内（``remember_typed`` / ``recall_typed`` 都是 ``async def``），
    嵌套 run 必死锁。内核四个 provider 均实现协议要求的同步 ``embed``。
    """
    if not texts:
        return []
    return resolve_provider().embed(texts)


async def embed_query(text: str) -> list[float]:
    return (await embed_texts([text]))[0]
