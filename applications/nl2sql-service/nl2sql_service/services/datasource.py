"""数据源注册表与方言探测（P1-3 源分片 / P1-4 方言分支 / P1-6 datasource 维度）。

三条方案在代码层的共用地基：

- **P1-6**：元数据与召回都按 `datasource_id` 分片——请求带源选择，检索阶段
  就带源过滤，不等 EXPLAIN 报"表不存在"才发现串源。
- **P1-4**：同一问法在两个源（PostgreSQL / MySQL）都要能命中；生成期就知道
   dialect，`WITH PARSER ngram`（MySQL）/ `MATCH_ANY`（Doris）这类源专有语法
  在 prompt 层与 guard 层就按方言分支，不指望运行时报错兜底。
- **P1-3②**：返回体带口径标签（`datasource_label`，如"数仓 T+1、已清洗" /
  "业务库、实时未清洗"）——答案里能看出数字来自哪个源、什么口径。

**不静默路由**（D5）：源由用户在会话里显式选定；未传时用配置的默认源，
未知 `datasource_id` **fail-fast**（对齐 agent_server `schema_store` 的纪律：
宁可报错也不猜一个源继续跑）。
"""

from __future__ import annotations

from dataclasses import dataclass

#: sqlglot / guard / literal_extractor 共用的方言常量
DIALECT_POSTGRES = "postgres"
DIALECT_MYSQL = "mysql"

#: DSN scheme → 方言。只认这两族；空/未知按 postgres（服务历史默认）。
_SCHEME_TO_DIALECT = {
    "postgres": DIALECT_POSTGRES,
    "postgresql": DIALECT_POSTGRES,
    "mysql": DIALECT_MYSQL,
    "mariadb": DIALECT_MYSQL,
}


def detect_dialect(dsn: str) -> str:
    """从 DSN scheme 推断方言；空或无法识别按 postgres。

    仅按 scheme 判定，不连库探测——方言是**连接参数的一部分**，scheme 已经
    唯一确定了它，连库只会把启动耦合到一次网络往返上。
    """
    if not dsn or "://" not in dsn:
        return DIALECT_POSTGRES
    scheme = dsn.split("://", 1)[0].strip().lower()
    return _SCHEME_TO_DIALECT.get(scheme, DIALECT_POSTGRES)


@dataclass(frozen=True)
class DataSource:
    """一个数据源的静态描述。

    - `id`：作用域键（检索过滤 / 会话隔离 / 统计都用它）；
    - `dialect`：生成期与 guard 的方言依据（P1-4）；
    - `label`：口径标签，随响应体返回（P1-3②）。
    """

    id: str
    dialect: str
    label: str = ""


class DataSourceRegistry:
    """请求 `datasource_id` → `DataSource` 的解析器。

    默认源显式注册；未知 id 抛 `KeyError`，由调用方转成对外的 fail-fast 错误
    （不回落默认源——静默串源比报错更糟，M4/P1-3）。
    """

    def __init__(self, sources: dict[str, DataSource], default_id: str) -> None:
        if default_id not in sources:
            raise ValueError(f"默认数据源 {default_id!r} 未在注册表中")
        self._sources = dict(sources)
        self._default_id = default_id

    @property
    def default_id(self) -> str:
        return self._default_id

    def resolve(self, datasource_id: str | None) -> DataSource:
        """空/None → 默认源；未知 id → KeyError（fail-fast）。"""
        key = (datasource_id or "").strip() or self._default_id
        return self._sources[key]

    def ids(self) -> list[str]:
        return sorted(self._sources)


def build_default_registry(
    datasource_id: str,
    dialect: str,
    label: str = "",
) -> DataSourceRegistry:
    """按单 dw 池的部署形态建注册表（仅一个源）。

    多源（MySQL + Doris 并存）时由 lifespan 用多 `DataSource` 覆盖——
    这个工厂函数只覆盖当前"一个业务数仓 DSN"的现实部署。
    """
    source = DataSource(id=datasource_id, dialect=dialect, label=label)
    return DataSourceRegistry({datasource_id: source}, default_id=datasource_id)


__all__ = [
    "DIALECT_MYSQL",
    "DIALECT_POSTGRES",
    "DataSource",
    "DataSourceRegistry",
    "build_default_registry",
    "detect_dialect",
]
