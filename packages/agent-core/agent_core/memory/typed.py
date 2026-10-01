# -*- coding: utf-8 -*-
"""类型化记忆下沉内核（ADR-0004 阶段 1）。

本模块把原先只存在于 ``app/memory/memory_backend.py`` 的类型化读写 / 加权融合 /
遗忘逻辑，下沉为 agent-core 的零依赖可选模块，让 app 与 deepagents 共用单一真相源。

设计约束（ADR-0004 v2.1）：
1. 由 ``SEMANTIC_MEMORY_TYPED`` 开关控制，**不替换**现有 ``recall_memories`` /
   ``remember_memory``；旧门面仍可用。
2. ``TypedMemory`` 用 stdlib ``@dataclass``（不引 pydantic，保持内核零依赖）。
3. 内核 API：``recall_typed`` / ``remember_typed`` / ``consolidate`` / ``forget``，
   加权融合 ``type_weight × importance × time_decay``。
4. 与 app 共用宿主 psycopg 池（``%s`` 占位符 + ``pool.connection()``），**不自建
   asyncpg 池**，不依赖 ``app.infra.db.vector_search``，遵守 ADR-0003（单一连接源）。
5. pg 模式 typed 路径接收宿主池直接读 ``memories`` 的类型/重要性/时间列；Milvus
   模式（无类型列）由调用方降级到无类型平权召回，本模块仅提供 SQL 实现。

§3 内核护栏：核心逻辑仅 stdlib；不 import langchain / openai / fastapi / psycopg
（psycopg 仅作为鸭子类型协议在运行时经宿主池传入，不在此硬依赖）。
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from agent_core.memory._tenant_gate import _TENANT_UNSET, resolve_tenant

logger = logging.getLogger(__name__)


# --- 类型定义 --------------------------------------------------------------

class MemoryType(str, Enum):
    """记忆类型枚举（ADR-0004：episodic/semantic/procedural）。"""

    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"

    @classmethod
    def normalize(cls, value: object) -> "MemoryType":
        """把任意输入归一化为合法 MemoryType；非法值降级 semantic。"""
        if isinstance(value, MemoryType):
            return value
        try:
            return cls(str(value).lower())
        except ValueError:
            return cls.SEMANTIC


@dataclass
class TypedMemory:
    """单条带类型元数据的记忆（零依赖 dataclass）。"""

    content: str
    memory_type: MemoryType
    importance: float
    created_at: datetime.datetime | None = None
    memory_id: object | None = None

    # 融合分，由 recall_typed 填充，便于调试/排序复现
    score: float = 0.0


# --- 默认加权系数（ADR-0004 约束 3）---------------------------------------

DEFAULT_TYPE_WEIGHTS: dict[MemoryType, float] = {
    MemoryType.PROCEDURAL: 1.2,
    MemoryType.SEMANTIC: 1.1,
    MemoryType.EPISODIC: 1.0,
}

TYPE_WEIGHTS_RAW: dict[str, float] = {
    "procedural": 1.2,
    "semantic": 1.1,
    "episodic": 1.0,
}

TIME_DECAY_COEFF: float = 0.01  # 双曲衰减 1/(1 + 0.01*age_days)


# --- 开关 ------------------------------------------------------------------

def semantic_memory_typed_enabled() -> bool:
    """``SEMANTIC_MEMORY_TYPED`` 加权策略开关（WS-1 起默认开）。

    语义变更（WS-1）：本开关不再决定「走哪条栈」（统一经 MemoryStore），
    只控制 typed 召回是否启用加权融合（``type_weight × importance × time_decay``）；
    关闭时退化为平权召回（按时间衰减排序）。``SEMANTIC_MEMORY_ENABLED`` 才是
    记忆总开关。加权系数默认写死，``weights`` 入参可覆盖（ADR-0004 约束 2）。
    WS-5：经内核配置层 ``env_bool`` 解析（非法值警告 + 回退默认）。
    """
    from agent_core.config import env_bool

    return env_bool("SEMANTIC_MEMORY_TYPED", True)


def _normalize_weights(weights: Iterable[tuple[str, float]] | None) -> dict[str, float]:
    """把可选 ``weights`` 入参（(type, weight) 序列）合入默认系数。"""
    merged = dict(TYPE_WEIGHTS_RAW)
    if weights:
        for mtype, w in weights:
            key = MemoryType.normalize(mtype).value
            merged[key] = float(w)
    return merged


def _clamp_importance(importance: float) -> float:
    return max(0.0, min(1.0, float(importance)))


# v5 租户隔离安全语义（P0 审计修复，2026-09-25）：
# 历史 legacy 行（v5 前 tenant_id=''，迁移后归入 'default'）只归属 'default'
# 租户可见。**不做** "真实租户 + default" 过渡读——那会让 tenantA/tenantB 共享
# default 桶记忆，形成跨租户泄漏。原则：归属不明的 legacy 记忆宁可暂时不可见，
# 也不跨租户可见；读/写/删路径统一精确 tenant_id 匹配。

# v8 双 scope（ADR-0006 T13 / TD-13 收口）：同一张 memories 表承载两种归属。
# 形参位语义澄清（TD-13 裁定：不重命名形参与列）：
# - ``user_id`` 形参位是「归属键（scope key）」：双 scope 前各宿主在其中实装
#   workspace_id（TD-13 现状）；双 scope 后新建行按 ``scope`` 列消歧——
#   scope='user' 行落真实 user_id、scope='workspace' 行落 workspace_id 列
#   （user_id 列位写 'default' 占位，与 migration 008 回填形态一致）；
#   过渡期读取对 scope key 做 (user_id 列 OR workspace_id 列) 双列匹配，
#   两侧调用方（workspace 语义）在滚动升级窗口内行为不变；
#   同一部署内承载哪种语义必须由调用方显式决定并保持一致。
SCOPE_WORKSPACE = "workspace"
SCOPE_USER = "user"
_VALID_SCOPES = frozenset({SCOPE_WORKSPACE, SCOPE_USER})
# workspace 行在 user_id 列位的占位值（与 008 回填一致；不再是真实用户）
_WORKSPACE_USER_PLACEHOLDER = "default"


def memory_dual_scope_enabled() -> bool:
    """双 scope 写入布局开关（``MEMORY_DUAL_SCOPE``，默认关）。

    关闭时 workspace 行维持旧布局（归属键直接落 ``user_id`` 列，与旧实例
    读谓词兼容），user 画像行降级为 workspace 行（宁可画像暂不可用，
    不在 schema 未就绪时写错位行）；全量应用 migration 008 后翻开开关，
    新行改写 ``workspace_id``/``scope`` 新布局。读路径始终双列兼容，
    开关翻转无需停机窗口。
    """
    from agent_core.config import env_bool

    return env_bool("MEMORY_DUAL_SCOPE", False)


def _normalize_scope(scope: object) -> str:
    """非法/缺失 scope 降级 workspace（首期写入路由默认，行为零变更）。"""
    s = str(scope).strip().lower()
    return s if s in _VALID_SCOPES else SCOPE_WORKSPACE


def _time_decay(created_at: datetime.datetime | None, now: datetime.datetime) -> float:
    """双曲时间衰减 1/(1 + 0.01*age_days)；无时间信息时退化为 1.0。"""
    if created_at is None:
        return 1.0
    ref = created_at
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=datetime.timezone.utc)
    age_days = max(0.0, (now - ref).total_seconds() / 86400.0)
    return 1.0 / (1.0 + TIME_DECAY_COEFF * age_days)


def _score_memory(mtype: MemoryType, importance: float, created_at, now,
                  weights: dict[str, float]) -> float:
    type_weight = weights.get(mtype.value, 1.0)
    decay = _time_decay(created_at, now)
    return type_weight * float(importance) * decay


# --- 内核 API（pg 模式，接收宿主 psycopg 池）-------------------------------

def _to_pg_vector(embedding):
    """list/tuple embedding → ``pgvector.Vector``（真实 PG 参数适配，P1 修复）。

    pgvector 的 psycopg 适配器只为 ``Vector``/``numpy.ndarray`` 注册了 dumper；
    宿主 embed_fn 返回的 plain list 会被适配成 ``double precision[]``，
    在真实 PG 上 ``<=>`` 算子与 vector 列赋值均报
    ``operator does not exist: vector <=> double precision[]``
    （由 tests/ha/test_tenant_isolation_real_pg.py 行为级回归首次暴露）。
    pgvector 未安装时惰性回退 list（内存 fake / 单测场景不受影响）。
    """
    if isinstance(embedding, (list, tuple)):
        try:
            from pgvector import Vector
        except ImportError:
            return list(embedding)
        return Vector(embedding)
    return embedding


def _score_rows(
    rows: list, weights: Iterable[tuple[str, float]] | None = None
) -> list[TypedMemory]:
    """对 rows（(content, memory_type, importance, created_at) 或降级元组）统一打分。

    按 ``type_weight × importance × time_decay`` 评分并降序排序（评分公式不变），
    返回带 ``score`` 的 ``list[TypedMemory]``；``SEMANTIC_MEMORY_TYPED`` 关时退化平权。
    供 workspace / user 两路召回复用，保证两路得分可比、能在上层融合。
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    merged = _normalize_weights(weights)
    typed_enabled = semantic_memory_typed_enabled()
    scored: list[TypedMemory] = []
    for row in rows:
        content = row[0]
        if len(row) >= 4:
            mtype = MemoryType.normalize(row[1])
            importance = float(row[2])
            created_at = row[3]
        else:
            # 降级（无类型列，如 Milvus 模式）：平权
            mtype = MemoryType.SEMANTIC
            importance = 0.5
            created_at = row[1] if len(row) > 1 else None
        if typed_enabled:
            score = _score_memory(mtype, importance, created_at, now, merged)
        else:
            score = _time_decay(created_at, now)
        scored.append(
            TypedMemory(
                content=content, memory_type=mtype, importance=importance,
                created_at=created_at, score=score,
            )
        )
    scored.sort(key=lambda m: m.score, reverse=True)
    return scored


