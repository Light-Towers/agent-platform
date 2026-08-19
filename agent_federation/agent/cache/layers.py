"""分层缓存：L1 精确 + L2 语义 + L3 检索结果。

L1: hash key → JSON value，<1ms，TTL 1h
L2: HNSW + COSINE 向量检索，相似度 > 0.92，<10ms，TTL 30min
L3: 检索结果缓存（只重算 LLM），TTL 10min

Valkey 客户端用 valkey 包（API 兼容 redis-py，BSD）。不可用时降级为 no-op。
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
from agent_core.cache import build_cache_key
from agent_core.logging import get_logger

from agent.cache.config import get_cache_config

logger = get_logger(__name__)

_valkey_client: Any = None
_valkey_available: bool | None = None


async def _get_valkey() -> Any:
    """懒连接 Valkey，失败时返回 None。"""
    global _valkey_client, _valkey_available
    if _valkey_available is False:
        return None
    if _valkey_client is not None:
        return _valkey_client

    cfg = get_cache_config()
    try:
        import valkey.asyncio as va  # noqa: PLC0415

        _valkey_client = va.Valkey.from_url(cfg.valkey_url, decode_responses=True)
        await _valkey_client.ping()
        _valkey_available = True
        logger.info("Valkey 连接成功: %s", cfg.valkey_url)
    except ImportError:
        logger.warning("valkey 包未安装，缓存层降级为 no-op")
        _valkey_available = False
    except Exception as e:
        logger.warning("Valkey 连接失败: %s，缓存层降级为 no-op", e)
        _valkey_available = False
    return _valkey_client if _valkey_available else None


# 缓存 key 构造统一走内核单一真相（agent_core.cache.build_cache_key），
# 避免 deepagents 与未来 app 重构各写一份 hash 逻辑导致漂移。
_build_cache_key = build_cache_key


class L1Cache:
    """精确缓存：hash key → JSON value，TTL 1h。"""

    @staticmethod
    async def get(key: str) -> dict[str, Any] | None:
        client = await _get_valkey()
        if client is None:
            return None
        cfg = get_cache_config()
        try:
            data = await client.get(f"{cfg.l1_prefix}{key}")
            if data:
                result = json.loads(data)
                result["_layer"] = "l1"
                logger.debug("L1 命中: %s", key[:16])
                return result
        except Exception as e:
            logger.warning("L1 get 失败: %s", e)
        return None

    @staticmethod
    async def set(key: str, value: dict[str, Any], ttl: int | None = None) -> None:
        client = await _get_valkey()
        if client is None:
            return
        cfg = get_cache_config()
        try:
            ttl = ttl or cfg.l1_ttl_seconds
            await client.set(
                f"{cfg.l1_prefix}{key}",
                json.dumps(value, ensure_ascii=False),
                ex=ttl,
            )
        except Exception as e:
            logger.warning("L1 set 失败: %s", e)

    @staticmethod
    async def invalidate(key: str) -> None:
        client = await _get_valkey()
        if client is None:
            return
        cfg = get_cache_config()
        try:
            await client.delete(f"{cfg.l1_prefix}{key}")
        except Exception as e:
            logger.warning("L1 invalidate 失败: %s", e)


class L2Cache:
    """语义缓存：HNSW + COSINE 向量检索，相似度 > 0.92，TTL 30min。"""

    _index_created = False

    @classmethod
    async def _ensure_index(cls) -> bool:
        """确保 Valkey Search 索引存在。"""
        if cls._index_created:
            return True
        client = await _get_valkey()
        if client is None:
            return False
        cfg = get_cache_config()
        try:
            ft = client.ft(cfg.index_name)
            try:
                await ft.info()
                cls._index_created = True
                return True
            except Exception:
                pass

            from valkey.commands.search.field import TextField, VectorField
            from valkey.commands.search.indexDefinition import IndexDefinition, IndexType

            schema = (
                TextField("query_text"),
                TextField("intent"),
                TextField("value_json"),
                VectorField(
                    "query_vec",
                    "FLOAT32",
                    "DIM",
                    cfg.l2_vector_dim,
                    "DISTANCE_METRIC",
                    "COSINE",
                    "TYPE",
                    "HNSW",
                ),
            )
            definition = IndexDefinition(prefix=[cfg.l2_prefix], index_type=IndexType.HASH)
            await ft.create_index(schema, definition=definition)
            cls._index_created = True
            logger.info("L2 Valkey Search 索引已创建: %s", cfg.index_name)
            return True
        except Exception as e:
            logger.warning("L2 索引创建失败: %s，L2 降级为 no-op", e)
            return False

    @classmethod
    async def get(cls, query_vec: np.ndarray, threshold: float | None = None) -> dict[str, Any] | None:
        if not await cls._ensure_index():
            return None
        client = await _get_valkey()
        if client is None:
            return None
        cfg = get_cache_config()
        threshold = threshold or cfg.l2_similarity_threshold
        try:
            from valkey.commands.search.query import Query

            vec_bytes = query_vec.astype(np.float32).tobytes()
            q = (
                Query("(*)=>[KNN 1 @query_vec $vec AS score]")
                .add_param("vec", vec_bytes)
                .return_fields("value_json", "score")
                .dialect(2)
            )
            results = await client.ft(cfg.index_name).search(q)
            if results and results.docs:
                doc = results.docs[0]
                score = float(doc.score) if hasattr(doc, "score") else 1.0
                similarity = 1.0 - score
                if similarity >= threshold:
                    value = json.loads(doc.value_json)
                    value["_layer"] = "l2"
                    value["_similarity"] = similarity
                    logger.debug("L2 命中: similarity=%.4f", similarity)
                    return value
        except Exception as e:
            logger.warning("L2 get 失败: %s", e)
        return None

    @classmethod
    async def set(
        cls,
        query_vec: np.ndarray,
        query_text: str,
        intent: str,
        value: dict[str, Any],
        ttl: int | None = None,
    ) -> None:
        if not await cls._ensure_index():
            return
        client = await _get_valkey()
        if client is None:
            return
        cfg = get_cache_config()
        try:
            import uuid

            key = f"{cfg.l2_prefix}{uuid.uuid4().hex}"
            vec_bytes = query_vec.astype(np.float32).tobytes()
            mapping = {
                "query_text": query_text,
                "intent": intent,
                "value_json": json.dumps(value, ensure_ascii=False),
                "query_vec": vec_bytes,
            }
            await client.hset(key, mapping=mapping)
            ttl = ttl or cfg.l2_ttl_seconds
            await client.expire(key, ttl)
        except Exception as e:
            logger.warning("L2 set 失败: %s", e)


class L3Cache:
    """检索结果缓存：只缓存检索结果（不缓存 LLM 生成），TTL 10min。"""

    @staticmethod
    async def get(key: str) -> dict[str, Any] | None:
        client = await _get_valkey()
        if client is None:
            return None
        cfg = get_cache_config()
        try:
            data = await client.get(f"{cfg.l3_prefix}{key}")
            if data:
                result = json.loads(data)
                result["_layer"] = "l3"
                logger.debug("L3 命中: %s", key[:16])
                return result
        except Exception as e:
            logger.warning("L3 get 失败: %s", e)
        return None

    @staticmethod
    async def set(key: str, value: dict[str, Any], ttl: int | None = None) -> None:
        client = await _get_valkey()
        if client is None:
            return
        cfg = get_cache_config()
        try:
            ttl = ttl or cfg.l3_ttl_seconds
            await client.set(
                f"{cfg.l3_prefix}{key}",
                json.dumps(value, ensure_ascii=False),
                ex=ttl,
            )
        except Exception as e:
            logger.warning("L3 set 失败: %s", e)


class NullCache:
    """空值缓存：防穿透，缓存空结果短 TTL。"""

    @staticmethod
    async def get(key: str) -> bool:
        """返回 True 表示已知空值（应短 circuit 返回空）。"""
        client = await _get_valkey()
        if client is None:
            return False
        cfg = get_cache_config()
        if not cfg.null_cache_enabled:
            return False
        try:
            data = await client.get(f"{cfg.null_prefix}{key}")
            return data is not None
        except Exception as e:
            logger.warning("NullCache get 失败: %s", e)
            return False

    @staticmethod
    async def set(key: str) -> None:
        client = await _get_valkey()
        if client is None:
            return
        cfg = get_cache_config()
        if not cfg.null_cache_enabled:
            return
        try:
            await client.set(
                f"{cfg.null_prefix}{key}",
                "1",
                ex=cfg.null_cache_ttl_seconds,
            )
        except Exception as e:
            logger.warning("NullCache set 失败: %s", e)
