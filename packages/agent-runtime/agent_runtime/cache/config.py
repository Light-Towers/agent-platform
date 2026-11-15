"""语义缓存配置（单一来源）。

``CACHE_BACKEND`` 只接受 ``valkey`` / ``disabled``；``pg`` 已随 ADR-0013 C 退役，
出现即 fail-fast。开发/测试与生产使用同一 Valkey 实现，没有第二后端可回退。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from agent_core.config import env_bool, env_float, env_int, env_str


class CacheConfigError(RuntimeError):
    """缓存配置非法：启动期必须失败，不允许静默降级成另一后端。"""


_VALID_BACKENDS = frozenset({"valkey", "disabled"})
_VALID_SCHEMES = frozenset({"redis", "rediss", "unix", "valkey"})
# 余弦距离的取值上界：distance = 1 - cos_similarity ∈ [0, 2]（反向量为 2）。
# 口径来源是 L2 索引本身使用的 DISTANCE_METRIC=COSINE（`valkey_backend.py` 建索引处），
# 不是相似度阈值——阈值一旦 ≥ 这个上界，"距离小于阈值"对所有向量恒真。
_MAX_COSINE_DISTANCE = 2.0


def _env_timeout_ms(name: str, default_ms: int) -> int:
    value = env_int(name, default_ms)
    if value <= 0:
        raise CacheConfigError(f"{name} 必须为正整数（毫秒），当前 {value}")
    return value


def redact_url(url: str) -> str:
    """隐藏 URL 中的口令，供日志/健康态/异常文本使用。"""
    if not url:
        return ""
    return re.sub(r"(?<=://)([^/@:]*):([^@]*)@", r"\1:***@", url)


def safe_token(value: str) -> str:
    """把 scope/model 变成可读且无碰撞的命名空间 token。"""
    raw = value or "default"
    slug = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")[:40] or "default"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
    return f"{slug}_{digest}"


@dataclass(frozen=True)
class CacheConfig:
    # L2 索引 schema 的版本 token（不带注解 ⇒ 类常量，不是 dataclass 字段，不可由环境变量覆盖）。
    # 索引是 Valkey 侧的持久状态，而建索引前只判"同名索引在不在"（ft.info 成功即复用），
    # 不比对字段：改了字段没改名，旧实例上的 stale schema 会被无声沿用——
    # v1 缺 CASESENSITIVE，租户隔离看着像生效其实没生效。**改 schema 必须同时改这里。**
    # 只动索引名不动数据键前缀：新索引按同一 PREFIX 自动重建，不丢数据、不需要删旧索引。
    # 这条"存量哈希会被首次扫描收进新索引"的前提已在真机取到读数（bundle 9.1.2 / search 1.2.1：
    # 先 HSET 后建索引，num_docs 0→1、state backfill_in_progress→ready 用时 0.5s，KNN 可检索到它），
    # 不再是推断。
    index_schema_version = 2

    enabled: bool = field(default_factory=lambda: env_bool("CACHE_ENABLED", True))
    backend: str = field(default_factory=lambda: env_str("CACHE_BACKEND", "valkey").strip().lower())
    valkey_url: str = field(default_factory=lambda: env_str("VALKEY_URL", "redis://localhost:6379/0").strip())

    l1_ttl_seconds: int = field(default_factory=lambda: env_int("CACHE_L1_TTL", 3600))
    l2_ttl_seconds: int = field(default_factory=lambda: env_int("CACHE_L2_TTL", 1800))
    null_ttl_seconds: int = field(default_factory=lambda: env_int("CACHE_NULL_TTL", 60))
    negative_cache_enabled: bool = field(default_factory=lambda: env_bool("CACHE_NULL_ENABLED", True))

    # 余弦距离语义（越小越严）：两段历史取值 0.05 / 0.92 相似度等价于 0.08 距离。
    threshold: float = field(default_factory=lambda: env_float("CACHE_THRESHOLD", 0.05))
    federation_threshold: float = field(default_factory=lambda: env_float("CACHE_THRESHOLD_FEDERATION", 0.08))

    vector_dim: int = field(default_factory=lambda: env_int("CACHE_VECTOR_DIM", 0))
    embedding_model: str = field(default_factory=lambda: env_str("CACHE_EMBEDDING_MODEL", "").strip())

    connect_timeout_ms: int = field(default_factory=lambda: _env_timeout_ms("CACHE_CONNECT_TIMEOUT_MS", 50))
    command_timeout_ms: int = field(default_factory=lambda: _env_timeout_ms("CACHE_COMMAND_TIMEOUT_MS", 100))
    write_queue_max: int = field(default_factory=lambda: env_int("CACHE_WRITE_QUEUE_MAX", 1000))
    write_flush_timeout_seconds: float = field(default_factory=lambda: env_float("CACHE_WRITE_FLUSH_TIMEOUT", 5.0))
    breaker_failure_threshold: int = field(default_factory=lambda: env_int("CACHE_BREAKER_FAILURES", 3))
    breaker_recovery_seconds: float = field(default_factory=lambda: env_float("CACHE_BREAKER_RECOVERY_SECONDS", 15.0))

    key_prefix: str = field(default_factory=lambda: env_str("CACHE_KEY_PREFIX", "cache:sc:v1").strip())

    def __post_init__(self) -> None:
        if self.backend not in _VALID_BACKENDS:
            if self.backend == "pg":
                raise CacheConfigError(
                    "CACHE_BACKEND=pg 已退役（ADR-0013 C）：语义缓存只支持 valkey，"
                    "生产与开发/测试均使用 Valkey；请改为 CACHE_BACKEND=valkey 或 disabled"
                )
            raise CacheConfigError(f"CACHE_BACKEND={self.backend!r} 非法，只接受 valkey / disabled")
        if self.backend == "valkey":
            url = self.valkey_url
            if not url:
                raise CacheConfigError("CACHE_BACKEND=valkey 但 VALKEY_URL 为空")
            scheme = urlsplit(url).scheme.lower()
            if scheme not in _VALID_SCHEMES:
                raise CacheConfigError(f"VALKEY_URL 协议 {scheme!r} 不受支持，只接受 redis/rediss/unix/valkey")
            if scheme == "valkey":
                object.__setattr__(self, "valkey_url", "redis" + url[len("valkey") :])
        if self.l1_ttl_seconds <= 0 or self.l2_ttl_seconds <= 0 or self.null_ttl_seconds <= 0:
            raise CacheConfigError("缓存 TTL 必须为正整数")
        if self.threshold < 0 or self.federation_threshold < 0:
            raise CacheConfigError("缓存距离阈值不能为负")
        # 上界不是"更宽松"的旋钮：COSINE 距离取值 0..2，阈值 ≥2 时**任何**向量都算命中
        # ⇒ L2 会把不相干的旧答案当命中返回（正确性问题，不是命中率问题）。
        # 与 CACHE_BACKEND=pg 同一口径：配错了要在启动期失败，不要静默换成另一种语义。
        if not self.threshold < _MAX_COSINE_DISTANCE:
            raise CacheConfigError(
                f"CACHE_THRESHOLD={self.threshold} 超出余弦距离上界 {_MAX_COSINE_DISTANCE}"
                "（0..2）；≥2 等于任何向量都判命中，L2 会返回不相干答案"
            )
        if not self.federation_threshold < _MAX_COSINE_DISTANCE:
            raise CacheConfigError(
                f"CACHE_THRESHOLD_FEDERATION={self.federation_threshold} 超出余弦距离上界 "
                f"{_MAX_COSINE_DISTANCE}（0..2）；≥2 等于任何向量都判命中"
            )
        if self.vector_dim < 0:
            raise CacheConfigError("CACHE_VECTOR_DIM 不能为负")
        if self.write_queue_max <= 0:
            raise CacheConfigError("CACHE_WRITE_QUEUE_MAX 必须为正整数")
        # 排空超时写 0/负数会让每次优雅关闭都"超时但不排空"：队列里的写入被丢弃，
        # 而日志只留一句 warning ⇒ 表现为"缓存莫名冷"，读数上看不出是配置所致。
        if self.write_flush_timeout_seconds <= 0:
            raise CacheConfigError("CACHE_WRITE_FLUSH_TIMEOUT 必须为正数（秒）")
        # 熔断阈值 0 = 一开始就永久 open（整条缓存静默失效）；恢复时间 0/负 = 熔断后
        # 不再生恢复或永不恢复。两者都是"装了但没接上"的形状，必须 fail-fast。
        if self.breaker_failure_threshold < 1:
            raise CacheConfigError("CACHE_BREAKER_FAILURES 必须 ≥1（0 会让熔断器一启动就永久打开）")
        if self.breaker_recovery_seconds <= 0:
            raise CacheConfigError("CACHE_BREAKER_RECOVERY_SECONDS 必须为正数（秒）")
        if not self.key_prefix:
            raise CacheConfigError("CACHE_KEY_PREFIX 不能为空")

    def threshold_for(self, scope: str) -> float:
        """按 scope 返回余弦距离阈值（federation 保留 0.92 相似度的等价距离）。"""
        return self.federation_threshold if scope == "federation" else self.threshold

    def namespace(self, scope: str, model: str, dim: int) -> str:
        return f"{self.key_prefix}:{safe_token(scope)}:{safe_token(model)}:{int(dim)}:"

    def index_name(self, scope: str, model: str, dim: int) -> str:
        # key_prefix 必须进索引名。索引定义里的 PREFIX 才是引擎侧真正的键空间绑定，而
        # 建索引前只判"同名索引在不在"（ft.info 成功即复用）⇒ 名字不含前缀时，两个共用
        # 一台 Valkey、scope/model/dim 相同而 CACHE_KEY_PREFIX 不同的实例会撞在同一个索引上：
        # 后启动的那个复用前者的索引，自己的写入永远进不了索引，检索却跑在前者的数据上。
        # 真机读数（2026-10-26 契约首跑 + 探针）：num_docs=0 / hash_indexing_failures=0 /
        # state=ready —— 完全静默，四条 L2 用例因此全红。
        return (
            f"semantic_cache_idx_{safe_token(scope)}_{safe_token(model)}_{int(dim)}"
            f"_k{safe_token(self.key_prefix)}_s{self.index_schema_version}"
        )

    @property
    def redacted_url(self) -> str:
        return redact_url(self.valkey_url)


_config: CacheConfig | None = None


def get_cache_config() -> CacheConfig:
    global _config
    if _config is None:
        _config = CacheConfig()
    return _config


def reset_cache_config() -> None:
    """测试/配置热更新用：下次读取重新解析环境变量。"""
    global _config
    _config = None


__all__ = [
    "CacheConfig",
    "CacheConfigError",
    "get_cache_config",
    "redact_url",
    "reset_cache_config",
    "safe_token",
]