async def remember_typed(
    pool,
    user_id: str,
    fact: str,
    memory_type: object = "semantic",
    importance: float = 0.5,
    embedding: list[float] | None = None,
    *,
    tenant_id: str= _TENANT_UNSET,
) -> None:
    """沉淀一条带类型/重要性的结构化记忆（workspace 旧 6 列布局）。

    ADR-0004 向后兼容：本函数为既有公开符号，**签名不变**（不承载 scope），
    固定按旧 6 列布局将 ``user_id`` 形参位（归属键，当前为 workspace 语义，
    见模块头 TD-13 注释）写入 ``user_id`` 列，新行 ``scope`` 取表缺省 'workspace'。
    需写跨 workspace 用户画像请改用 :func:`remember_typed_scoped`。
    embedding 必须由宿主层提供（内核不下沉 embedder）。
    """
    tenant_id = resolve_tenant(tenant_id)
    mtype = MemoryType.normalize(memory_type)
    importance = _clamp_importance(importance)
    if embedding is None:
        raise ValueError(
            "embed_memory 由宿主层提供；内核 typed.remember_typed 不内嵌 embedder"
        )
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO memories (tenant_id, user_id, content, embedding, memory_type, importance) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (tenant_id, user_id, fact, _to_pg_vector(embedding), mtype.value, importance),
        )


