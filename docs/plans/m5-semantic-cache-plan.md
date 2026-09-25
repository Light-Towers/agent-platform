# M5: SemanticCache 统一规划

## 现状：两套独立实现

### 实现一：`app/infra/cache.py`（66 行，PostgreSQL + pgvector）

| 维度 | 内容 |
|------|------|
| 存储后端 | PostgreSQL + pgvector（`embedding <=> %s` 余弦距离） |
| 向量索引 | **无索引**（全表顺序扫描） |
| Embedding | 调用方传入（`app/rag/embed.py` → OpenAI 兼容 `/embeddings` 或 mock） |
| 相似度 | 余弦距离 `< threshold`（默认 0.05，距离越小越严） |
| 缓存键 | `question.strip().lower()`（明文，非 hash） |
| TTL | **无** |
| 分层 | 单层 |
| 防穿透 | 无 |
| 防击穿 | 无 |
| 统计 | 无 |
| 写入 | `spawn_background` fire-and-forget |
| 开关默认 | `cache_enabled=True` |

调用方：`app/api/routes.py:106-114`（查询前 `cache_lookup`，命中直接 SSE 返回 `cache_hit`；流式结束后 `cache_store` 异步写入）

### 实现二：`agent_federation/agent/cache/`（4 文件 ~600 行，Valkey + HNSW）

| 维度 | 内容 |
|------|------|
| 存储后端 | Valkey（Redis 兼容）+ Valkey Search HNSW 向量索引 |
| 向量索引 | HNSW + COSINE KNN |
| Embedding | 本地 sentence-transformers（`BAAI/bge-small-zh-v1.5`，复用意图分类器 `_embedder`） |
| 相似度 | COSINE 相似度 `>= threshold`（默认 0.92，相似度越大越严） |
| 缓存键 | `sha256(intent|query|kb_versions|tenant_id|gray_pct)` |
| TTL | L1=1h, L2=30min, L3=10min, Null=60s |
| 分层 | L1 精确 + L2 语义 + L3 检索 + NullCache |
| 防穿透 | NullCache（空值短 TTL） |
| 防击穿 | singleflight（已实现未集成） |
| 统计 | `_stats` dict + `get_stats()` 命中率 |
| 写入 | `set_async` fire-and-forget |
| 开关默认 | `CACHE_ENABLED=false` |

调用方：`agent_federation/agent/main_agent.py:192-200`（查询）、`290-296`（异步写入）

### 关键不一致点

1. **阈值方向相反**：app 用距离（0.05，越小越严），agent_federation 用相似度（0.92，越大越严）。转换：`similarity = 1 - distance`
2. **Embedding 模型名义相同但实际不同**：app 走远端 API（或 mock），agent_federation 走本地 sentence-transformers，**向量空间可能不一致**
3. **缓存键策略**：app 用明文小写（无防脏命中），agent_federation 用 sha256（含 kb_versions/tenant/gray 防脏命中）
4. **app 无 TTL** 是显著缺陷
5. **配置来源不同**：app 用 pydantic Settings，agent_federation 用 dataclass + os.getenv

---

## 方案选择

### 方案 A：定义公共接口（Protocol/ABC），保留两套后端实现

```
agent_core/cache/
├── __init__.py
├── base.py          # BaseSemanticCache ABC + CacheStats + build_cache_key
└── null_cache.py    # NullCacheProtocol（防穿透抽象）
```

- `app/infra/cache.py` → `PgSemanticCache(BaseSemanticCache)`
- `agent_federation/agent/cache/` → `ValkeySemanticCache(BaseSemanticCache)`

**优点**：风险最低，保留各后端独特优势（app 零依赖 vs agent_federation 高性能）
**缺点**：不消除后端实现代码，只消除抽象层重复

### 方案 B：统一到单一实现，可插拔后端

```
agent_core/cache/
├── __init__.py
├── base.py          # BaseSemanticCache ABC
├── stats.py         # CacheStats
├── key.py           # build_cache_key
├── pg_backend.py    # PostgreSQL + pgvector 后端
├── valkey_backend.py # Valkey + HNSW 后端
└── semantic_cache.py # 统一入口，按配置选后端
```

**优点**：真正消除重复，单一数据源
**缺点**：重构量大，agent_core 需引入 psycopg/valkey 可选依赖

### 方案 C（推荐）：提取共享抽象到 agent_core，后端实现各自保留

```
agent_core/cache/
├── __init__.py
├── base.py          # BaseSemanticCache ABC + CacheStats + build_cache_key
└── null_cache.py    # NullCache ABC（防穿透）
```

- 共享：接口定义、统计逻辑、缓存键构建、空值缓存抽象
- 各保留：PgSemanticCache（app）、ValkeySemanticCache（agent_federation）
- app 的 `cache_lookup`/`cache_store` 改为 `PgSemanticCache` 类方法
- agent_federation 的 `SemanticCache` 改为 `ValkeySemanticCache(BaseSemanticCache)`

**优点**：消除抽象层重复（~80 行），保留后端灵活性，风险可控
**缺点**：后端实现仍各自维护（但后端代码本就不可复用 — SQL ≠ Valkey 命令）

---

## 推荐方案 C 详细执行计划

### Step 1: `agent_core/cache/base.py` — 共享抽象

