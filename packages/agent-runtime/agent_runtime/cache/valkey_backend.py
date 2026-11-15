"""Valkey 语义缓存唯一实现（生产 + 开发/测试）。

设计边界（ADR-0013 C）：
- 租户为空 fail-closed；所有 L2 查询恒带 tenant/scope/kb_version/gray/epoch 过滤。
- 后端异常 fail-open：按未命中处理，熔断 + 健康态 degraded，不切换到其他后端。
- 写侧有界队列；队列满丢弃并计数，不阻塞请求。
- 写侧 PII 门禁：问答检出 PII 即跳过写入并计数（缓存是持久副本，命中不再过输出护栏）。
- 索引与 key 命名空间含 embedding 模型 + 维度 + schema 版本；换模型或改索引字段都换命名空间
  （索引按名字复用、不比对字段，改名才会绕开旧实例里的 stale schema）。
- 索引被外部摘掉（FT.DROPINDEX / FLUSHALL）时清 ``_index_ready`` 并计数，下次读路径重建；
  否则 L2 会永久静默 miss 而健康态仍报 ready。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from array import array
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from agent_core.cache import CacheHealth, CacheHit, CacheStats, build_cache_key
from agent_core.guardrails.input_guard import detect_pii
from agent_core.logging import get_logger
from agent_core.memory.embedder import embed_one
from valkey.commands.search.field import TagField, TextField, VectorField
from valkey.commands.search.indexDefinition import IndexDefinition, IndexType
from valkey.commands.search.query import Query
from valkey.exceptions import ResponseError, ValkeyError

from agent_runtime.cache.config import CacheConfig, CacheConfigError, redact_url
from agent_runtime.circuit_breaker import CircuitBreaker

logger = get_logger(__name__)

_VALKEY_ERRORS = (ValkeyError, OSError, TimeoutError, ValueError, TypeError)
_TAG_SEPARATOR = "\x1f"
# ``|`` 是 TAG 查询的 OR 分隔符，漏转义会让 @tenant:{a|b} 变成跨租户或查询。
_TAG_SPECIAL = frozenset(",.<>{}[]\"'`:;!@#$%^&*()-+=~|\\ ")
_MISSING = object()
_STOP = object()


def _escape_tag(value: str) -> str:
    """转义 TAG 查询值（RediSearch 语法）；存储侧分隔符为 control char。"""
    return "".join("\\" + ch if ch in _TAG_SPECIAL else ch for ch in value)


def _short(exc: BaseException, limit: int = 200) -> str:
    text = f"{type(exc).__name__}: {exc}"
    return text[:limit]


def _is_missing_index_error(message: str) -> bool:
    """索引不存在的那类报错（FT.DROPINDEX / FLUSHALL 之后）。

    措辞按**部署 pin 的那个 ref** 实取，而不是文档转述：真机 pin = valkey-bundle
    9.1.2（MODULE LIST 解出 search 1.2.1）上 FT.SEARCH 命中缺失索引报的是
    ``Index with name 'X' not found in database 0``（**带** database 后缀，main 那一支的形状）。
    上一代 pin = bundle 9.0.1（core 9.0.3 + valkey-search 1.0.2）源码里是两种无后缀形状——
    ``src/schema_manager.cc:121`` "Index with name 'X' not found"、``src/schema_manager.cc:133/:137``
    "Index schema not found: X"；main（e335d9e）另有 ``src/index_schema.h:63`` 与集群 fanout 的
    ``src/query/fanout_operation_base.h:224`` "Index name not found."。两代一并覆盖：
    升 pin 时形状会漂移，只留一边就是单边证据。
    同族的其它 "not found" 不会误判：1.0.2 的 "Record was not found" /
    "Entry not found: " / "Subscription not found" / "Parameter X not found."
    均不带 index 子串，被 ``"index" in low`` 挡在门外。
    误判无害——最多白跑一次建索引，同名已存在会回落到 ft.info 判定。"""
    low = message.lower()
    return "index" in low and any(marker in low for marker in ("no such index", "not found"))


def _vec_bytes(vector: Sequence[float]) -> bytes:
    raw = array("f", [float(x) for x in vector])
    if sys.byteorder != "little":  # pragma: no cover - 目标机均为小端
        raw.byteswap()
    return raw.tobytes()


class ValkeySemanticCache:
    """Valkey 分层语义缓存：L1 精确 + L2 HNSW + 负缓存 + epoch 失效。"""

    enabled = True

    def __init__(
        self,
        config: CacheConfig,
        scope: str,
        *,
        embedder: Any | None = None,
    ) -> None:
        if not scope or any(ch in scope for ch in ("\x00", _TAG_SEPARATOR)):
            raise CacheConfigError(f"缓存 scope 非法: {scope!r}")
        self._cfg = config
        self._scope = scope
        self._embedder = embedder
        self._dim = int(config.vector_dim)
        self._model = config.embedding_model or "unresolved"
        self._ns = ""
        self._index = ""
        self._rebuild_namespace()

        self._client = self._create_client()
        self._breaker = CircuitBreaker(
            failure_threshold=config.breaker_failure_threshold,
            recovery_seconds=config.breaker_recovery_seconds,
        )
        self._stats = CacheStats()
        self._runtime_counts = {
            "error": 0,
            "skipped_no_tenant": 0,
            # 仅 L2 路径会加它（TAG 查询里星号转义不掉 ⇒ 直接拒绝）；L1 走精确 key，不受影响。
            "skipped_unsafe_tag": 0,
            "skipped_pii": 0,
            "dropped_writes": 0,
            "embedding_error": 0,
            "l2_unavailable": 0,
            "index_missing": 0,
        }
        self._degraded_reason: str | None = None
        self._started = False
        self._start_lock = asyncio.Lock()
        self._index_ready = False
        self._index_lock = asyncio.Lock()
        self._index_next_retry = 0.0
        self._embedder_next_retry = 0.0
        self._queue: asyncio.Queue[Callable[[], Awaitable[None]] | object] | None = None
        self._worker: asyncio.Task | None = None
        self._closing = False
        if embedder is not None:
            self._resolve_model_from_embedder(embedder)

    # ------------------------------------------------------------------ setup
    def _create_client(self) -> Any:
        try:
            import valkey.asyncio as valkey_asyncio
        except ImportError as exc:  # pragma: no cover - 依赖缺失时由 factory 报错
            raise CacheConfigError(
                "CACHE_BACKEND=valkey 但未安装 valkey 客户端；请安装 agent-runtime 的主依赖"
            ) from exc
        try:
            return valkey_asyncio.Valkey.from_url(
                self._cfg.valkey_url,
                decode_responses=True,
                socket_connect_timeout=self._cfg.connect_timeout_ms / 1000.0,
                socket_timeout=self._cfg.command_timeout_ms / 1000.0,
                retry_on_timeout=False,
                health_check_interval=30,
            )
        except (ValkeyError, OSError, ValueError) as exc:
            raise CacheConfigError(f"VALKEY_URL 非法（{self._cfg.redacted_url}）: {_short(exc)}") from exc

    def _rebuild_namespace(self) -> None:
        self._ns = self._cfg.namespace(self._scope, self._model, self._dim)
        self._index = self._cfg.index_name(self._scope, self._model, self._dim)

    def _resolve_model_from_embedder(self, embedder: Any) -> None:
        dim = int(getattr(embedder, "dim", 0) or 0)
        if dim <= 0:
            raise CacheConfigError(f"embedder.dim 非法: {dim}")
        if self._cfg.vector_dim and self._cfg.vector_dim != dim:
            raise CacheConfigError(
                "embedding 维度不一致：CACHE_VECTOR_DIM="
                f"{self._cfg.vector_dim}，embedder.dim={dim}；请对齐配置或更换索引前缀"
            )
        model = self._cfg.embedding_model or self._embedder_model_id(embedder)
        self._embedder = embedder
        self._dim = dim
        self._model = model
        if self._degraded_reason and self._degraded_reason.startswith("embedder_unavailable"):
            self._degraded_reason = None
        self._rebuild_namespace()

    @staticmethod
    def _embedder_model_id(embedder: Any) -> str:
        model = getattr(embedder, "_model", None)
        if isinstance(model, str) and model:
            return f"{type(embedder).__name__}:{model}"
        if type(embedder).__name__ == "LocalEmbedder":
            local = os.getenv("INTENT_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
            return f"LocalEmbedder:{local}"
        return type(embedder).__name__

    async def startup(self) -> None:
        """幂等启动：解析 embedder（模型/维度）、探测 Valkey、按需建索引。

        embedder 自身不可用（模型缺失等）只降级 L2，L1 仍可用；配置不一致
        （``CACHE_VECTOR_DIM`` 与 ``embedder.dim`` 冲突）抛 ``CacheConfigError``，
        由应用启动失败暴露，不做静默改名。
        """
        if self._started:
            return
        async with self._start_lock:
            if self._started:
                return
            if self._embedder is None:
                await self._load_embedder()
            self._started = True
            ok = await self._run(self._client.ping, op="startup", fallback=False)
            if ok:
                await self._ensure_index()
            self._ensure_worker()

    async def _load_embedder(self) -> None:
        try:
            from agent_core.memory.embedder import get_embedder

            embedder = await asyncio.to_thread(get_embedder)
        except CacheConfigError:
            raise
        except Exception as exc:  # noqa: BLE001 - 第三方模型加载边界，失败只降级 L2
            self._embedder_next_retry = time.monotonic() + 30.0
            self._degraded_reason = f"embedder_unavailable: {self._redact(_short(exc))}"
            logger.warning("语义缓存 embedder 不可用，L2 降级: %s", self._degraded_reason)
            return
        self._resolve_model_from_embedder(embedder)

    async def _ensure_embedder(self) -> Any | None:
        if self._embedder is not None:
            return self._embedder
        if time.monotonic() < self._embedder_next_retry:
            return None
        try:
            await self._load_embedder()
        except CacheConfigError:
            raise
        return self._embedder

    def _ensure_worker(self) -> None:
        if self._worker is not None or self._closing:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._queue = asyncio.Queue(maxsize=self._cfg.write_queue_max)
        self._worker = loop.create_task(self._worker_loop())

    async def _worker_loop(self) -> None:
        queue = self._queue
        if queue is None:
            return
        while True:
            job = await queue.get()
            try:
                if job is _STOP:
                    return
                try:
                    await job()  # type: ignore[operator]
                except _VALKEY_ERRORS as exc:
                    self._record_error(exc, op="write")
                except Exception as exc:  # noqa: BLE001 - worker 边界：单条写失败不得杀死队列
                    self._record_error(exc, op="write_unexpected")
            finally:
                queue.task_done()

    # ------------------------------------------------------------------ ops
    async def get(
        self,
        *,
        tenant_id: str,
        intent: str,
        rewritten_query: str,
        kb_versions: Mapping[str, str] | None = None,
        gray_pct: float = 0.0,
        embedding: Sequence[float] | None = None,
    ) -> CacheHit | None:
        if not tenant_id:
            self._runtime_counts["skipped_no_tenant"] += 1
            self._stats.record("miss")
            return None
        await self.startup()
        key = self._logical_key(intent, rewritten_query, kb_versions, tenant_id, gray_pct)
        epoch = await self._current_epoch(tenant_id)
        if epoch is None:
            self._stats.record("miss")
            return None
        keys = self._keys(tenant_id, key, epoch)

        if self._cfg.negative_cache_enabled:
            null_raw = await self._run(self._client.get, keys["null"], op="get_null", fallback=_MISSING)
            if null_raw is not _MISSING and null_raw is not None:
                self._stats.record("null_hit")
                return CacheHit(value={}, layer="null")

        raw = await self._run(self._client.get, keys["l1"], op="get_l1", fallback=_MISSING)
        if raw is not _MISSING and raw:
            try:
                value = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                value = None
            if isinstance(value, dict):
                self._stats.record("l1_hit")
                return CacheHit(value=value, layer="l1")

        vector = await self._resolve_embedding(embedding, rewritten_query)
        if vector is not None and self._dim > 0 and await self._ensure_index():
            hit = await self._search_l2(
                tenant_id=tenant_id,
                vector=vector,
                epoch=epoch,
                kb_versions=kb_versions,
                gray_pct=gray_pct,
            )
            if hit is not None:
                self._stats.record("l2_hit")
                return hit

        self._stats.record("miss")
        return None

    async def set(
        self,
        *,
        tenant_id: str,
        intent: str,
        rewritten_query: str,
        value: Mapping[str, Any],
        kb_versions: Mapping[str, str] | None = None,
        gray_pct: float = 0.0,
        embedding: Sequence[float] | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        if not tenant_id:
            self._runtime_counts["skipped_no_tenant"] += 1
            return
        try:
            value_json = json.dumps(dict(value), ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            self._record_error(exc, op="set_serialize")
            return
        # 写侧 PII 门禁（单一实现，两个调用点都无法漏接）：缓存是另一套系统里的持久
        # 副本，而命中路径直接返回答案、不再跑应用的输出护栏（联邦只记日志、
        # agent_server 根本没有输出护栏）⇒ 检出 PII 就不落缓存，响应本身不变。
        pii_types = {f["type"] for f in detect_pii(value_json)} | {f["type"] for f in detect_pii(rewritten_query)}
        if pii_types:
            self._runtime_counts["skipped_pii"] += 1
            logger.warning("语义缓存跳过写入（检出 PII: %s）", sorted(pii_types))
            return
        await self.startup()
        if not self._breaker.allow():
            return
        vector = await self._resolve_embedding(embedding, rewritten_query)
        key = self._logical_key(intent, rewritten_query, kb_versions, tenant_id, gray_pct)
        kb_sig = self._kb_signature(kb_versions)
        gray_tag = self._gray_tag(gray_pct)
        ttl = self._ttl(ttl_seconds)
        # 显式 ttl_seconds 同时约束 L1/L2：只改 L1 会让"短 TTL"语义在 L2 失效。
        l2_ttl = int(ttl_seconds) if ttl_seconds is not None else int(self._cfg.l2_ttl_seconds)

        async def _job() -> None:
            epoch = await self._current_epoch(tenant_id)
            if epoch is None:
                return
            keys = self._keys(tenant_id, key, epoch)
            await self._write_positive(
                keys=keys,
                value_json=value_json,
                vector=vector,
                tenant_id=tenant_id,
                intent=intent,
                rewritten_query=rewritten_query,
                kb_sig=kb_sig,
                gray_tag=gray_tag,
                epoch=epoch,
                ttl=ttl,
                l2_ttl=l2_ttl,
            )

        self._enqueue(_job)

    async def set_negative(
        self,
        *,
        tenant_id: str,
        intent: str,
        rewritten_query: str,
        kb_versions: Mapping[str, str] | None = None,
        gray_pct: float = 0.0,
    ) -> None:
        if not tenant_id:
            self._runtime_counts["skipped_no_tenant"] += 1
            return
        if not self._cfg.negative_cache_enabled:
            return
        await self.startup()
        if not self._breaker.allow():
            return
        key = self._logical_key(intent, rewritten_query, kb_versions, tenant_id, gray_pct)

        async def _job() -> None:
            epoch = await self._current_epoch(tenant_id)
            if epoch is None:
                return
            keys = self._keys(tenant_id, key, epoch)
            await self._run(
                lambda: self._client.delete(keys["l1"], keys["l2"]),
                op="delete_positive",
            )
            await self._run(
                lambda: self._client.set(keys["null"], "1", ex=self._cfg.null_ttl_seconds),
                op="set_null",
            )

        self._enqueue(_job)

    async def invalidate(
        self,
        *,
        tenant_id: str,
        intent: str,
        rewritten_query: str,
        kb_versions: Mapping[str, str] | None = None,
        gray_pct: float = 0.0,
    ) -> None:
        if not tenant_id:
            self._runtime_counts["skipped_no_tenant"] += 1
            return
        await self.startup()
        key = self._logical_key(intent, rewritten_query, kb_versions, tenant_id, gray_pct)
        epoch = await self._current_epoch(tenant_id)
        if epoch is None:
            return
        keys = self._keys(tenant_id, key, epoch)
        await self._run(
            lambda: self._client.delete(keys["l1"], keys["l2"], keys["null"]),
            op="invalidate",
        )

    async def invalidate_namespace(self, *, tenant_id: str) -> None:
        if not tenant_id:
            self._runtime_counts["skipped_no_tenant"] += 1
            return
        await self.startup()
        epoch_key = self._epoch_key(tenant_id)

        async def _bump() -> Any:
            # epoch key 必须常驻：过期会让 epoch 归零、旧 epoch 的数据 key 复活
            # （显式 ttl_seconds 可长于 CACHE_L1/L2_TTL）；persist 清掉旧版本遗留的 TTL。
            pipe = self._client.pipeline(transaction=True)
            pipe.incr(epoch_key)
            pipe.persist(epoch_key)
            return await pipe.execute()

        await self._run(_bump, op="invalidate_namespace")

    async def flush(self) -> None:
        if self._queue is None:
            return
        try:
            await asyncio.wait_for(
                self._queue.join(),
                timeout=self._cfg.write_flush_timeout_seconds,
            )
        except TimeoutError:
            logger.warning("语义缓存写队列排空超时（%ss）", self._cfg.write_flush_timeout_seconds)

    async def health(self) -> CacheHealth:
        if self._closing:
            return CacheHealth(backend="valkey", ready=False, degraded_reason="closed", index=None)
        ok = bool(await self._run(self._client.ping, op="ping", fallback=False))
        reason = self._degraded_reason
        if not ok and not reason:
            reason = "valkey_unreachable"
        return CacheHealth(
            backend="valkey",
            ready=ok,
            degraded_reason=reason,
            index=self._index if self._index_ready else None,
        )

    async def aclose(self) -> None:
        if self._closing:
            return
        self._closing = True
        if self._queue is not None and self._worker is not None:
            try:
                await self.flush()
            finally:
                self._worker.cancel()
                await asyncio.gather(self._worker, return_exceptions=True)
                self._worker = None
        close = getattr(self._client, "aclose", None)
        try:
            if close is not None:
                await close()
            else:  # pragma: no cover - 兼容旧版客户端
                await self._client.close()
        except _VALKEY_ERRORS as exc:
            logger.warning("语义缓存关闭连接失败: %s", self._redact(_short(exc)))

    def get_stats(self) -> dict[str, Any]:
        snapshot: dict[str, Any] = dict(self._stats.snapshot())
        snapshot.update(self._runtime_counts)
        snapshot["backend"] = "valkey"
        snapshot["scope"] = self._scope
        return snapshot

    def reset_stats(self) -> None:
        self._stats.reset()
        for key in self._runtime_counts:
            self._runtime_counts[key] = 0

    # ------------------------------------------------------------------ internals
    def _logical_key(
        self,
        intent: str,
        rewritten_query: str,
        kb_versions: Mapping[str, str] | None,
        tenant_id: str,
        gray_pct: float,
    ) -> str:
        return build_cache_key(
            intent,
            rewritten_query,
            kb_versions,
            tenant_id,
            gray_pct,
            scope=self._scope,
            embedding_model=self._model,
            dim=self._dim,
        )

    @staticmethod
    def _kb_signature(kb_versions: Mapping[str, str] | None) -> str:
        if not kb_versions:
            return "none"
        raw = json.dumps(dict(kb_versions), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _gray_tag(gray_pct: float) -> str:
        return f"{float(gray_pct):g}"

    @staticmethod
    def _tenant_token(tenant_id: str) -> str:
        return hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:16]

    def _epoch_key(self, tenant_id: str) -> str:
        return f"{self._ns}epoch:{self._tenant_token(tenant_id)}"

    def _keys(self, tenant_id: str, logical_key: str, epoch: int) -> dict[str, str]:
        prefix = f"{self._ns}"
        return {
            "l1": f"{prefix}l1:{epoch}:{logical_key}",
            "l2": f"{prefix}l2:{epoch}:{logical_key}",
            "null": f"{prefix}null:{epoch}:{logical_key}",
        }

    def _ttl(self, ttl_seconds: int | None) -> int:
        ttl = int(ttl_seconds) if ttl_seconds is not None else int(self._cfg.l1_ttl_seconds)
        return max(1, ttl)

    async def _current_epoch(self, tenant_id: str) -> int | None:
        raw = await self._run(
            self._client.get,
            self._epoch_key(tenant_id),
            op="get_epoch",
            fallback=_MISSING,
        )
        if raw is _MISSING:
            return None
        if raw is None:
            return 0
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    async def _resolve_embedding(
        self,
        embedding: Sequence[float] | None,
        text: str,
    ) -> list[float] | None:
        if embedding is not None:
            vector = [float(x) for x in embedding]
            if self._dim > 0 and len(vector) != self._dim:
                self._runtime_counts["embedding_error"] += 1
                logger.warning(
                    "语义缓存 embedding 维度不匹配：期望 %s，实际 %s；跳过 L2",
                    self._dim,
                    len(vector),
                )
                return None
            return vector
        if self._dim <= 0:
            return None
        embedder = await self._ensure_embedder()
        if embedder is None:
            return None
        try:
            vector = [float(x) for x in await embed_one(embedder, text)]
        except Exception as exc:  # noqa: BLE001 - embedder 边界，失败只跳过 L2
            self._runtime_counts["embedding_error"] += 1
            logger.warning("语义缓存 embedding 失败（跳过 L2）: %s", self._redact(_short(exc)))
            return None
        if len(vector) != self._dim:
            self._runtime_counts["embedding_error"] += 1
            logger.warning("语义缓存 embedding 维度漂移：期望 %s，实际 %s；跳过 L2", self._dim, len(vector))
            return None
        return vector

    async def _write_positive(
        self,
        *,
        keys: Mapping[str, str],
        value_json: str,
        vector: list[float] | None,
        tenant_id: str,
        intent: str,
        rewritten_query: str,
        kb_sig: str,
        gray_tag: str,
        epoch: int,
        ttl: int,
        l2_ttl: int,
    ) -> None:
        tenant_tag = self._valid_tag(tenant_id)
        scope_tag = self._valid_tag(self._scope)
        if tenant_tag is None or scope_tag is None:
            # 原因分账：星号结尾属"配置里有非法隔离值"，与"没有租户"是两回事，
            # 混在一起会让容量/命中率排查找错方向。
            self._runtime_counts[self._skip_counter(tenant_id, self._scope)] += 1
            return

        async def _write() -> Any:
            pipe = self._client.pipeline(transaction=False)
            pipe.set(keys["l1"], value_json, ex=ttl)
            pipe.delete(keys["null"])
            if vector is not None and self._dim > 0 and await self._ensure_index():
                pipe.hset(
                    keys["l2"],
                    mapping={
                        "tenant": tenant_tag,
                        "scope": scope_tag,
                        "kb_version": kb_sig,
                        "gray_pct": gray_tag,
                        "epoch": str(epoch),
                        "intent": intent,
                        "query_text": rewritten_query,
                        "value_json": value_json,
                        "query_vec": _vec_bytes(vector),
                    },
                )
                pipe.expire(keys["l2"], max(1, l2_ttl))
            return await pipe.execute()

        await self._run(_write, op="set_positive")

    async def _search_l2(
        self,
        *,
        tenant_id: str,
        vector: list[float],
        epoch: int,
        kb_versions: Mapping[str, str] | None,
        gray_pct: float,
    ) -> CacheHit | None:
        tenant_tag = self._valid_tag(tenant_id)
        scope_tag = self._valid_tag(self._scope)
        if tenant_tag is None or scope_tag is None:
            # 原因分账：星号结尾属"配置里有非法隔离值"，与"没有租户"是两回事，
            # 混在一起会让容量/命中率排查找错方向。
            self._runtime_counts[self._skip_counter(tenant_id, self._scope)] += 1
            return None
        kb_sig = self._kb_signature(kb_versions)
        gray_tag = self._gray_tag(gray_pct)
        filter_expr = (
            f"(@tenant:{{{_escape_tag(tenant_tag)}}}"
            f" @scope:{{{_escape_tag(scope_tag)}}}"
            f" @kb_version:{{{_escape_tag(kb_sig)}}}"
            f" @gray_pct:{{{_escape_tag(gray_tag)}}}"
            f" @epoch:{{{epoch}}})"
        )
        # 只回传读路径真正要用的两个字段。这不是"优化"，是**正确性**：客户端是
        # decode_responses=True 建的，而 `query_vec` 存的是原始 float32 字节 ⇒ 不带 RETURN 时
        # 引擎把向量一起回传，valkey-py 对它做 UTF-8 解码，抛
        # `UnicodeDecodeError: 'utf-8' codec can't decode byte 0x80 in position 2`，
        # 被 fail-open 吞成永久 miss（2026-10-26 契约首跑的四条红就是这个）。
        # 本行刻意反向于此前"不写 return_fields"的决定——当时担心的是 `distance` 是 KNN
        # 结果别名、不是 schema 字段，"能不能 RETURN 出来"未证实；真机已证实可以
        # （`RETURN 2 value_json distance` → [value_json=…, distance=0]），所以未证实项已消除。
        query = (
            Query(f"{filter_expr}=>[KNN 1 @query_vec $vec AS distance]")
            .dialect(2)
            .return_fields("value_json", "distance")
        )
        # valkey-py 6.2 的 Query 没有 add_param：参数必须作为 search(query, query_params=...)
        # 传进去，写进 Query 链会在运行期 AttributeError（契约测试在无服务时会整段跳过，
        # 该类错误只能靠真机契约或本文件的构造期单测兜住）。
        params = {"vec": _vec_bytes(vector)}

        async def _search() -> Any:
            return await self._client.ft(self._index).search(query, query_params=params)

        result = await self._run(_search, op="search_l2", fallback=None)
        if not result or not getattr(result, "docs", None):
            return None
        doc = result.docs[0]
        distance = getattr(doc, "distance", None)
        if distance is None:
            distance = getattr(doc, "__dict__", {}).get("distance")
        try:
            distance = float(distance)
        except (TypeError, ValueError):
            return None
        threshold = self._cfg.threshold_for(self._scope)
        if distance > threshold:
            return None
        value_raw = getattr(doc, "value_json", None)
        if value_raw is None:
            value_raw = getattr(doc, "__dict__", {}).get("value_json")
        try:
            value = json.loads(value_raw)
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(value, dict):
            return None
        return CacheHit(
            value=value,
            layer="l2",
            distance=distance,
            similarity=1.0 - distance,
        )

    def _enqueue(self, job: Callable[[], Awaitable[None]]) -> None:
        self._ensure_worker()
        if self._queue is None:
            return
        try:
            self._queue.put_nowait(job)
        except asyncio.QueueFull:
            self._runtime_counts["dropped_writes"] += 1
            logger.warning("语义缓存写队列已满，丢弃一次写入（fail-open）")

    async def _ensure_index(self) -> bool:
        if self._index_ready:
            return True
        if self._dim <= 0:
            self._runtime_counts["l2_unavailable"] += 1
            return False
        now = time.monotonic()
        if now < self._index_next_retry:
            return False
        async with self._index_lock:
            if self._index_ready:
                return True
            ft = self._client.ft(self._index)
            try:
                await ft.info()
                self._mark_index_ready()
                return True
            except ResponseError:
                pass
            except _VALKEY_ERRORS as exc:
                self._record_error(exc, op="index_info")
                return False
            try:
                schema = (
                    # TAG 默认大小写不敏感：tenant 若含同名不同大小写会被合并成同一
                    # tag，L2 过滤就可能跨租户命中，故隔离维度必须 CASESENSITIVE。
                    TagField("tenant", separator=_TAG_SEPARATOR, case_sensitive=True),
                    TagField("scope", separator=_TAG_SEPARATOR, case_sensitive=True),
                    TagField("kb_version", separator=_TAG_SEPARATOR, case_sensitive=True),
                    TagField("gray_pct", separator=_TAG_SEPARATOR, case_sensitive=True),
                    TagField("epoch", separator=_TAG_SEPARATOR, case_sensitive=True),
                    TextField("intent", no_stem=True),
                    TextField("query_text", no_stem=True),
                    TextField("value_json", no_stem=True),
                    # valkey-py 6.2 签名是 (name, algorithm, attributes: dict)；
                    # 平铺传参会被当成多余位置参数，建索引直接 TypeError。
                    VectorField(
                        "query_vec",
                        "HNSW",
                        {
                            "TYPE": "FLOAT32",
                            "DIM": self._dim,
                            "DISTANCE_METRIC": "COSINE",
                        },
                    ),
                )
                definition = IndexDefinition(
                    prefix=[f"{self._ns}l2:"],
                    index_type=IndexType.HASH,
                )
                await ft.create_index(schema, definition=definition)
                self._mark_index_ready()
                logger.info("Valkey Search 索引已创建: %s (dim=%s)", self._index, self._dim)
                return True
            except _VALKEY_ERRORS as exc:
                try:
                    await ft.info()
                    self._mark_index_ready()
                    return True
                except _VALKEY_ERRORS:
                    pass
                self._index_next_retry = now + 30.0
                self._runtime_counts["l2_unavailable"] += 1
                self._degraded_reason = f"search_index_unavailable: {self._redact(_short(exc))}"
                logger.warning("Valkey Search 索引不可用，L2 降级: %s", self._degraded_reason)
                return False

    def _mark_index_ready(self) -> None:
        self._index_ready = True
        if self._degraded_reason and self._degraded_reason.startswith("search_index_unavailable"):
            self._degraded_reason = None

    @staticmethod
    def _tag_reject_reason(value: str) -> str | None:
        """隔离维度取值的拒绝原因；``None`` = 可用。

        ``wildcard`` 这一支是真机测出来的，不是推测：在 valkey-bundle 9.1.2（search 1.2.1）上
        以 `acme` / `acmeX` / 字面 `acme*` 三个租户值建索引后，`@tenant:{acme*}` 命中 3 条
        （前缀匹配成立），而 `@tenant:{acme\\*}` **同样命中 3 条**——反斜杠被引擎忽略，星号仍是
        通配符。所以 `_escape_tag()` 对 `*` 无效，"转义集里有 `*`"并不构成防线（`|` 的转义实测
        有效，两者不是一回事）。既然转义不掉，只能拒绝：以 `*` 结尾一律 fail-closed。
        值中间含 `*` 的通配语义尚未在真机确认，本轮不扩大拒绝面，留给上机复验。
        """
        if not value:
            return "empty"
        if any(ch in value for ch in ("\x00", _TAG_SEPARATOR)):
            return "separator"
        if value.endswith("*"):
            return "wildcard"
        return None

    @classmethod
    def _valid_tag(cls, value: str) -> str | None:
        return None if cls._tag_reject_reason(value) is not None else value

    @classmethod
    def _skip_counter(cls, tenant_id: str, scope: str) -> str:
        """把"为什么这次没写/没查"归到可区分的计数键上。"""
        reasons = {cls._tag_reject_reason(tenant_id), cls._tag_reject_reason(scope)}
        return "skipped_unsafe_tag" if "wildcard" in reasons else "skipped_no_tenant"

    async def _run(
        self,
        fn: Callable[..., Awaitable[Any]],
        *args: Any,
        op: str,
        fallback: Any = None,
    ) -> Any:
        if not self._breaker.allow():
            if not self._degraded_reason:
                self._degraded_reason = "circuit_open"
            return fallback
        try:
            result = await fn(*args)
        except _VALKEY_ERRORS as exc:
            self._breaker.record_failure()
            self._record_error(exc, op=op)
            return fallback
        self._breaker.record_success()
        if self._degraded_reason and self._degraded_reason.startswith("valkey_unavailable"):
            self._degraded_reason = None
        return result

    def _record_error(self, exc: BaseException, *, op: str) -> None:
        self._runtime_counts["error"] += 1
        message = self._redact(_short(exc))
        self._degraded_reason = f"valkey_unavailable: {message}"
        if self._index_ready and _is_missing_index_error(message):
            # 索引被 FT.DROPINDEX / FLUSHALL 摘掉后，_index_ready 若不清就会把 L2
            # 判成永久可用：每次检索都报错再 fail-open，要到进程重启才恢复。
            # 清掉后下一次读路径重建索引（同一 PREFIX 会自动回索引存量哈希）。
            self._index_ready = False
            self._runtime_counts["index_missing"] += 1
            logger.warning("语义缓存 L2 索引缺失，下次读路径重建: %s", message)
        logger.warning("语义缓存 %s 失败（fail-open）: %s", op, message)

    def _redact(self, text: str) -> str:
        text = redact_url(text)
        raw = self._cfg.valkey_url
        if raw:
            text = text.replace(raw, self._cfg.redacted_url)
        return text


__all__ = ["ValkeySemanticCache"]