async def remember_typed_scoped(
    pool,
    tenant_id: str,
    user_id: str,
    workspace_id: str | None,
    scope: str,
    fact: str,
    memory_type: object = "semantic",
    importance: float = 0.5,
    *,
    embedding: list[float] | None = None,
) -> None:
    """双 scope 写入（ADR-0006 T13 新增公开函数，不改 5 个旧符号）。

    参数顺序与 plan T13 一致（pool, tenant_id, user_id, workspace_id, scope, fact, ...）；
    embedding 为 kw-only（内核不下沉 embedder，与旧符号同约束，宿主传入）。

    归属路由：
    - ``scope='workspace'``：行落 ``workspace_id`` 列（未传时用 ``user_id`` 形参位值），
      ``user_id`` 列位写 ``'default'`` 占位（与 migration 008 回填一致）；
    - ``scope='user'``：跨该用户所有 workspace 的画像行，真实用户落 ``user_id`` 列，
      ``workspace_id`` 仅溯源。
    渐进开关 ``MEMORY_DUAL_SCOPE`` 关时：降级为旧 6 列 workspace 行（画像不跨空间，
    不写错位行）；读路径始终双列兼容，开关翻转无需停机。
    """
    tenant_id = resolve_tenant(tenant_id)
    mtype = MemoryType.normalize(memory_type)
    importance = _clamp_importance(importance)
    scope = _normalize_scope(scope)
    if embedding is None:
        raise ValueError(
            "embed_memory 由宿主层提供；内核 typed.remember_typed_scoped 不内嵌 embedder"
        )
    if not memory_dual_scope_enabled():
        # 旧布局：归属键落 user_id 列（workspace 语义），scope 列取表缺省 'workspace'。
        key = workspace_id if workspace_id is not None else user_id
        async with pool.connection() as conn:
            await conn.execute(
                "INSERT INTO memories (tenant_id, user_id, content, embedding, memory_type, importance) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (tenant_id, key, fact, _to_pg_vector(embedding), mtype.value, importance),
            )
        return
    if scope == SCOPE_USER:
        row_user_id, row_workspace_id = user_id, workspace_id
    else:
        row_user_id = _WORKSPACE_USER_PLACEHOLDER
        row_workspace_id = workspace_id if workspace_id is not None else user_id
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO memories "
            "(tenant_id, user_id, workspace_id, scope, content, embedding, memory_type, importance) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                tenant_id, row_user_id, row_workspace_id, scope,
                fact, _to_pg_vector(embedding), mtype.value, importance,
            ),
        )


