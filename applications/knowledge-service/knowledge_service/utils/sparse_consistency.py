# -*- coding: utf-8 -*-
"""
稀疏向量编码一致性防呆门禁（self-retrieval canary）。

背景（实测根因，见 docs/plans/plan-rag-sparse-encoding-consistency-2026-09-29.md）：
    Milvus 混合检索依赖「稠密 + 稀疏」双路。稀疏向量以 {维度id: 权重} 存储，检索做 IP（内积），
    **仅对查询与库内"相同维度 id"累加权重乘积**。本项目稀疏编码随 EMBEDDING_MODE 不同而不同：
      - api 模式：sparse_vectorizer.build_sparse_vector → md5(token) 哈希 id（8–10 位）；
      - local 模式：BGE-M3 encode_documents → 词表 token id（小整数）。
    两 id 空间天然不相交。若「导入编码 ≠ 查询编码」，稀疏路 IP 恒为 0 → 混合检索静默退化为
    纯 dense（曾致路线消融层2 权重扫描结论整体作废）。集合名 `..._bge_m3` 亦无法反映真实稀疏编码。

门禁思路（不依赖集合元数据/动态字段，直接验证失败症状本身）：
    取库内任意一条 chunk 的 content，用"当前查询编码"重新生成其稀疏向量，再对该集合做稀疏单路
    搜索——同编码自我检索必命中该 chunk 自身（IP 最高）。若命中不到自身，则当前查询编码与库内
    存储编码不一致，抛 SparseEncodingMismatchError，供调用方 fail-fast，杜绝静默退化。

依赖方向：仅在本包内引用 embedding / milvus 客户端，不反向依赖 applications/。
"""

from typing import Any, Callable, Dict, List, Optional

from knowledge_service.core.logger import logger


class SparseEncodingMismatchError(RuntimeError):
    """库内稀疏编码与当前查询编码不一致（混合检索将静默退化为纯 dense）。"""


# 按集合缓存已通过校验（进程级，避免每次检索重复 canary 开销）。
_VERIFIED_COLLECTIONS: Dict[str, bool] = {}


def reset_sparse_consistency_cache() -> None:
    """清空缓存（重导入集合后需重新校验时调用；亦供单测隔离）。"""
    _VERIFIED_COLLECTIONS.clear()


def _default_embed_sparse(content: str) -> Dict[int, float]:
    """默认稀疏编码：走当前 EMBEDDING_MODE 的 generate_embeddings（与查询链路同一实现）。"""
    from knowledge_service.lm.embedding_utils import generate_embeddings

    return generate_embeddings([content]).get("sparse")[0]


def _collect_hit_ids(res: Any) -> List[Any]:
    """从 Milvus search 结果规整出命中 id 列表（兼容 dict / entity 嵌套两种形态）。"""
    if not res:
        return []
    hits = res[0] if isinstance(res[0], (list, tuple)) else res
    ids: List[Any] = []
    for h in hits or []:
        if isinstance(h, dict):
            entity = h.get("entity")
            if isinstance(entity, dict) and "chunk_id" in entity:
                ids.append(entity["chunk_id"])
            elif "chunk_id" in h:
                ids.append(h["chunk_id"])
        else:
            entity = getattr(h, "entity", None)
            if entity is not None and "chunk_id" in entity:
                ids.append(entity["chunk_id"])
    return ids


def assert_sparse_encoding_consistent(
    client: Optional[Any] = None,
    collection_name: Optional[str] = None,
    *,
    embed_sparse: Optional[Callable[[str], Dict[int, float]]] = None,
    top_k: int = 10,
    use_cache: bool = True,
) -> bool:
    """
    self-retrieval canary：校验"当前查询稀疏编码"与"库内存储稀疏编码"是否一致。

    :param client: MilvusClient 实例，默认取全局单例（注入便于单测）
    :param collection_name: 目标集合名，默认读 milvus_config.chunks_collection
    :param embed_sparse: content -> {id: weight} 编码函数，默认走 generate_embeddings（注入便于单测）
    :param top_k: 稀疏单路搜索取前 K，判断自身是否在其中
    :param use_cache: 命中过的集合是否走进程缓存跳过重复 canary
    :return: True=一致（或集合空/无法校验时按通过放行，交由上层判断）
    :raises SparseEncodingMismatchError: 明显不一致（当前编码查不回库内同 content 的 chunk 自身）
    """
    if client is None:
        from knowledge_service.clients.milvus_utils import get_milvus_client

        client = get_milvus_client()
    if collection_name is None:
        from knowledge_service.conf.milvus_config import milvus_config

        collection_name = milvus_config.chunks_collection
    if embed_sparse is None:
        embed_sparse = _default_embed_sparse

    if use_cache and _VERIFIED_COLLECTIONS.get(collection_name):
        return True

    # 取库内一条真实 chunk（content + 主键）。取不到（集合空）→ 无可校验，放行非失败。
    probe = client.query(
        collection_name=collection_name,
        filter="chunk_id >= 0",
        limit=1,
        output_fields=["chunk_id", "content"],
    )
    if not probe:
        logger.warning(f"[sparse-consistency] 集合 '{collection_name}' 为空，跳过编码一致性校验")
        return True

    probe_row = probe[0]
    chunk_id = probe_row.get("chunk_id")
    content = probe_row.get("content") or ""
    if content == "":
        logger.warning("[sparse-consistency] 探针 chunk content 为空，跳过校验")
        return True

    sparse_vec = embed_sparse(content)
    if not sparse_vec:
        # 当前编码对该内容产出空稀疏（如无词元）→ 无法判定，放行但留痕
        logger.warning("[sparse-consistency] 当前编码对探针 content 产出空稀疏，无法校验，跳过")
        return True

    # 稀疏单路自我检索：同编码下该内容重算的稀疏向量必能与库内自身匹配（IP 最高）。
    res = client.search(
        collection_name=collection_name,
        anns_field="sparse_vector",
        data=[sparse_vec],
        limit=top_k,
        output_fields=["chunk_id"],
    )
    hit_ids = [str(x) for x in _collect_hit_ids(res)]

    if str(chunk_id) in hit_ids:
        if use_cache:
            _VERIFIED_COLLECTIONS[collection_name] = True
        logger.info(f"[sparse-consistency] 集合 '{collection_name}' 稀疏编码一致性校验通过")
        return True

    raise SparseEncodingMismatchError(
        f"稀疏编码不一致：当前查询编码对 chunk_id={chunk_id} 的 content 重算稀疏后，"
        f"在集合 '{collection_name}' 稀疏单路搜索未能命中其自身（top{top_k}={hit_ids}）。"
        f"多半是『导入 EMBEDDING_MODE ≠ 查询 EMBEDDING_MODE』（md5 哈希 id vs BGE-M3 token id），"
        f"混合检索将静默退化为纯 dense。请统一编码或重算集合稀疏向量"
        f"（见 docs/plans/plan-rag-sparse-encoding-consistency-2026-09-29.md）。"
    )