```python
# agent_core/cache/base.py
"""语义缓存共享抽象：接口 + 统计 + 缓存键构建。"""

from abc import ABC, abstractmethod
from time import time
from hashlib import sha256
from json import dumps
from typing import Any

class CacheStats:
    """命中率统计（线程安全由调用方保证，asyncio 单线程语义）。"""
    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
    
    def record(self, layer: str) -> None:
        """记录一次命中/未命中。layer: l1_hit/l2_hit/miss/null_hit"""
        self._counts[layer] = self._counts.get(layer, 0) + 1
        self._counts["total"] = self._counts.get("total", 0) + 1
    
    def snapshot(self) -> dict[str, int | float]:
        total = self._counts.get("total", 0) or 1
        hits = sum(self._counts.get(k, 0) for k in ("l1_hit", "l2_hit", "null_hit"))
        return {**self._counts, "hit_rate": round(hits / total, 4)}
    
    def reset(self) -> None:
        self._counts.clear()


def build_cache_key(
    intent: str = "",
    query: str = "",
    kb_versions: dict[str, str] | None = None,
    tenant_id: str = "default",
    gray_pct: float = 0.0,
) -> str:
    """统一缓存键：sha256(intent|query|kb_versions|tenant|gray)。
    
    无 kb_versions 时退化为 sha256(intent|query|tenant)，
    兼容 app 的简单场景。
    """
    kb_str = dumps(kb_versions, sort_keys=True) if kb_versions else "{}"
    raw = f"{intent}|{query}|{kb_str}|{tenant_id}|{gray_pct}"
    return sha256(raw.encode("utf-8")).hexdigest()


class BaseSemanticCache(ABC):
    """语义缓存接口。"""
    
    @abstractmethod
    async def get(self, query: str, embedding: list[float] | None = None, **extra: Any) -> dict[str, Any] | None:
        """查询缓存。返回含 _layer 字段的 dict 或 None。"""
    
    @abstractmethod
    async def set(self, query: str, value: dict[str, Any], embedding: list[float] | None = None, **extra: Any) -> None:
        """写入缓存。"""
    
    @abstractmethod
    async def invalidate(self, query: str, **extra: Any) -> None:
        """手动失效。"""
    
    def get_stats(self) -> dict[str, int | float]:
        return self._stats.snapshot()
    
    def reset_stats(self) -> None:
        self._stats.reset()
```

### Step 2: `agent_core/cache/null_cache.py` — 防穿透抽象

```python
# agent_core/cache/null_cache.py
"""NullCache 防穿透抽象。"""
from abc import ABC, abstractmethod

class BaseNullCache(ABC):
    @abstractmethod
    async def get(self, key: str) -> bool: ...
    
    @abstractmethod
    async def set(self, key: str, ttl: int = 60) -> None: ...
```

### Step 3: `app/infra/cache.py` → `PgSemanticCache(BaseSemanticCache)`

- 将模块级函数 `cache_lookup`/`cache_store` 包装为 `PgSemanticCache` 类
- `get()` 内部调用 `cache_lookup`，`set()` 内部调用 `cache_store`
- 保留 `spawn_background`（app 其他模块也用）
- 缓存键改用 `build_cache_key`（向后兼容：无 kb_versions 时退化为 query hash）
- 加入 `CacheStats` 统计
- `app/api/routes.py` 调用方改为 `PgSemanticCache.get/set`

### Step 4: `agent_federation/agent/cache/` → `ValkeySemanticCache(BaseSemanticCache)`

- `SemanticCache` 类改名为 `ValkeySemanticCache`，继承 `BaseSemanticCache`
- `_build_cache_key` 改为调用 `agent_core.cache.base.build_cache_key`
- `_stats` 改为 `CacheStats` 实例
- `L1Cache`/`L2Cache`/`L3Cache`/`NullCache` 保留（Valkey 特有逻辑）
- `main_agent.py` 调用方改为 `ValkeySemanticCache`

### Step 5: 配置统一

- app 的 `cache_enabled`/`cache_threshold` 保留在 `app/config.py`（PostgreSQL 特有）
- agent_federation 的 `CacheConfig` 保留（Valkey 特有 TTL/索引配置）
- 共享配置（如 `cache_enabled`）已在各自 Settings 中，无需额外提取

---

## 风险与注意事项

1. **向量空间不一致**：app 和 agent_federation 用不同 embedding 模型，统一接口后**不可跨后端共享缓存数据**（各自缓存各自命中，这是现有行为，不改变）
2. **阈值方向**：`BaseSemanticCache` 接口不规定阈值方向，各后端自行解释（距离 vs 相似度）
3. **向后兼容**：app 的 `cache_lookup`/`cache_store` 模块级函数保留为 `PgSemanticCache` 的静态方法别名，避免破坏外部调用
4. **agent_core 依赖**：`base.py` 仅依赖 stdlib（abc/hashlib/json/time），不引入 psycopg/valkey
5. **测试**：需为 `CacheStats` 和 `build_cache_key` 新增 agent_core 单元测试

## 预估变更量

| 文件 | 变更类型 | 行数 |
|------|----------|------|
| `agent-core/agent_core/cache/__init__.py` | 新增 | ~5 |
| `agent-core/agent_core/cache/base.py` | 新增 | ~60 |
| `agent-core/agent_core/cache/null_cache.py` | 新增 | ~15 |
| `agent-core/tests/test_cache_base.py` | 新增 | ~40 |
| `app/infra/cache.py` | 改写 | ~80（66→80） |
| `app/api/routes.py` | 小改 | ~5 行 |
| `agent_federation/agent/cache/semantic_cache.py` | 改写 | ~170（176→170） |
| `agent_federation/agent/cache/layers.py` | 小改 | ~5 行 |
| `agent_federation/agent/main_agent.py` | 小改 | ~3 行 |
| **总计** | | ~380 行变更 |