async def recall_typed(
    pool,
    user_id: str,
    question: str,
    k: int = 3,
    weights: Iterable[tuple[str, float]] | None = None,
    embedding: list[float] | None = None,
    *,
    tenant_id: str= _TENANT_UNSET,
) -> list[TypedMemory]:
    """workspace 路分层加权召回（pg 模式）。ADR-0004 公开符号，**签名不变**。

    语义召回 memories（scope='workspace'，归属键双列兼容）后，按
    ``type_weight × importance × time_decay`` 融合排序，返回 k 条 ``TypedMemory``。
    跨 workspace 用户画像请另调 :func:`recall_user_profile`（两路融合由门面完成）。
    """
    tenant_id = resolve_tenant(tenant_id)
    if embedding is None:
        raise ValueError(
            "embed_memory 由宿主层提供；内核 typed.recall_typed 不内嵌 embedder"
        )
    rows = await _vector_search_memories(pool, tenant_id, user_id, embedding, k=k * 2)
    if not rows:
        return []
    return _score_rows(rows, weights)[:k]


async def recall_user_profile(
    pool,
    tenant_id: str,
    user_id: str,
    question: str,
    k: int = 3,
    *,
    embedding: list[float] | None = None,
    weights: Iterable[tuple[str, float]] | None = None,
) -> list[TypedMemory]:
    """用户画像路召回（ADR-0006 T13 新增，跨该用户所有 workspace 的 scope='user' 行）。

    与 :func:`recall_typed` 同一评分（``type_weight × importance × time_decay``）→
    两路返回的 ``TypedMemory.score`` 可直接在上层融合（不改评分公式）。仅在
    ``MEMORY_DUAL_SCOPE`` 开启且 schema 含 scope/workspace_id 列时有数据（否则为空）。
    embedding 为 kw-only（内核不下沉 embedder）。
    """
    tenant_id = resolve_tenant(tenant_id)
    if embedding is None:
        raise ValueError(
            "embed_memory 由宿主层提供；内核 typed.recall_user_profile 不内嵌 embedder"
        )
    rows = await _vector_search_user_profile(pool, tenant_id, user_id, embedding, k=k * 2)
    if not rows:
        return []
    return _score_rows(rows, weights)[:k]


def memory_forget_threshold() -> float:
    """遗忘重要度阈值（TD-6 参数化）。

    读环境变量 ``MEMORY_FORGET_THRESHOLD``；缺省回退历史常量 ``0.1``。
    基线采集后（ADR-0004 候选A 被驳回原因：缺数据）可按业务覆盖。
    WS-5：经 ``env_float`` 解析（非法值警告 + 回退默认）。
    """
    from agent_core.config import env_float

    return env_float("MEMORY_FORGET_THRESHOLD", 0.1)


def memory_forget_age_days() -> int:
    """遗忘老化天数（TD-6 参数化）。

    读环境变量 ``MEMORY_FORGET_AGE_DAYS``；缺省回退历史常量 ``30``。
    SQL 端用参数化 ``interval '%s days'``，避免写死字面量。
    WS-5：经 ``env_int`` 解析（非法值警告 + 回退默认）。
    """
    from agent_core.config import env_int

    return env_int("MEMORY_FORGET_AGE_DAYS", 30)


async def consolidate(
    user_id,
    pool,
    forget_threshold: float | None = None,
    age_days: int | None = None,
    *,
    tenant_id: str= _TENANT_UNSET,
) -> int:
    """巩固 + 遗忘（ADR-0004 D4/D5，TD-6 阈值/老化天数参数化）。

    淘汰「importance 低于阈值且超过 age_days 天」的低价值记忆，返回删除条数。
    完整 SQL 逻辑，与 app 既有 ``consolidate_memories`` 一致，仅内核化。

    Args:
        forget_threshold: 重要度淘汰阈值；``None`` 时取 ``memory_forget_threshold()``。
        age_days: 老化天数；``None`` 时取 ``memory_forget_age_days()``。
    """
    tenant_id = resolve_tenant(tenant_id)
    if forget_threshold is None:
        forget_threshold = memory_forget_threshold()
    if age_days is None:
        age_days = memory_forget_age_days()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "DELETE FROM memories "
            "WHERE tenant_id = %s AND scope = %s "
            "AND (workspace_id = %s OR user_id = %s) AND importance < %s "
            "AND created_at < now() - interval '%s days'",
            (tenant_id, SCOPE_WORKSPACE, user_id, user_id, forget_threshold, age_days),
        )
        deleted = getattr(cur, "rowcount", 0) or 0
        logger.info(
            "[typed] consolidate 删除 %d 条（scope key=%s, threshold=%.3f, age_days=%d）",
            deleted, user_id, forget_threshold, age_days,
        )
        return deleted


async def forget(user_id, pool, memory_id, *, tenant_id: str= _TENANT_UNSET) -> bool:
    """按 memory_id 删除单条记忆，返回是否实际删除。

    归属断言与召回对称：tenant 精确匹配 + scope key 双列兼容（新行落
    workspace_id、旧行落 user_id），不跨租户删除。
    """
    tenant_id = resolve_tenant(tenant_id)
    async with pool.connection() as conn:
        cur = await conn.execute(
            "DELETE FROM memories "
            "WHERE tenant_id = %s AND (workspace_id = %s OR user_id = %s) AND id = %s",
            (tenant_id, user_id, user_id, memory_id),
        )
        return (getattr(cur, "rowcount", 0) or 0) > 0


# --- 内部：带类型的向量召回（%s 风格，宿主 psycopg 池）---------------------

async def _vector_search_memories(
    pool, tenant_id: str, user_id: str, embedding: list[float], k: int = 6
):
    """memories 表 workspace 路径向量召回，返回 (content, memory_type, importance, created_at)。

    使用 pgvector 余弦距离 ``embedding <=> %s``；标识符 ``memories`` 写死（内核内部
    单一表名），无注入风险。宿主池须已 ``register_vector`` 并支持 ``<=>`` 算子。
    租户谓词为精确 ``tenant_id = %s``（与 consolidate/forget 删除路径同一严格语义），
    不做 legacy ``default`` 桶过渡读（跨租户泄漏风险，见文件头安全语义注释）。

    workspace 归属双列兼容（v8 渐进）：``scope='workspace'`` 限定工作空间行（
    排除 user 画像）；``(workspace_id = %s OR user_id = %s)`` 同时命中已迁移行
    （新列 workspace_id）与未迁移/旧布局行（归属键仍在 user_id）。
    """
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT content, memory_type, importance, created_at "
            "FROM memories "
            "WHERE tenant_id = %s AND scope = %s "
            "AND (workspace_id = %s OR user_id = %s) AND embedding IS NOT NULL "
            "ORDER BY embedding <=> %s LIMIT %s",
            (tenant_id, SCOPE_WORKSPACE, user_id, user_id, _to_pg_vector(embedding), k),
        )
        return await cur.fetchall()


async def _vector_search_user_profile(
    pool, tenant_id: str, profile_user_id: str, embedding: list[float], k: int = 6
):
    """user 画像路：跨该用户所有 workspace 的 scope='user' 向量召回。

    仅在 ``MEMORY_DUAL_SCOPE`` 开启且 schema 已含 scope/workspace_id 列时被调用；
    tenant 精确谓词 + user_id 精确匹配（真实用户），不跨租户、不读 workspace 行。
    返回列与 workspace 路一致，供上层统一融合评分。
    """
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT content, memory_type, importance, created_at "
            "FROM memories "
            "WHERE tenant_id = %s AND scope = %s AND user_id = %s AND embedding IS NOT NULL "
            "ORDER BY embedding <=> %s LIMIT %s",
            (tenant_id, SCOPE_USER, profile_user_id, _to_pg_vector(embedding), k),
        )
        return await cur.fetchall()


__all__ = [
    "MemoryType",
    "TypedMemory",
    "DEFAULT_TYPE_WEIGHTS",
    "SCOPE_WORKSPACE",
    "SCOPE_USER",
    "semantic_memory_typed_enabled",
    "memory_dual_scope_enabled",
    "remember_typed",
    "remember_typed_scoped",
    "recall_typed",
    "recall_user_profile",
    "consolidate",
    "forget",
]
