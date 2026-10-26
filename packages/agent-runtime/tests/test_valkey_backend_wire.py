"""Valkey 适配器的命令构造单测（无需真实服务）。

为什么单独存在：契约测试在本机无 Docker/Valkey 时整段 skip，而 valkey-py 的
Search API 与 redis-py 并不完全同形（``VectorField`` 要 dict 属性、
``Query`` 没有 ``add_param``）。这类差异只会在运行期炸，且会绕过 fail-open
直接冒到请求层，因此用假客户端把「发出去的 schema / 查询 / 写命令」钉死。

假客户端只在本文件内使用，不实现 ``SemanticCacheBackend``，不进工厂。另有
``_ArgvCapture`` 借 valkey-py 自己的 ``_mk_query_args`` 生成**真 argv**：客户端如何
序列化属于第三方形状，抄进测试就等于把前提写成结论。
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
from types import SimpleNamespace
from typing import Any

import pytest
from valkey.commands.search.commands import SearchCommands
from valkey.exceptions import ResponseError, ValkeyError

from agent_runtime.cache import valkey_backend
from agent_runtime.cache.config import CacheConfig, CacheConfigError, safe_token
from agent_runtime.cache.disabled_backend import DisabledSemanticCache
from agent_runtime.cache.valkey_backend import (
    _TAG_SEPARATOR,
    ValkeySemanticCache,
    _vec_bytes,
)

_DIM = 4


class _MockEmbedder:
    dim = _DIM


class _FakePipeline:
    def __init__(self) -> None:
        self.ops: list[tuple] = []

    def set(self, *args: Any, **kwargs: Any) -> None:
        self.ops.append(("set", args, kwargs))

    def delete(self, *args: Any) -> None:
        self.ops.append(("delete", args, {}))

    def hset(self, *args: Any, **kwargs: Any) -> None:
        self.ops.append(("hset", args, kwargs))

    def expire(self, *args: Any) -> None:
        self.ops.append(("expire", args, {}))

    def incr(self, *args: Any) -> None:
        self.ops.append(("incr", args, {}))

    def persist(self, *args: Any) -> None:
        self.ops.append(("persist", args, {}))

    async def execute(self) -> list:
        return []


class _FakeSearch:
    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self.created: list[tuple] = []
        self.searches: list[dict[str, Any]] = []
        self._result = result
        self._error = error

    async def info(self) -> dict:
        raise ResponseError("Unknown Index name")

    async def create_index(self, fields, definition=None):
        self.created.append((fields, definition))
        return True

    async def search(self, query, query_params=None):
        self.searches.append({"query": query, "query_params": query_params})
        if self._error is not None:
            raise self._error
        return self._result


class _FakeClient:
    def __init__(
        self, result: Any = None, error: Exception | None = None, ft_obj: Any = None
    ) -> None:
        self.search = ft_obj if ft_obj is not None else _FakeSearch(result, error)
        self.pipeline_obj = _FakePipeline()
        # transaction 标志是"哪些写必须原子"的唯一读数（epoch 的 INCR+PERSIST 要原子，
        # L2 的 HSET+EXPIRE 刻意不原子），以前没记 ⇒ 这一位变异后没人看。
        self.pipeline_flags: list[bool] = []

    def ft(self, _name: str) -> _FakeSearch:
        return self.search

    def pipeline(self, transaction: bool = False) -> _FakePipeline:
        self.pipeline_flags.append(transaction)
        return self.pipeline_obj

    async def get(self, _key: str) -> None:
        """epoch 键缺失 → 后端按 epoch 0 处理（写侧路径需要这一步）。"""
        return None


def _backend(
    result: Any = None, error: Exception | None = None, ft_obj: Any = None
) -> tuple[ValkeySemanticCache, _FakeClient]:
    cfg = CacheConfig(
        backend="valkey",
        valkey_url="redis://localhost:6379/0",
        l1_ttl_seconds=100,
        l2_ttl_seconds=50,
        null_ttl_seconds=10,
        threshold=0.05,
        federation_threshold=0.08,
        vector_dim=_DIM,
        embedding_model="mock",
    )
    cache = ValkeySemanticCache(cfg, "agent_server", embedder=_MockEmbedder())
    fake = _FakeClient(result=result, error=error, ft_obj=ft_obj)
    cache._client = fake
    return cache, fake


def test_vector_field_matches_valkeypy_signature():
    """valkey-py 6.2 的 VectorField 是 (name, algorithm, attributes: dict)。"""
    cache, fake = _backend()
    import asyncio

    assert asyncio.run(cache._ensure_index()) is True
    fields, definition = fake.search.created[0]
    vector = [f for f in fields if f.name == "query_vec"][0]
    assert vector.args == [
        "VECTOR",
        "HNSW",
        6,
        "TYPE",
        "FLOAT32",
        "DIM",
        _DIM,
        "DISTANCE_METRIC",
        "COSINE",
    ]
    assert definition.args == [
        "ON",
        "HASH",
        "PREFIX",
        1,
        f"{cache._ns}l2:",
        "SCORE",
        1.0,
    ]


def test_isolation_tag_fields_are_case_sensitive():
    """TAG 默认大小写不敏感：tenant 大小写变体不能合并成同一过滤值。"""
    cache, fake = _backend()
    import asyncio

    assert asyncio.run(cache._ensure_index()) is True
    fields, _ = fake.search.created[0]
    tags = {f.name: f for f in fields if f.name in {"tenant", "scope", "kb_version", "gray_pct", "epoch"}}
    assert set(tags) == {"tenant", "scope", "kb_version", "gray_pct", "epoch"}
    for name, field in tags.items():
        assert "CASESENSITIVE" in field.args, name


def test_search_passes_vector_bytes_as_query_params():
    """Query 链上没有 add_param；向量必须以 search(query_params=...) 传入。"""
    cache, fake = _backend(
        result=SimpleNamespace(docs=[SimpleNamespace(value_json='{"answer": "a"}', distance="0.01")])
    )
    cache._index_ready = True
    import asyncio

    hit = asyncio.run(
        cache._search_l2(
            tenant_id="tenant-a",
            vector=[0.1] * _DIM,
            epoch=0,
            kb_versions={"kb": "v1"},
            gray_pct=0.0,
        )
    )
    assert hit is not None and hit.layer == "l2" and hit.value == {"answer": "a"}
    call = fake.search.searches[0]
    assert "$vec" in call["query"].query_string()
    assert call["query_params"] == {"vec": _vec_bytes([0.1] * _DIM)}


def test_l2_filter_contains_every_isolation_dimension():
    cache, fake = _backend(result=SimpleNamespace(docs=[]))
    cache._index_ready = True
    import asyncio

    asyncio.run(
        cache._search_l2(
            tenant_id="tenant-a",
            vector=[0.0] * _DIM,
            epoch=3,
            kb_versions={"kb": "v2"},
            gray_pct=12.5,
        )
    )
    text = fake.search.searches[0]["query"].query_string()
    # TAG 值里的 ``-`` 与 ``.`` 必须转义，否则 RediSearch 会把它们当语法
    for token in (
        r"@tenant:{tenant\-a}",
        "@scope:{agent_server}",
        r"@gray_pct:{12\.5}",
        "@epoch:{3}",
    ):
        assert token in text
    assert "@kb_version:{" in text


def test_l2_escapes_pipe_so_tenant_fields_cannot_become_or_clause():
    """RediSearch TAG 查询里 ``|`` 是 OR 分隔符；租户名带 ``|`` 时必须转义。

    漏转义时 ``@tenant:{victim|attacker}`` 会扩散为两个 tag 的并集，
    L2 检索就可能读到别的租户写入的答案（跨租户读）。
    """
    cache, fake = _backend(result=SimpleNamespace(docs=[]))
    cache._index_ready = True
    import asyncio

    asyncio.run(
        cache._search_l2(
            tenant_id="victim|attacker",
            vector=[0.0] * _DIM,
            epoch=0,
            kb_versions=None,
            gray_pct=0.0,
        )
    )
    text = fake.search.searches[0]["query"].query_string()
    assert r"@tenant:{victim\|attacker}" in text
    assert "@tenant:{victim|attacker}" not in text


def test_namespace_bump_never_expires_epoch_key():
    """epoch key 一旦过期，epoch 归零会让旧 key 复活、命名空间失效被撤销。"""
    cache, fake = _backend()
    cache._started = True
    import asyncio

    asyncio.run(cache.invalidate_namespace(tenant_id="tenant-a"))

    ops = fake.pipeline_obj.ops
    assert [op[0] for op in ops] == ["incr", "persist"]
    assert ops[0][1] == (f"{cache._ns}epoch:{cache._tenant_token('tenant-a')}",)


def test_l2_rejects_result_beyond_distance_threshold():
    cache, _ = _backend(result=SimpleNamespace(docs=[SimpleNamespace(value_json='{"answer": "a"}', distance="0.5")]))
    cache._index_ready = True
    import asyncio

    assert (
        asyncio.run(
            cache._search_l2(
                tenant_id="tenant-a",
                vector=[0.1] * _DIM,
                epoch=0,
                kb_versions=None,
                gray_pct=0.0,
            )
        )
        is None
    )


def test_positive_write_carries_tags_and_both_ttls():
    cache, fake = _backend()
    cache._index_ready = True
    import asyncio

    asyncio.run(
        cache._write_positive(
            keys={"l1": "L1", "l2": "L2", "null": "N"},
            value_json='{"answer": "a"}',
            vector=[0.1] * _DIM,
            tenant_id="tenant-a",
            intent="sql",
            rewritten_query="q",
            kb_sig="sig",
            gray_tag="0",
            epoch=0,
            ttl=100,
            l2_ttl=50,
        )
    )
    ops = fake.pipeline_obj.ops
    kinds = [op[0] for op in ops]
    assert kinds == ["set", "delete", "hset", "expire"]
    assert ops[0][2] == {"ex": 100}
    assert ops[3][1] == ("L2", 50)
    mapping = ops[2][2]["mapping"]
    assert mapping["tenant"] == "tenant-a"
    assert mapping["scope"] == "agent_server"
    assert mapping["kb_version"] == "sig"
    assert mapping["gray_pct"] == "0"
    assert mapping["epoch"] == "0"
    assert mapping["value_json"] == '{"answer": "a"}'


def test_set_skips_write_when_value_or_query_has_pii():
    """缓存是持久副本、命中路径不再跑输出护栏 ⇒ 检出 PII 的写入在单一实现里拦下。"""
    cache, fake = _backend()
    cache._started = True
    import asyncio

    for kwargs in (
        {"rewritten_query": "查销售额", "value": {"answer": "结果：13800138000"}},
        {"rewritten_query": "查 13800138000 的销售额", "value": {"answer": "42"}},
    ):
        asyncio.run(
            cache.set(
                tenant_id="tenant-a",
                intent="sql",
                embedding=[0.1] * _DIM,
                **kwargs,
            )
        )
    assert cache.get_stats()["skipped_pii"] == 2
    assert fake.pipeline_obj.ops == []

    async def _clean_write() -> None:
        await cache.set(
            tenant_id="tenant-a",
            intent="sql",
            rewritten_query="查销售额",
            value={"answer": "42"},
            embedding=[0.1] * _DIM,
        )
        await cache.flush()

    asyncio.run(_clean_write())
    # 门禁不是"永不写"：干净问答照常落 L1 + L2
    assert [op[0] for op in fake.pipeline_obj.ops] == ["set", "delete", "hset", "expire"]
    assert cache.get_stats()["skipped_pii"] == 2


def test_l2_accepts_distance_equal_to_threshold_and_rejects_above():
    """阈值边界语义：本实现取 ``distance <= threshold`` 算命中。

    被删的 PG 用例取的是严格小于；换后端时这类"边界挪一档"最容易静默发生，
    故必须有用例钉住等号这一侧的归属。
    """
    import asyncio

    for distance, should_hit in (("0.05", True), ("0.051", False)):
        cache, _ = _backend(
            result=SimpleNamespace(docs=[SimpleNamespace(value_json='{"answer": "a"}', distance=distance)])
        )
        cache._index_ready = True
        hit = asyncio.run(
            cache._search_l2(
                tenant_id="tenant-a",
                vector=[0.1] * _DIM,
                epoch=0,
                kb_versions=None,
                gray_pct=0.0,
            )
        )
        assert (hit is not None) is should_hit, distance


def test_l2_treats_no_docs_or_missing_distance_as_miss():
    """Search 无结果、没回 distance、或回了非数值时都按未命中处理，不得抛到请求层。"""
    import asyncio

    for result, doc in (
        (SimpleNamespace(docs=[]), None),
        (SimpleNamespace(docs=[SimpleNamespace(value_json='{"answer": "a"}')]), "no-distance"),
        (SimpleNamespace(docs=[SimpleNamespace(value_json='{"answer": "a"}', distance="n/a")]), "bad-distance"),
        (SimpleNamespace(docs=[SimpleNamespace(value_json="not-json", distance="0.01")]), "bad-json"),
    ):
        cache, _ = _backend(result=result)
        cache._index_ready = True
        hit = asyncio.run(
            cache._search_l2(
                tenant_id="tenant-a",
                vector=[0.1] * _DIM,
                epoch=0,
                kb_versions=None,
                gray_pct=0.0,
            )
        )
        assert hit is None, doc


def test_set_with_open_breaker_does_not_enqueue():
    """熔断打开时写侧不入队：否则停机期间队列被填满，真实写入全被丢弃。"""
    cache, fake = _backend()
    cache._started = True
    import asyncio

    for _ in range(cache._cfg.breaker_failure_threshold):
        cache._breaker.record_failure()

    asyncio.run(
        cache.set(
            tenant_id="tenant-a",
            intent="sql",
            rewritten_query="查销售额",
            value={"answer": "42"},
            embedding=[0.1] * _DIM,
        )
    )
    assert cache._queue is None
    assert fake.pipeline_obj.ops == []


def test_worker_records_write_failure_and_keeps_processing():
    """单条写失败只计数，不得杀死写队列 worker（写失败静默 = 原 PG 判据）。"""
    cache, _ = _backend()
    cache._started = True
    import asyncio

    done: list[str] = []

    async def _boom() -> None:
        raise ValkeyError("write boom")

    async def _ok() -> None:
        done.append("ok")

    async def _drive() -> None:
        cache._enqueue(_boom)
        cache._enqueue(_ok)
        await cache.flush()

    asyncio.run(_drive())
    assert done == ["ok"]
    assert cache.get_stats()["error"] == 1


def test_full_write_queue_drops_and_counts():
    """队列满：丢弃 + 计数、不阻塞调用方（bench 的「写丢弃 = 0」预算靠这个计数）。"""
    import asyncio

    cfg = CacheConfig(
        backend="valkey",
        valkey_url="redis://localhost:6379/0",
        vector_dim=_DIM,
        embedding_model="mock",
        write_queue_max=1,
    )
    cache = ValkeySemanticCache(cfg, "agent_server", embedder=_MockEmbedder())
    cache._client = _FakeClient()
    cache._started = True

    async def _job() -> None:
        return None

    async def _drive() -> None:
        cache._enqueue(_job)
        cache._enqueue(_job)  # 队列已满 ⇒ 丢弃并计数

    asyncio.run(_drive())
    assert cache.get_stats()["dropped_writes"] == 1


def test_reset_stats_clears_hit_and_runtime_counters():
    cache, _ = _backend()
    cache._runtime_counts["skipped_pii"] = 2
    cache._runtime_counts["skipped_no_tenant"] = 1
    cache._stats.record("miss")

    cache.reset_stats()

    stats = cache.get_stats()
    assert stats.get("total", 0) == 0
    assert stats["skipped_pii"] == 0
    assert stats["skipped_no_tenant"] == 0


@pytest.mark.parametrize("tenant", ["", "\x1f"])
def test_empty_or_separator_tenant_is_fail_closed(tenant):
    cache, fake = _backend()
    cache._index_ready = True
    import asyncio

    assert (
        asyncio.run(
            cache._search_l2(
                tenant_id=tenant,
                vector=[0.1] * _DIM,
                epoch=0,
                kb_versions=None,
                gray_pct=0.0,
            )
        )
        is None
    )
    assert fake.search.searches == []


# 实跑取得（不是手抄）：任何 L2 字段/参数变动都会翻红，逼作者同步 index_schema_version。
_L2_SCHEMA_SNAPSHOT = (
    ("epoch", ("TAG", "SEPARATOR", "\x1f", "CASESENSITIVE")),
    ("gray_pct", ("TAG", "SEPARATOR", "\x1f", "CASESENSITIVE")),
    ("intent", ("TEXT", "WEIGHT", "1.0", "NOSTEM")),
    ("kb_version", ("TAG", "SEPARATOR", "\x1f", "CASESENSITIVE")),
    ("query_text", ("TEXT", "WEIGHT", "1.0", "NOSTEM")),
    (
        "query_vec",
        ("VECTOR", "HNSW", "6", "TYPE", "FLOAT32", "DIM", "4", "DISTANCE_METRIC", "COSINE"),
    ),
    ("scope", ("TAG", "SEPARATOR", "\x1f", "CASESENSITIVE")),
    ("tenant", ("TAG", "SEPARATOR", "\x1f", "CASESENSITIVE")),
    ("value_json", ("TEXT", "WEIGHT", "1.0", "NOSTEM")),
)


def test_l2_schema_change_must_move_index_name():
    """索引按名字复用（ft.info 成功即 ready），不比对字段：改了字段没改名 ⇒
    旧实例上的 stale schema 被无声沿用（v1 缺 CASESENSITIVE 就是这么漏的）。
    这条把 schema 快照与版本 token 绑死。"""
    cache, fake = _backend()
    import asyncio

    assert asyncio.run(cache._ensure_index()) is True
    fields, _ = fake.search.created[0]
    signature = tuple(sorted((f.name, tuple(str(a) for a in f.args)) for f in fields))
    assert signature == _L2_SCHEMA_SNAPSHOT, "L2 schema 变了：同步 CacheConfig.index_schema_version"
    assert cache._index.endswith(f"_s{CacheConfig.index_schema_version}")


# 措辞全部从上游树**全量 grep**（不是文档转述），且两代形状都要在场：
# 真机 pin = valkey-bundle 9.1.2（search 模块 MODULE LIST 解出 1.2.1）实测报的是
#   "Index with name 'X' not found in database 0"（带 database 后缀，即 main 那一支）
# 而 1.0.2（bundle 9.0.1）源码里是
#   schema_manager.cc:121 "Index with name 'X' not found"（**无** database 后缀）
#   schema_manager.cc:133/:137 "Index schema not found: X"
# 另两条来自 main（e335d9e）：fanout_operation_base.h:224（集群 fanout）、RediSearch 遗留措辞。
# 两套都留着：升 pin 后形状会漂移，只测一边就是单边证据。
# 索引名不手抄：取 `_backend()` 真算出来的名字（名字里含 key_prefix/scope/model/dim 的 token，
# 手抄的那份会在下一次改命名规则时静默变成"测一个线上不存在的名字"）。
_INDEX_NAME = _backend()[0]._index


@pytest.mark.parametrize(
    "message",
    [
        f"Index with name '{_INDEX_NAME}' not found in database 0",
        "Index name not found.",
        "no such index with that name",
        f"Index with name '{_INDEX_NAME}' not found",
        f"Index schema not found: {_INDEX_NAME}",
    ],
)
def test_missing_l2_index_clears_ready_flag_for_rebuild(message):
    """索引被 FT.DROPINDEX / FLUSHALL 摘掉后，_index_ready 不清就是永久静默 miss：
    每次检索报错都被 fail-open 吞掉，健康态还报 ready=true，要等进程重启才恢复。"""
    cache, fake = _backend(error=ResponseError(message))
    cache._index_ready = True
    import asyncio

    hit = asyncio.run(
        cache._search_l2(
            tenant_id="t1",
            vector=[0.1] * _DIM,
            epoch=0,
            kb_versions=None,
            gray_pct=0.0,
        )
    )
    assert hit is None
    assert cache._index_ready is False
    assert cache.get_stats()["index_missing"] == 1


# 反方向：其它带 "not found" 的报错也必须**不**触发重建。这些字符串逐条
# 来自 1.0.2 源码（vector_base.cc / tag.cc / schema_manager.cc / ft_search_parser.cc:82）。
# 谓词靠 "index" in low 做区分，这条用例就是这个区分度的唯一守卫——删掉它，
# 把谓词放宽成 `any(marker in low for marker in ("no such index", "not found"))` 仍然全绿。
@pytest.mark.parametrize(
    "message",
    [
        "Embedding id not found: 42",
        "Record was not found",
        "Entry not found: doc:1",
        "Subscription not found",
        "Parameter vec not found.",
    ],
)
def test_non_index_not_found_error_keeps_index_ready(message):
    cache, fake = _backend(error=ResponseError(message))
    cache._index_ready = True
    import asyncio

    hit = asyncio.run(
        cache._search_l2(
            tenant_id="t1",
            vector=[0.1] * _DIM,
            epoch=0,
            kb_versions=None,
            gray_pct=0.0,
        )
    )
    assert hit is None
    assert cache._index_ready is True
    assert cache.get_stats()["index_missing"] == 0


def test_unrelated_valkey_error_keeps_index_ready():
    """只有"索引缺失"才触发重建；连接类故障不该顺手改名重建。"""
    cache, fake = _backend(error=ValkeyError("connection reset by peer"))
    cache._index_ready = True
    import asyncio

    hit = asyncio.run(
        cache._search_l2(
            tenant_id="t1",
            vector=[0.1] * _DIM,
            epoch=0,
            kb_versions=None,
            gray_pct=0.0,
        )
    )
    assert hit is None
    assert cache._index_ready is True
    assert cache.get_stats()["index_missing"] == 0


# 这一组补的是**谓词的区分度**，不是引擎措辞：上面那两组负例（"Record was not found" 等）
# 全部不含 "index"，于是它们只守得住 `"index" in low` 那一侧；`any(marker in low ...)`
# 被改成 `marker not in low` 时，两条负例仍然全绿（因为外层 `"index" in low` 先把它们挡掉），
# 而真实后果是"任何带 index 字样的报错都被当成索引被摘 ⇒ 无谓重建索引"。
# ⇒ 要杀这一刀必须有**含 index 但不是索引缺失**的负例。下面两条是形状样例（不是本仓实取的
# 引擎原文，实取的都收在 `_is_missing_index_error` 的 docstring 里），本条要断言的是
# "含 index ≠ 就该重建"这个区分度本身，换任何引擎措辞这条判据都成立。
@pytest.mark.parametrize(
    "message",
    [
        "BUSYINDEX: Index creation is already in progress",
        "Unknown Index name",
        "Index schema is invalid for this command",
    ],
)
def test_index_worded_but_not_missing_error_keeps_index_ready(message):
    cache, _ = _backend(error=ResponseError(message))
    cache._index_ready = True
    import asyncio

    hit = asyncio.run(
        cache._search_l2(
            tenant_id="t1",
            vector=[0.1] * _DIM,
            epoch=0,
            kb_versions=None,
            gray_pct=0.0,
        )
    )
    assert hit is None, "检索报错当然不命中"
    assert cache._index_ready is True, f"含 index 字样不等于索引缺失，不许顺手重建：{message}"
    assert cache.get_stats()["index_missing"] == 0


class _ArgvCapture(SearchCommands):
    """用 valkey-py 自己的组装器生成真 argv，而不是抄它的输出形状——本文件已有两条
    历史坑（VectorField 位置参数、Query.add_param）都出在"我以为客户端是这样"。"""

    def __init__(self) -> None:
        self.index_name = "capture"
        self.argv: list[Any] | None = None

    async def search(self, query, query_params=None):
        """真实 async 客户端上 search 是协程，替身必须同形（否则 await 到的是值）。"""
        args, _parsed = self._mk_query_args(query, query_params=query_params)
        self.argv = list(args)
        return SimpleNamespace(docs=[])


def _search_argv(**kwargs: Any) -> list[Any]:
    cache, fake = _backend(ft_obj=_ArgvCapture())
    cache._index_ready = True
    import asyncio

    asyncio.run(
        cache._search_l2(
            tenant_id=kwargs.get("tenant_id", "t1"),
            vector=[0.1] * _DIM,
            epoch=kwargs.get("epoch", 3),
            kb_versions=kwargs.get("kb_versions"),
            gray_pct=kwargs.get("gray_pct", 25.0),
        )
    )
    return fake.search.argv


def test_l2_argv_carries_params_dialect_and_isolation_tags():
    argv = _search_argv(kb_versions={"ks": "7"})
    text = " ".join(str(a) for a in argv)
    assert argv[0] == "capture"
    assert "AS distance" in text
    assert "DIALECT" in argv and 2 in argv
    assert "@tenant:{t1}" in text and "@kb_version:" in text and "@epoch:{3}" in text
    # 向量必须走 PARAMS，不进查询串（裸浮点串会让 KNN 变成文本匹配）
    assert "vec" in argv
    assert argv[argv.index("vec") + 1] == _vec_bytes([0.1] * _DIM)


def test_l2_argv_returns_only_the_two_text_fields():
    """L2 必须只 RETURN 读路径真正用的两个**文本**字段，且不许把向量字段带回来。

    客户端建在 `decode_responses=True` 上，而 `query_vec` 是原始 float32 字节 ⇒ 一旦回传
    就是 `UnicodeDecodeError: 0x80 in position 2`，被 fail-open 吞成永久 miss
    （2026-10-26 契约首跑四条红的确切原因，真机读数）。
    此前这条断言的是"根本不发 RETURN"，理由是 `distance` 属 KNN 别名、能否 RETURN 未证实；
    真机已证实 `RETURN 2 value_json distance` 两个都回得来 ⇒ 该前提消除，断言反过来钉住
    "必须发 RETURN 且字段集合恰好是这两个"。
    """
    argv = _search_argv()
    tokens = [str(a) for a in argv]
    assert "RETURN" in [t.upper() for t in tokens], tokens
    i = [t.upper() for t in tokens].index("RETURN")
    count = int(argv[i + 1])
    fields = tokens[i + 2 : i + 2 + count]
    assert fields == ["value_json", "distance"], fields
    assert "query_vec" not in fields, "二进制向量字段进 RETURN = 解码即崩"


def test_index_name_is_partitioned_by_key_prefix():
    """索引名必须含 CACHE_KEY_PREFIX 的 token。

    真机读数：索引名不含前缀时，第二个实例（同 scope/model/dim、不同前缀）会复用第一个
    实例的索引（建索引前只判同名在不在），于是自己的写入永远不进索引——`num_docs=0`、
    `hash_indexing_failures=0`、`state=ready`，一条日志都不留；而它的检索跑在别人的数据上。
    契约首跑的四条 L2 红就是这个撞车（每个用例用随机前缀、索引名却相同）。
    """
    def named(prefix: str) -> str:
        return CacheConfig(
            backend="valkey",
            valkey_url="redis://localhost:6379/0",
            vector_dim=_DIM,
            embedding_model="mock",
            key_prefix=prefix,
        ).index_name("agent_server", "mock", _DIM)

    name_a = named("inst-a")
    name_b = named("inst-b")
    assert name_a != name_b, "同 scope/model/dim、不同前缀必须落到不同索引"
    assert name_a.endswith(f"_s{CacheConfig.index_schema_version}")
    assert safe_token("inst-a") in name_a


def test_star_suffix_tenant_is_rejected_not_escaped():
    """星号结尾的租户**根本不该发出 L2 查询**。

    这条用例的前身断言的是"我们发了 `@tenant:{acme\\*}`"——那个断言是错的守卫：
    真机（bundle 9.1.2 / search 1.2.1）实测反斜杠不关掉通配，`{acme\\*}` 与 `{acme*}`
    同样把 `acme`、`acmeX` 一起前缀命中。假客户端不解释查询串，所以旧断言一直绿着，
    而它承诺的隔离并不存在。 ⇒ 判据改成"拒绝"，转义挡不住的东西不许用转义来安心。
    """
    cache, fake = _backend()
    cache._index_ready = True
    import asyncio

    hit = asyncio.run(
        cache._search_l2(
            tenant_id="acme*",
            vector=[0.1] * _DIM,
            epoch=0,
            kb_versions=None,
            gray_pct=0.0,
        )
    )
    assert hit is None
    assert fake.search.searches == [], "被拒绝的租户不该发出任何 L2 查询"
    assert cache.get_stats()["skipped_unsafe_tag"] == 1
    # 与"没有租户"分账：两者原因不同，混计会让排查找错方向
    assert cache.get_stats()["skipped_no_tenant"] == 0


def test_star_suffix_tenant_write_is_skipped_l1_unaffected():
    """写侧同样 fail-closed；但 L1 走精确 key（不含 TAG 查询串），不受该规则牵连。"""
    cache, fake = _backend()
    cache._index_ready = True
    cache._started = True
    import asyncio

    asyncio.run(
        cache._write_positive(
            keys=cache._keys("acme*", "k", 0),
            value_json="{}",
            vector=[0.1] * _DIM,
            tenant_id="acme*",
            intent="refund",
            rewritten_query="q",
            kb_sig="kb",
            gray_tag="0.0",
            epoch=0,
            ttl=60,
            l2_ttl=60,
        )
    )
    assert cache.get_stats()["skipped_unsafe_tag"] == 1


def test_star_inside_value_is_not_rejected_this_round():
    """中间位置的 `*` 本轮**不**扩大拒绝面——它的通配语义尚未在真机确认。

    这条不是"证明安全"，而是把"我们只拒了已实测有害的那一类"写清楚，
    免得后来人以为所有星号都已被挡。上机复验若显示中间星号也参与匹配，就收紧。
    """
    assert ValkeySemanticCache._tag_reject_reason("ac*me") is None
    assert ValkeySemanticCache._valid_tag("ac*me") == "ac*me"


def test_empty_and_separator_tags_still_attribute_to_no_tenant():
    """拒绝原因分账的反向：空值/分隔符不归到 unsafe_tag，否则新计数会变成大杂烩。"""
    for bad in ("", "a\x1fb"):
        assert ValkeySemanticCache._tag_reject_reason(bad) in ("empty", "separator")


def test_l1_logical_key_partitions_by_every_isolation_dimension():
    """L1 是精确键：分区维度只能靠键本身，少一个维度就是跨分区读到别人的正文。

    这条补的是 m09（真机反证里唯一活到最后的一个变异）：把 tenant 从 `_logical_key`
    的参数里摘掉，L2 的 TAG 过滤、CASESENSITIVE、索引分区全都还在 ⇒ 引擎层照样隔离，
    只有 L1 会跨租户命中。而隔离类契约用例为了强制走 L2 都换了措辞，于是两头都不红。
    """
    cache, _ = _backend()

    def key(
        *,
        intent: str = "refund",
        rewritten_query: str = "q",
        kb_versions: dict[str, str] | None = None,
        tenant_id: str = "t1",
        gray_pct: float = 0.0,
    ) -> str:
        return cache._logical_key(intent, rewritten_query, kb_versions, tenant_id, gray_pct)

    base = key()
    assert key(tenant_id="t2") != base, "L1 键必须含租户：摘掉即跨租户命中"
    assert key(kb_versions={"kb": "v1"}) != base
    assert key(gray_pct=0.5) != base
    assert key(intent="other") != base
    assert key(rewritten_query="") != base
    assert key() == base, "同输入必须同键，否则 L1 永不命中"


# ---------------------------------------------------------------------------
# 以下各条来自 `make mutation` 全量战役（333 刀）留下的存活体分诊。
# 共同点：本文件此前只钉"发出去的命令"，没钉"计数对不对、连接怎么建、两个后端形状
# 是否一致"——那些位置变异后套件照样绿，所以它们一直没人认领。
# ---------------------------------------------------------------------------


def test_disabled_backend_reports_every_valkey_runtime_counter():
    """切后端不许换 stats 的形状：消费方是 `**get_stats()` 摊进监控事件/`/health`。

    战役发现 disabled 侧少了 `error / embedding_error / l2_unavailable / index_missing`
    四个键——少键不报错，只在 `CACHE_BACKEND` 从 valkey 切成 disabled 时静默换掉事件形状。
    全 0 也是语义正确的断言（这个后端从不计数），不是摆设。
    """
    cache, _ = _backend()
    valkey_keys = set(cache.get_stats())
    disabled = DisabledSemanticCache("agent_server").get_stats()
    assert not valkey_keys - set(disabled), f"disabled 少了这些键：{valkey_keys - set(disabled)}"
    assert disabled["backend"] == "disabled" and disabled["scope"] == "agent_server"
    counters = {k: v for k, v in disabled.items() if k not in {"backend", "scope", "hit_rate"}}
    assert set(counters) >= {"total", "skipped_no_tenant", "skipped_unsafe_tag", "skipped_pii", "dropped_writes"}
    assert all(v == 0 for v in counters.values()), counters


def test_client_connection_kwargs_are_part_of_the_line_format(monkeypatch):
    """连接参数与线格式是一对，必须一起钉。

    `decode_responses=True` 只在"RETURN 只回文本字段"成立时才安全（见
    `test_l2_argv_returns_only_the_two_text_fields`）；而 `retry_on_timeout=False` 是把
    "读一次就熔断计数"留住的前提——命令级重tries会把一次超时拆成多次写，写队列语义就变了。
    战役里这五个 kwargs 全是存活体，因为本文件过去不看 `_create_client`。
    """
    import valkey.asyncio as valkey_asyncio

    seen: dict[str, Any] = {}

    def _fake_from_url(url: str, **kwargs: Any) -> _FakeClient:
        seen["url"] = url
        seen.update(kwargs)
        return _FakeClient()

    monkeypatch.setattr(valkey_asyncio.Valkey, "from_url", staticmethod(_fake_from_url))
    cfg = CacheConfig(
        backend="valkey",
        valkey_url="redis://192.0.2.10:6379/2",
        connect_timeout_ms=50,
        command_timeout_ms=100,
        vector_dim=_DIM,
        embedding_model="mock",
    )
    ValkeySemanticCache(cfg, "agent_server", embedder=_MockEmbedder())
    assert seen["url"] == "redis://192.0.2.10:6379/2"
    assert seen["decode_responses"] is True
    assert seen["socket_connect_timeout"] == pytest.approx(0.05)
    assert seen["socket_timeout"] == pytest.approx(0.1)
    assert seen["retry_on_timeout"] is False
    assert seen["health_check_interval"] == 30


def test_dialect_keyword_is_followed_by_its_value():
    """`DIALECT` 后面那个数才是 dialect——旧的 `2 in argv` 被 `RETURN 2` 满足了，恒真。

    这是 §11 第 28 行那条教训的本地版：**形状断言若不绑定位置，就永远绿着但什么都没说**。
    没有 DIALECT 2，KNN 的 `=>[KNN ...]` 向量过滤语法在 search 1.2.x 上直接报错。
    """
    argv = _search_argv()
    tokens = [str(a).upper() for a in argv]
    i = tokens.index("DIALECT")
    assert argv[i + 1] == 2, argv[i - 1 : i + 3]


@pytest.mark.parametrize("method", ["set_negative", "invalidate", "invalidate_namespace"])
def test_empty_tenant_guard_counts_exactly_on_the_other_three_methods(method):
    """三个写/失效入口各有一份租户守卫，都要"计一次且只计一次"。

    既有用例只覆盖了 get/set 两处（那两个计数器增量是被钉住的）；这三处的 `+= 1` 变异成
    `+= 0`（不计数）或 `+= 2`（重复计）都能活，因为它们压根没被调用过。
    计数分账很重要：`skipped_no_tenant` 是"调用方没带租户"，和 `error`（后端故障）混了就查错方向。
    """
    import asyncio

    cache, _ = _backend()
    kwargs: dict[str, Any] = {"tenant_id": ""}
    if method != "invalidate_namespace":
        kwargs |= {"intent": "refund", "rewritten_query": "q"}
    asyncio.run(getattr(cache, method)(**kwargs))
    stats = cache.get_stats()
    assert stats["skipped_no_tenant"] == 1
    assert stats["error"] == 0, "空租户是拒绝，不是后端故障"
    assert stats["dropped_writes"] == 0


class _RaisingEmbedder:
    dim = _DIM

    async def aembed(self, texts: list[str]) -> list[list[float]]:
        msg = "嵌入模型不可用"
        raise RuntimeError(msg)


class _ShortEmbedder:
    dim = _DIM

    async def aembed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 3 for _ in texts]


def test_embedding_failure_and_dim_drift_each_count_one_embedding_error():
    """L2 的三条"向量拿不到"出路分开钉：显式向量维度不符 / embedder 抛错 / embedder 返回维度漂移。

    三者都只跳过 L2、不影响 L1，但它们的原因完全不同；`+= 1` 变异成 `+= 0` 时线上表现是
    "L2 命中率莫名掉到 0 而读数上看不见任何错误"——正是本仓最难查的那一类。
    """
    import asyncio

    cache, _ = _backend()
    assert asyncio.run(cache._resolve_embedding([0.1] * 3, "q")) is None
    assert cache.get_stats()["embedding_error"] == 1

    cache2, _ = _backend()
    cache2._embedder = _RaisingEmbedder()
    assert asyncio.run(cache2._resolve_embedding(None, "q")) is None
    assert cache2.get_stats()["embedding_error"] == 1
    assert cache2.get_stats()["error"] == 0, "embedder 故障不计入 valkey 错误面"

    cache3, _ = _backend()
    cache3._embedder = _ShortEmbedder()
    assert asyncio.run(cache3._resolve_embedding(None, "q")) is None
    assert cache3.get_stats()["embedding_error"] == 1


def test_unknown_dim_and_failed_index_creation_are_counted_as_l2_unavailable():
    """`l2_unavailable` 的两个来源各钉一次：维度未知（永不能建索引）与建索引被拒。"""
    import asyncio
    import time

    cache, _ = _backend()
    cache._dim = 0
    cache._index_ready = False
    assert asyncio.run(cache._ensure_index()) is False
    assert cache.get_stats()["l2_unavailable"] == 1

    class _NoSearchIndex(_FakeSearch):
        async def create_index(self, fields, definition=None):
            raise ResponseError("FT.CREATE command returned err")

    cache2, _ = _backend()
    cache2._client = _FakeClient(ft_obj=_NoSearchIndex())
    assert asyncio.run(cache2._ensure_index()) is False
    stats = cache2.get_stats()
    assert stats["l2_unavailable"] == 1
    assert stats["index_missing"] == 0, "建索引失败与索引被外部摘掉是两件事"
    assert cache2._index_ready is False
    assert cache2._index_next_retry > time.monotonic(), "失败后要进入退避，别每次读都重试"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, 0), ("5", 5), ("garbage", 0)],
)
def test_epoch_reads_absent_or_garbage_as_zero_not_none(raw, expected):
    """epoch 键缺失 → 0；值不是整数 → 0。**都不许返回 None**。

    返回 None 会让写侧直接跳过（`_job` 里 `if epoch is None: return`）——表现是"每个新租户
    的缓存永远写不进去"，而读数上没有任何错误。三态里只有"客户端报错"才该是 None（走 fallback）。
    """
    import asyncio

    class _GetClient:
        def __init__(self, value: Any) -> None:
            self.value = value

        async def get(self, _key: str) -> Any:
            return self.value

    cache, _ = _backend()
    cache._client = _GetClient(raw)
    assert asyncio.run(cache._current_epoch("t1")) == expected


def test_epoch_client_error_reads_as_missing_not_zero():
    """后端故障时读成 `_MISSING`（→ None），不能和"键不存在"（→ 0）混为一谈。

    混了就会把故障当成"该租户还没有 epoch"，于是写入落在 epoch 0 上、而真实 epoch 早已
    改名 ⇒ 这批写入永远检索不到（静默丢缓存）。
    """
    import asyncio

    class _BoomClient:
        async def get(self, _key: str) -> Any:
            raise ValkeyError("connection reset")

    cache, _ = _backend()
    cache._client = _BoomClient()
    assert asyncio.run(cache._current_epoch("t1")) is None
    assert cache.get_stats()["error"] == 1


class _RouterClient(_FakeClient):
    """按 key 形状给返回值的假客户端：`get` 是读路径唯一的三态来源。

    三态必须能分开测：**键存在有值** / **键不存在（None）** / **读失败（_MISSING）**。
    以前假客户端的 `get` 只会返回 None，所以"失败被当成未命中"和"未命中被当成命中"
    这两类变异都测不出来。
    """

    def __init__(self, values: dict[str, Any] | None = None, error_on: tuple[str, ...] = ()) -> None:
        super().__init__()
        self._values = values or {}
        self._error_on = error_on
        self.got: list[str] = []

    @staticmethod
    def _kind(key: str) -> str:
        for kind in ("null", "l1", "l2", "epoch"):
            if f":{kind}:" in key:
                return kind
        return "other"

    async def get(self, key: str) -> Any:
        self.got.append(key)
        kind = self._kind(key)
        if kind in self._error_on:
            raise ValkeyError(f"simulated read failure on {kind}")
        return self._values.get(kind)

    async def ping(self) -> bool:
        return True


def test_null_hit_requires_an_actual_negative_value():
    """负缓存命中只认"键存在且有值"；读失败与键不存在都必须继续往下读 L1。

    把 `null_raw is not _MISSING and null_raw is not None` 的任一侧改掉，表现都是
    **"后端一抖动就把这个查询永久判成未命中"**（在 null_ttl 内不再回源），
    这是命中率与正确性问题，不是性能问题。
    """
    import asyncio

    cache, _ = _backend()
    cache._started = True
    cache._client = _RouterClient({"null": "1", "l1": '{"answer":"x"}'})
    hit = asyncio.run(cache.get(tenant_id="t1", intent="refund", rewritten_query="q"))
    assert hit is not None and hit.layer == "null"
    assert cache._client.got and all(":l1:" not in k for k in cache._client.got), "负缓存命中不该再读正文"

    cache2, _ = _backend()
    cache2._started = True
    cache2._index_ready = True
    cache2._client = _RouterClient({"l1": '{"answer":"x"}'}, error_on=("null",))
    hit2 = asyncio.run(cache2.get(tenant_id="t1", intent="refund", rewritten_query="q"))
    assert hit2 is not None and hit2.layer == "l1", "负缓存读失败被当成命中 = 永久不回源"
    assert cache2.get_stats().get("null_hit", 0) == 0


def test_l1_requires_a_json_object_and_treats_read_failure_as_miss():
    """L1 只认"能解析成 dict 的正文"；空串与读失败都不是命中。"""
    import asyncio

    for values, error_on, expect_layer in (
        ({"l1": '{"answer":"x"}'}, (), "l1"),
        ({"l1": ""}, (), None),
        ({"l1": "not-json"}, (), None),
        ({}, ("l1",), None),
    ):
        cache, _ = _backend()
        cache._started = True
        cache._index_ready = True
        cache._client = _RouterClient(values, error_on=error_on)
        hit = asyncio.run(cache.get(tenant_id="t1", intent="refund", rewritten_query="q"))
        assert (hit.layer if hit else None) == expect_layer, values
        stats = cache.get_stats()
        assert stats.get("l1_hit", 0) == (1 if expect_layer == "l1" else 0)
        assert stats.get("l2_hit", 0) == 0


def test_epoch_read_failure_short_circuits_to_miss_without_reading_values():
    """epoch 读失败（None）时**不许**继续读 null/l1。

    继续读会用 epoch 0 的键去查一个早已改名的命名空间：结果是"永远未命中"，
    而 stats 里只多几条 miss，看不出任何故障。
    """
    import asyncio

    cache, _ = _backend()
    cache._started = True
    cache._client = _RouterClient({"l1": '{"answer":"x"}'}, error_on=("epoch",))
    hit = asyncio.run(cache.get(tenant_id="t1", intent="refund", rewritten_query="q"))
    assert hit is None
    assert cache.get_stats()["miss"] == 1
    assert all(":l1:" not in k and ":null:" not in k for k in cache._client.got)


def test_startup_only_builds_index_when_ping_succeeds(monkeypatch):
    """启动顺序就是正确性：ping 失败时不许去建索引，且 `_started` 仍要置位（不重复握手）。"""
    import asyncio

    cache, fake = _backend()
    calls: list[str] = []

    class _Pinging(_FakeClient):
        def __init__(self, ok: bool) -> None:
            super().__init__()
            self._ok = ok

        async def ping(self) -> bool:
            return self._ok

    async def _spy_ensure_index() -> bool:
        calls.append("ensure_index")
        return True

    monkeypatch.setattr(ValkeySemanticCache, "_ensure_index", lambda self: _spy_ensure_index())

    ok_client = _Pinging(True)
    cache._client = ok_client
    asyncio.run(cache.startup())
    assert calls == ["ensure_index"]
    assert cache._started is True
    asyncio.run(cache.startup())
    assert calls == ["ensure_index"], "已启动的实例第二次 startup 必须是空操作"

    cache2, _ = _backend()
    cache2._client = _Pinging(False)
    asyncio.run(cache2.startup())
    assert calls == ["ensure_index"], "ping 失败还要建索引 = 在连不上的实例上白跑 FT.CREATE"


def test_embedder_reload_is_throttled_by_the_cooldown_clock():
    """embedder 加载失败后的 30s 冷却：每个请求都重试会让启动路径反复走线程池。"""
    import asyncio
    import time

    cache, _ = _backend()
    cache._embedder = None
    loaded: list[str] = []

    async def _spy() -> None:
        loaded.append("load")

    cache._load_embedder = _spy  # type: ignore[method-assign]

    cache._embedder_next_retry = time.monotonic() + 30.0
    assert asyncio.run(cache._ensure_embedder()) is None
    assert loaded == [], "冷却期内不许重新加载模型"

    cache._embedder_next_retry = time.monotonic() - 1.0
    assert asyncio.run(cache._ensure_embedder()) is None
    assert loaded == ["load"], "冷却到期必须真的去加载一次"


def test_index_readiness_transitions_and_backoff():
    """`_ensure_index` 的每条出路都要钉返回值与副作用：已就绪 / 冷却中 / info 成功 / 建索引失败后 info 成功。"""
    import asyncio
    import time

    class _InfoOk(_FakeSearch):
        def __init__(self) -> None:
            super().__init__()
            self.info_calls = 0
            self.create_calls = 0

        async def info(self) -> dict:
            self.info_calls += 1
            return {"num_docs": 0}

        async def create_index(self, fields, definition=None):
            self.create_calls += 1
            raise ResponseError("FT.CREATE returned err")

    cache, _ = _backend()
    cache._index_ready = True
    spy = _InfoOk()
    cache._client = _FakeClient(ft_obj=spy)
    assert asyncio.run(cache._ensure_index()) is True
    assert spy.info_calls == 0, "已就绪时不该再发 FT.INFO"

    cache2, _ = _backend()
    cache2._index_ready = False
    cache2._index_next_retry = time.monotonic() + 30.0
    spy2 = _InfoOk()
    cache2._client = _FakeClient(ft_obj=spy2)
    assert asyncio.run(cache2._ensure_index()) is False
    assert spy2.info_calls == 0, "退避期内不许发命令"

    class _CreateFailThenInfoOk(_FakeSearch):
        def __init__(self) -> None:
            super().__init__()
            self.info_calls = 0

        async def info(self) -> dict:
            self.info_calls += 1
            if self.info_calls == 1:
                raise ResponseError("Unknown Index name")
            return {"num_docs": 0}

        async def create_index(self, fields, definition=None):
            raise ResponseError("BUSYINDEX concurrent create")

    cache3, _ = _backend()
    cache3._client = _FakeClient(ft_obj=_CreateFailThenInfoOk())
    assert asyncio.run(cache3._ensure_index()) is True, "并发建索引撞车后 FT.INFO 成功就算就绪"
    assert cache3._index_ready is True
    assert cache3.get_stats()["l2_unavailable"] == 0

    cache4, _ = _backend()
    cache4._dim = 1
    assert asyncio.run(cache4._ensure_index()) is True
    assert cache4._index_ready is True, "dim=1 是合法维度，不许被「未知维度」的守卫挡掉"


def test_health_shape_for_closed_unreachable_and_degraded(monkeypatch):
    """健康态三种非 ready 形状分开钉：关闭中 / ping 失败且无原因 / ping 失败但已有降级原因。

    `if not ok and not reason` 的任一侧改掉，表现是"降级原因被 valkey_unreachable 覆盖"
    ——运维看到的将是"连不上"，而真实原因（索引不可用 / embedder 不可用）消失。
    """
    import asyncio

    cache, _ = _backend()

    class _Ping(_FakeClient):
        def __init__(self, ok: bool = True) -> None:
            super().__init__()
            self._ok = ok

        async def ping(self) -> bool:
            return self._ok

    cache._closing = True
    health = asyncio.run(cache.health())
    assert health.ready is False and health.degraded_reason == "closed" and health.index is None

    cache2, _ = _backend()
    cache2._client = _Ping(False)
    health2 = asyncio.run(cache2.health())
    assert health2.ready is False and health2.degraded_reason == "valkey_unreachable"

    cache3, _ = _backend()
    cache3._client = _Ping(False)
    cache3._degraded_reason = "search_index_unavailable: boom"
    health3 = asyncio.run(cache3.health())
    assert health3.degraded_reason == "search_index_unavailable: boom", "已有原因不许被覆盖"

    cache4, _ = _backend()
    cache4._client = _Ping(True)
    cache4._index_ready = True
    health4 = asyncio.run(cache4.health())
    assert health4.ready is True and health4.index == cache4._index
    assert health4.degraded_reason is None


def test_flush_and_aclose_shapes(monkeypatch):
    """未启动工作队列时 flush 是空操作；aclose 幂等且两种客户端方法都要走。"""
    import asyncio

    cache, _ = _backend()
    assert cache._queue is None
    asyncio.run(cache.flush())  # 不许抛，也不许等满超时

    closed: list[str] = []

    class _AcloseClient(_FakeClient):
        async def aclose(self) -> None:
            closed.append("aclose")

    cache._client = _AcloseClient()
    asyncio.run(cache.aclose())
    assert closed == ["aclose"]
    asyncio.run(cache.aclose())
    assert closed == ["aclose"], "aclose 必须幂等（_closing 守卫）"
    assert cache._closing is True

    cache2, _ = _backend()

    class _CloseOnly(_FakeClient):
        async def close(self) -> None:
            closed.append("close")

    cache2._client = _CloseOnly()
    asyncio.run(cache2.aclose())
    assert "close" in closed, "旧版客户端只有 close()，缺 aclose 时不许静默不关连接"


def test_pipeline_atomicity_flag_is_partitioned_by_purpose():
    """epoch 的 INCR+PERSIST 必须原子，正文写入必须**不**原子。

    前者不原子会出现"epoch 涨了但 persist 没发"⇒ 键带着旧 TTL 过期 ⇒ 归零 ⇒ 旧数据复活；
    后者原子化则把一次 HSET+EXPIRE 变成事务，写队列吞吐被无谓限住。
    """
    import asyncio

    cache, fake = _backend()
    cache._started = True
    asyncio.run(cache.invalidate_namespace(tenant_id="t1"))
    assert fake.pipeline_flags == [True], fake.pipeline_flags

    cache2, fake2 = _backend()
    cache2._started = True
    cache2._index_ready = True
    asyncio.run(
        cache2._write_positive(
            keys=cache2._keys("t1", "k", 0),
            value_json="{}",
            vector=[0.1] * _DIM,
            tenant_id="t1",
            intent="refund",
            rewritten_query="q",
            kb_sig="kb",
            gray_tag="0.0",
            epoch=0,
            ttl=60,
            l2_ttl=60,
        )
    )
    assert fake2.pipeline_flags == [False], fake2.pipeline_flags
    ops = [op for op, _a, _kw in fake2.pipeline_obj.ops]
    assert ops == ["set", "delete", "hset", "expire"], ops


def test_ttl_floor_and_namespace_hash_lengths_are_pinned():
    """TTL 下限 1 与命名空间摘要 16 位都是"键形状"，长度漂了会撞键或让键立即过期。"""
    cache, _ = _backend()
    assert cache._ttl(0) == 1
    assert cache._ttl(-5) == 1
    assert cache._ttl(2) == 2
    assert cache._ttl(None) == cache._cfg.l1_ttl_seconds

    sig_a = ValkeySemanticCache._kb_signature({"kb": "1", "other": "2"})
    sig_b = ValkeySemanticCache._kb_signature({"other": "2", "kb": "1"})
    assert sig_a == sig_b, "dict 插入顺序不许改变签名（否则同一份知识库算成两个版本）"
    assert len(sig_a) == 16
    assert ValkeySemanticCache._kb_signature(None) == "none"
    assert len(ValkeySemanticCache._tenant_token("t1")) == 16
    assert ValkeySemanticCache._tenant_token("t1") != ValkeySemanticCache._tenant_token("t2")


def _trip_breaker(cache: ValkeySemanticCache) -> None:
    for _ in range(cache._cfg.breaker_failure_threshold):
        cache._breaker.record_failure()
    assert cache._breaker.allow() is False


def test_negative_cache_switch_and_open_breaker_both_skip_the_write_job():
    """`set_negative` 的两道守卫各自都要拦下入队：关掉负缓存 / 熔断打开。

    熔断打开时继续入队会做两件事：往一个已知坏掉的后端排队写，以及把"缓存未命中"和
    "后端故障"两件事在 stats 里搅成一团（`dropped_writes` 会涨，读起来像队列容量问题）。
    """
    import asyncio

    enqueued: list[str] = []

    cache, _ = _backend()
    cache._started = True
    cache._enqueue = lambda job: enqueued.append("job")  # type: ignore[assignment]
    asyncio.run(cache.set_negative(tenant_id="t1", intent="refund", rewritten_query="q"))
    assert enqueued == ["job"], "正常路径必须入队一次"

    cache2, _ = _backend()
    cache2._started = True
    cache2._cfg = dataclasses.replace(cache2._cfg, negative_cache_enabled=False)
    cache2._enqueue = lambda job: enqueued.append("neg-off")  # type: ignore[assignment]
    asyncio.run(cache2.set_negative(tenant_id="t1", intent="refund", rewritten_query="q"))
    assert enqueued == ["job"], "CACHE_NULL_ENABLED=false 时负缓存写入必须整段跳过"

    cache3, _ = _backend()
    cache3._started = True
    _trip_breaker(cache3)
    cache3._enqueue = lambda job: enqueued.append("breaker-open")  # type: ignore[assignment]
    asyncio.run(cache3.set_negative(tenant_id="t1", intent="refund", rewritten_query="q"))
    assert enqueued == ["job"], "熔断打开时不许继续排队写"
    assert cache3.get_stats()["dropped_writes"] == 0, "熔断拦下的是「不发」，不是「发了又丢」"


@pytest.mark.asyncio
async def test_aclose_drains_then_cancels_the_worker(monkeypatch):
    """`aclose` 只有在"队列与 worker 都在"时才排空并取消——两个守卫任改一个都会留下孤儿任务。

    表现：优雅关闭后仍有后台任务在往已经关掉的连接上写（异常被 fail-open 吞掉），
    或反过来队列里未完成的写入被直接丢弃而读数上只看得到"关闭成功"。
    """
    cache, _ = _backend()
    closed: list[str] = []

    class _TrackingClient(_FakeClient):
        async def aclose(self) -> None:
            closed.append("aclose")

    cache._client = _TrackingClient()
    cache._ensure_worker()
    assert cache._queue is not None and cache._worker is not None

    drained: list[str] = []

    async def _spy_flush() -> None:
        drained.append("flush")

    monkeypatch.setattr(cache, "flush", _spy_flush)
    worker = cache._worker
    await cache.aclose()

    assert drained == ["flush"], "有 worker 时必须先排空队列"
    assert worker.cancelled() or worker.done(), "关闭路径必须取消后台任务"
    assert cache._worker is None
    assert cache._closing is True
    assert closed == ["aclose"], "排空与取消之后仍要关连接"


def test_circuit_open_records_reason_only_when_none():
    """`_run` 在熔断打开时补的降级原因不许覆盖已有原因。

    覆盖了会看到什么：线上只剩 `valkey_unreachable`/`circuit_open` 一类笼统字样，
    真正的病灶（索引不可用、embedder 不可用）从 health 里消失——正是第 43 行那类"只换语义不报错"。
    """
    import asyncio

    cache, _ = _backend()
    _trip_breaker(cache)
    assert asyncio.run(cache._run(cache._client.get, "k", op="probe")) is None
    assert cache._degraded_reason == "circuit_open"

    cache2, _ = _backend()
    _trip_breaker(cache2)
    cache2._degraded_reason = "search_index_unavailable: boom"
    asyncio.run(cache2._run(cache2._client.get, "k", op="probe"))
    assert cache2._degraded_reason == "search_index_unavailable: boom"


def test_startup_with_failing_ping_does_not_try_to_create_index(monkeypatch):
    """ping 抛异常（不是返回 False）时同样不许去建索引——这条钉的是 `_run` 的 `fallback=False`。

    把 fallback 改成 True，启动路径就会在连不上的实例上发 FT.CREATE：白跑一次并可能把
    `_index_ready` 之外的状态搞脏，而 health 仍然报 unreachable，读数上看不出多做了一件事。
    """
    import asyncio

    calls: list[str] = []

    async def _spy_ensure_index() -> bool:
        calls.append("ensure_index")
        return True

    class _PingRaises(_FakeClient):
        async def ping(self) -> bool:
            raise ValkeyError("connection refused")

    monkeypatch.setattr(ValkeySemanticCache, "_ensure_index", _spy_ensure_index)
    cache, _ = _backend()
    cache._client = _PingRaises()
    asyncio.run(cache.startup())
    assert calls == [], "ping 失败仍建索引 = 在坏实例上白跑 FT.CREATE"
    assert cache.get_stats()["error"] == 1


class _DimEmbedder:
    def __init__(self, dim: Any) -> None:
        if dim is not None:
            self.dim = dim


def test_embedder_dim_is_validated_at_the_boundary_values():
    """`embedder.dim` 的 0 / 负数 / 缺失 / 1 四个边界各钉一次。

    这条守卫决定的是**命名空间与索引 DIM**：dim=0 被当成合法值放行，就会建出一个 DIM=0 的
    向量索引（引擎侧报错或永不出结果，而启动读数一切正常）；而"默认 0"被改成 1 会让
    **没有 dim 属性的 embedder** 悄悄跑起来，索引维度与实际向量不一致。
    """
    cfg = CacheConfig(backend="valkey", valkey_url="redis://localhost:6379/0", vector_dim=0, embedding_model="")
    with pytest.raises(CacheConfigError, match="embedder.dim 非法: 0"):
        ValkeySemanticCache(cfg, "unit", embedder=_DimEmbedder(0))
    with pytest.raises(CacheConfigError, match="embedder.dim 非法: -1"):
        ValkeySemanticCache(cfg, "unit", embedder=_DimEmbedder(-1))
    with pytest.raises(CacheConfigError, match="embedder.dim 非法: 0"):
        ValkeySemanticCache(cfg, "unit", embedder=_DimEmbedder(None))  # 无 dim 属性 → 默认 0
    ok = ValkeySemanticCache(cfg, "unit", embedder=_DimEmbedder(1))
    assert ok._dim == 1, "dim=1 是合法维度，不许被「未知」守卫挡掉"
    assert ok._model, "模型名走兜底派生，不许是空的"


def test_configured_model_wins_and_conflict_with_env_dim_still_raises():
    """`CACHE_EMBEDDING_MODEL` 存在时用配置值（不派生）；与 `CACHE_VECTOR_DIM` 冲突必须启动期失败。"""
    cfg = CacheConfig(
        backend="valkey",
        valkey_url="redis://localhost:6379/0",
        vector_dim=8,
        embedding_model="configured",
    )
    cache = ValkeySemanticCache(cfg, "unit", embedder=_DimEmbedder(8))
    assert cache._dim == 8
    assert cache._model == "configured", "配置里给了模型名却去派生 = 命名空间随类名漂移"

    clash = CacheConfig(
        backend="valkey",
        valkey_url="redis://localhost:6379/0",
        vector_dim=16,
        embedding_model="configured",
    )
    with pytest.raises(CacheConfigError, match="embedding 维度不一致"):
        ValkeySemanticCache(clash, "unit", embedder=_DimEmbedder(8))


class LocalEmbedder:  # 类名本身是判据：`_embedder_model_id` 按类名分支
    pass


def test_embedder_model_id_falls_back_in_the_declared_order(monkeypatch):
    """派生模型 id 的三级兜底：`_model` 字符串 → LocalEmbedder 的环境变量 → 类名。

    这一位进的是索引名与 key 前缀，选错一级不会报错，只会让同一个模型换命名空间
    （= 缓存整体失效，或换模型后仍复用旧索引）。
    """

    class _Named:
        _model = "bge-m3"

    class _EmptyNamed:
        _model = ""

    class _WrongType:
        _model = 123

    assert ValkeySemanticCache._embedder_model_id(_Named()) == "_Named:bge-m3"
    assert ValkeySemanticCache._embedder_model_id(_EmptyNamed()) == "_EmptyNamed"
    assert ValkeySemanticCache._embedder_model_id(_WrongType()) == "_WrongType"
    assert ValkeySemanticCache._embedder_model_id(_DimEmbedder(4)) == "_DimEmbedder"

    monkeypatch.setenv("INTENT_EMBEDDING_MODEL", "BAAI/bge-large-zh")
    assert ValkeySemanticCache._embedder_model_id(LocalEmbedder()) == "LocalEmbedder:BAAI/bge-large-zh"
    monkeypatch.delenv("INTENT_EMBEDDING_MODEL", raising=False)
    assert ValkeySemanticCache._embedder_model_id(LocalEmbedder()) == "LocalEmbedder:BAAI/bge-small-zh-v1.5"


def test_unknown_dim_skips_l2_on_both_read_and_write_paths():
    """`_dim` 未知（0）时读写两侧都只走 L1，且**根本不该去建索引**。

    `self._dim > 0` 写成 `>= 0` 或 `> -1` 都不会报错，但会在 L2 上白跑一次 `_ensure_index`
    （那里 dim<=0 直接计数 l2_unavailable），于是"缓存没命中"与"维度没解析出来"两种故障
    在同一个计数器上混起来。
    """
    import asyncio

    cache, fake = _backend()
    cache._started = True
    cache._dim = 0
    hit = asyncio.run(
        cache.get(tenant_id="t1", intent="refund", rewritten_query="q", embedding=[0.1] * _DIM)
    )
    assert hit is None
    assert fake.search.searches == [], "dim 未知还发 FT.SEARCH"
    assert cache.get_stats()["l2_unavailable"] == 0, "dim 未知不该去碰 _ensure_index"

    cache2, fake2 = _backend()
    cache2._started = True
    cache2._dim = 0
    asyncio.run(
        cache2._write_positive(
            keys=cache2._keys("t1", "k", 0),
            value_json='{"answer":"a"}',
            vector=[0.1] * _DIM,
            tenant_id="t1",
            intent="refund",
            rewritten_query="q",
            kb_sig="kb",
            gray_tag="0.0",
            epoch=0,
            ttl=60,
            l2_ttl=60,
        )
    )
    ops = [op for op, _a, _kw in fake2.pipeline_obj.ops]
    assert ops == ["set", "delete"], f"dim 未知时 L2 的 hset/expire 不该发出：{ops}"
    assert cache2.get_stats()["l2_unavailable"] == 0


def test_explicit_embedding_is_unchecked_when_dim_unknown():
    """dim 未知时**不校验**显式传入的向量长度（没有基准可比）；dim 已知才比对。"""
    import asyncio

    cache, _ = _backend()
    cache._dim = 0
    assert asyncio.run(cache._resolve_embedding([0.1] * 3, "q")) == [0.1] * 3
    assert cache.get_stats()["embedding_error"] == 0

    cache2, _ = _backend()
    assert asyncio.run(cache2._resolve_embedding([0.1] * 1, "q")) is None
    assert cache2.get_stats()["embedding_error"] == 1


def test_l2_ttl_and_l1_ttl_both_floor_at_one_second():
    """TTL 下限 1 秒在两侧各钉一次：`expire(key, 0)` 在 Valkey 里是**参数错误**，
    会让整条 pipeline 失败（写入静默丢失），而配置上写 0 秒的人只是想"尽量短"。
    """
    import asyncio

    cache, fake = _backend()
    cache._started = True
    cache._index_ready = True
    asyncio.run(
        cache._write_positive(
            keys=cache._keys("t1", "k", 0),
            value_json="{}",
            vector=[0.1] * _DIM,
            tenant_id="t1",
            intent="refund",
            rewritten_query="q",
            kb_sig="kb",
            gray_tag="0.0",
            epoch=0,
            ttl=60,
            l2_ttl=0,
        )
    )
    expires = [args for op, args, _kw in fake.pipeline_obj.ops if op == "expire"]
    assert expires and expires[0][1] == 1, expires
    sets = [kwargs for op, _a, kwargs in fake.pipeline_obj.ops if op == "set"]
    assert sets and sets[0]["ex"] == 60


def test_l2_uses_the_first_doc_because_that_is_the_nearest_neighbor():
    """KNN 结果按距离升序返回：取 `docs[-1]` 会命中"最近邻集合里最远的那条"。

    单条结果测不出这一位（`docs[0]` 与 `docs[-1]` 同一个），所以必须给两条不同的正文。
    """
    import asyncio

    near = SimpleNamespace(distance=0.01, value_json='{"answer":"near"}')
    far = SimpleNamespace(distance=0.02, value_json='{"answer":"far"}')

    class _TwoDocs(_FakeSearch):
        async def search(self, query, query_params=None):
            self.searches.append({"query": query})
            return SimpleNamespace(docs=[near, far])

    cache, _ = _backend()
    cache._started = True
    cache._index_ready = True
    cache._client = _FakeClient(ft_obj=_TwoDocs())
    hit = asyncio.run(
        cache._search_l2(tenant_id="t1", vector=[0.1] * _DIM, epoch=0, kb_versions=None, gray_pct=0.0)
    )
    assert hit is not None and hit.value == {"answer": "near"}, hit


class _RecordingClient(_FakeClient):
    """补上 `delete` / `set` 两个直接命令的 Recorder：失效与负缓存路径不走 pipeline。"""

    def __init__(self, epoch_value: Any = None) -> None:
        super().__init__()
        self.calls: list[tuple] = []
        self._epoch_value = epoch_value

    async def get(self, key: str) -> Any:
        self.calls.append(("get", key))
        if ":epoch:" in key:
            return self._epoch_value
        return None

    async def delete(self, *keys: str) -> int:
        """真实 async 客户端上 DELETE 是协程（pipeline 里的才是同步登记）。"""
        self.calls.append(("delete", *keys))
        return len(keys)

    async def set(self, key: str, value: Any, **kwargs: Any) -> None:
        self.calls.append(("set", key, value))

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        self.calls.append(("aclose",))


def test_backend_identity_and_scope_guards_are_part_of_the_contract():
    """三处"看起来没人读"的常量位，其实都在契约上：`enabled`、scope 守卫、未解析模型名。

    - `enabled` 是应用侧区分"真后端 / 空后端"的唯一布尔位（`test_cache_config` 反过来断言
      disabled 后端是 False），把它改成 False 会让 valkey 后端被当成没装。
    - scope 空值/含分隔符必须拒（scope 进 TAG 与索引名）。
    - 配置没给模型名时用 `unresolved` 占位，**不许是空串**——空串会让命名空间少一段，
      不同模型互相复用索引（与 §11 第 38 行那次撞车同一族）。
    """
    cfg = CacheConfig(
        backend="valkey",
        valkey_url="redis://localhost:6379/0",
        vector_dim=_DIM,
        embedding_model="mock",
    )
    cache, _ = _backend()
    assert cache.enabled is True and ValkeySemanticCache.enabled is True

    with pytest.raises(CacheConfigError, match="scope 非法"):
        ValkeySemanticCache(cfg, "")
    with pytest.raises(CacheConfigError, match="scope 非法"):
        ValkeySemanticCache(cfg, f"a{_TAG_SEPARATOR}b")

    blank_model = CacheConfig(
        backend="valkey",
        valkey_url="redis://localhost:6379/0",
        vector_dim=_DIM,
        embedding_model="",
    )
    cache3 = ValkeySemanticCache(blank_model, "agent_server")
    assert cache3._model == "unresolved"
    assert "unresolved" in cache3._ns and "unresolved" in cache3._index


def test_dim_one_is_a_known_dim_on_both_paths():
    """`_dim > 0` 写成 `> 1` 会把 1 维向量判成"维度未知"——1 维是合法值（测试与调试都用它）。"""
    import asyncio

    cache, fake = _backend()
    cache._started = True
    cache._dim = 1
    cache._model = "mock"
    cache._rebuild_namespace()
    asyncio.run(cache.get(tenant_id="t1", intent="refund", rewritten_query="q", embedding=[0.5]))
    assert fake.search.searches != [], "dim=1 必须照常走 L2"

    cache2, fake2 = _backend()
    cache2._started = True
    cache2._dim = 1
    cache2._index_ready = True
    asyncio.run(
        cache2._write_positive(
            keys=cache2._keys("t1", "k", 0),
            value_json="{}",
            vector=[0.5],
            tenant_id="t1",
            intent="refund",
            rewritten_query="q",
            kb_sig="kb",
            gray_tag="0.0",
            epoch=0,
            ttl=60,
            l2_ttl=60,
        )
    )
    ops = [op for op, _a, _kw in fake2.pipeline_obj.ops]
    assert "hset" in ops and "expire" in ops, ops


def test_l2_hit_is_recorded_only_when_a_documentation_is_returned():
    """`if hit is not None` 取反后，未命中也会被记成 l2_hit ⇒ 命中率读数直接失真。"""
    import asyncio

    doc = SimpleNamespace(distance=0.0, value_json='{"answer":"x"}')

    cache, _ = _backend()
    cache._started = True
    cache._index_ready = True
    cache._client = _FakeClient(result=SimpleNamespace(docs=[doc]))
    hit = asyncio.run(
        cache._search_l2(tenant_id="t1", vector=[0.1] * _DIM, epoch=0, kb_versions=None, gray_pct=0.0)
    )
    assert hit is not None
    assert cache.get_stats().get("l2_hit", 0) == 0, "_search_l2 自己不记命中，由 get() 记"

    cache2, _ = _backend()
    cache2._started = True
    cache2._index_ready = True
    cache2._client = _FakeClient(result=SimpleNamespace(docs=[doc]))
    hit2 = asyncio.run(cache2.get(tenant_id="t1", intent="refund", rewritten_query="q", embedding=[0.1] * _DIM))
    assert hit2 is not None and hit2.layer == "l2"
    assert cache2.get_stats()["l2_hit"] == 1

    cache3, _ = _backend()
    cache3._started = True
    cache3._index_ready = True
    cache3._client = _FakeClient(result=SimpleNamespace(docs=[]))
    hit3 = asyncio.run(cache3.get(tenant_id="t1", intent="refund", rewritten_query="q", embedding=[0.1] * _DIM))
    assert hit3 is None
    assert cache3.get_stats().get("l2_hit", 0) == 0


class _SlottedDoc:
    """只有 `__slots__` 的文档对象：没有 `__dict__` 可兜底，属性形状就是唯一形状。"""

    __slots__ = ("distance", "value_json")

    def __init__(self, distance: float, value_json: str) -> None:
        self.distance = distance
        self.value_json = value_json


def test_l2_reads_attributes_when_the_object_has_no_dict():
    """结果对象的属性 / `__dict__` 两级取值都要单独走通（valkey-py 两种形状都出现过）。

    把 `distance is None` 取反，属性有值的对象也会被推去走 `__dict__` 兜底，
    对 `_SlottedDoc` 就取到 None ⇒ `float(None)` ⇒ 永久 miss（命中率掉光但不报错）。
    """
    import asyncio

    for doc, expect_value in (
        (_SlottedDoc(0.01, '{"answer":"slotted"}'), {"answer": "slotted"}),
        (SimpleNamespace(**{"distance": 0.02, "value_json": '{"answer":"dicted"}'}), {"answer": "dicted"}),
    ):
        cache, _ = _backend()
        cache._started = True
        cache._index_ready = True
        cache._client = _FakeClient(result=SimpleNamespace(docs=[doc]))
        hit = asyncio.run(
            cache._search_l2(tenant_id="t1", vector=[0.1] * _DIM, epoch=0, kb_versions=None, gray_pct=0.0)
        )
        assert hit is not None and hit.value == expect_value, doc


def test_index_info_failure_that_is_not_response_error_counts_an_error_only():
    """`FT.INFO` 抛非 ResponseError 的 ValkeyError：返回 False、只记 `error`、不建索引也不进退避。

    这条区分的是"搜索模块不存在（该建索引）"与"连接/协议故障（不该白跑一次 FT.CREATE）"。
    """
    import asyncio

    class _InfoValkeyError(_FakeSearch):
        def __init__(self) -> None:
            super().__init__()
            self.create_calls = 0

        async def info(self) -> dict:
            raise ValkeyError("connection reset by peer")

        async def create_index(self, fields, definition=None):
            self.create_calls += 1
            return True

    spy = _InfoValkeyError()
    cache, _ = _backend()
    cache._client = _FakeClient(ft_obj=spy)
    assert asyncio.run(cache._ensure_index()) is False
    stats = cache.get_stats()
    assert stats["error"] == 1
    assert stats["l2_unavailable"] == 0, "连接故障不该算成「L2 不可用」"
    assert spy.create_calls == 0, "信息探测失败时不许接着建索引"
    assert cache._index_ready is False


@pytest.mark.asyncio
async def test_invalidate_and_negative_write_act_when_epoch_exists():
    """epoch 读到值时两条路径必须真的发出命令：`epoch is None` 取反会让它们永远沉默。"""
    cache, _ = _backend()
    client = _RecordingClient(epoch_value="3")
    cache._client = client
    cache._started = True
    await cache.invalidate(tenant_id="t1", intent="refund", rewritten_query="q")
    deletes = [c for c in client.calls if c[0] == "delete"]
    assert deletes and ":3:" in deletes[0][1], client.calls
    assert cache.get_stats()["error"] == 0

    cache2, _ = _backend()
    client2 = _RecordingClient(epoch_value="7")
    cache2._client = client2
    cache2._started = True
    cache2._ensure_worker()
    await cache2.set_negative(tenant_id="t1", intent="refund", rewritten_query="q")
    for _ in range(20):
        await asyncio.sleep(0)
    kinds = [c[0] for c in client2.calls]
    assert "delete" in kinds and "set" in kinds, client2.calls
    await cache2.aclose()


@pytest.mark.asyncio
async def test_invalidate_and_negative_write_stay_silent_without_epoch():
    """反向：epoch 读失败（None）时**一条命令都不许发**——否则会写到旧 epoch 的键上。"""
    cache, _ = _backend()
    cache._client = _RecordingClient(epoch_value=None)  # 键不存在 → epoch 0
    cache._started = True
    await cache.invalidate(tenant_id="t1", intent="refund", rewritten_query="q")
    assert [c for c in cache._client.calls if c[0] == "delete"], "epoch 0 是合法值，正常应发删除"

    boom = _FakeClient()

    async def _raise(_key: str) -> Any:
        raise ValkeyError("connection reset")

    boom.get = _raise  # type: ignore[assignment]
    cache2, _ = _backend()
    cache2._client = boom
    cache2._started = True
    await cache2.invalidate(tenant_id="t1", intent="refund", rewritten_query="q")
    assert cache2.get_stats()["error"] == 1


@pytest.mark.asyncio
async def test_aclose_tolerates_queue_without_worker():
    """`_queue is not None and _worker is not None` 的合取取反会在只有队列没有 worker 时崩。

    这条正是"优雅关闭路径自己把进程搞炸"的形状：关闭发生在退出期，崩了也没人看见，
    只留下"缓存偶尔没排空"的现象。
    """
    cache, _ = _backend()
    cache._queue = asyncio.Queue()
    cache._worker = None
    closed: list[str] = []

    class _C(_FakeClient):
        async def aclose(self) -> None:
            closed.append("aclose")

    cache._client = _C()
    await cache.aclose()
    assert closed == ["aclose"]
    assert cache._closing is True


class _FrozenClock:
    """把后端模块里 `time` 这个名字换成固定读数（不动 stdlib；monkeypatch 退出时还原）。

    冷却/退避"到期那一瞬归哪一侧"只有钉死时钟才测得出来：真 `monotonic()` 的值永远追不上
    一个已经写死的 `_next_retry`，用例只能退化成"提前 30s / 滞后 1s"两个远端。
    其余属性回落真 time 模块——替身要像真的协作者，不能只长成我要的那两个方法。
    """

    def __init__(self, now: float) -> None:
        self._now = now

    def monotonic(self) -> float:
        return self._now

    def __getattr__(self, name: str) -> Any:
        return getattr(time, name)


def test_cooldown_expiry_instant_belongs_to_the_retry_side(monkeypatch):
    """embedder 冷却与索引退避在 `now == next_retry` 这一瞬都必须放行重试。

    两处 `<` 写成 `<=` 都不会报错，代价是每次刚好到期再多等一个 tick：embedder 那条链上
    线上表现是"模型已经能加载了，L2 还是降级"，而降级原因停在 embedder_unavailable 不消失。
    """
    cache, _ = _backend()
    cache._embedder = None
    loaded: list[str] = []

    async def _spy() -> None:
        loaded.append("load")

    cache._load_embedder = _spy  # type: ignore[method-assign]
    frozen = time.monotonic()
    cache._embedder_next_retry = frozen
    monkeypatch.setattr(valkey_backend, "time", _FrozenClock(frozen))
    assert asyncio.run(cache._ensure_embedder()) is None
    assert loaded == ["load"], "刚好到期的这一瞬该去加载，不该再等一轮"

    class _InfoOnce(_FakeSearch):
        def __init__(self) -> None:
            super().__init__()
            self.info_calls = 0

        async def info(self) -> dict:
            self.info_calls += 1
            return {"num_docs": 0}

    spy = _InfoOnce()
    cache2, _ = _backend()
    cache2._client = _FakeClient(ft_obj=spy)
    cache2._index_next_retry = frozen
    assert asyncio.run(cache2._ensure_index()) is True
    assert spy.info_calls == 1, "退避到期的这一瞬该真的发一次 FT.INFO"


def test_explicit_embedding_is_length_checked_all_the_way_down_to_dim_one():
    """`self._dim > 0` 的下界是 1 不是 2：dim=1 是合法配置，写成 `> 1` 会让它整段跳过长度校验。

    跳过之后显式传入的错误长度会原样落进索引（建索引时 DIM=1 却塞进 2 维向量），
    表现是 L2 查询侧报维度不匹配，而不是写入侧当场拒绝。
    """
    cache, _ = _backend()
    cache._dim = 1
    assert asyncio.run(cache._resolve_embedding([0.2, 0.3], "q")) is None
    assert cache.get_stats()["embedding_error"] == 1

    assert asyncio.run(cache._resolve_embedding([0.7], "q")) == [0.7]
    assert cache.get_stats()["embedding_error"] == 1, "长度匹配不该记错误"


class _CountingEmbedder:
    dim = 1

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def aembed(self, texts: list[str]) -> list[list[float]]:
        self.calls.extend(texts)
        return [[0.5] for _ in texts]


def test_unknown_dim_stops_before_the_embedder_and_dim_one_reaches_it():
    """`self._dim <= 0` 的三个邻位对应两种方向相反的故障，所以两侧都得钉。

    写成 `< 0` 或 `<= -1`：dim 没解析出来时照样去调 embedder，于是每次读都走一遍
    模型加载线程池（启动路径的代价被搬进热路径）。写成 `<= 1`：dim=1 这个合法值被当成
    未知，L2 整段静默关闭，而读数上只看得到"命中率低"。
    """
    embedder = _CountingEmbedder()

    cache, _ = _backend()
    cache._dim = 0
    cache._embedder = embedder
    assert asyncio.run(cache._resolve_embedding(None, "q")) is None
    assert embedder.calls == [], "dim 未知时不许去调 embedder"
    assert cache.get_stats()["embedding_error"] == 0

    cache2, _ = _backend()
    cache2._dim = 1
    cache2._embedder = embedder
    assert asyncio.run(cache2._resolve_embedding(None, "q")) == [0.5]
    assert embedder.calls == ["q"], "dim=1 是合法维度，该真的去嵌入"
    assert cache2.get_stats()["embedding_error"] == 0


def test_a_pre_existing_index_is_reported_ready_without_creating():
    """索引已在（上一代进程建的）：`FT.INFO` 成功那条出路既要标内部标志，也要**回报** True。

    现有用例都直接设 `_index_ready = True` 绕开这里，所以只把 `return True` 变异成 False
    时没有一条会红；线上表现是"索引明明在，L2 永远不命中"——静默的能力丧失，没有错误计数。
    """

    class _InfoOk(_FakeSearch):
        def __init__(self) -> None:
            super().__init__()
            self.info_calls = 0
            self.create_calls = 0

        async def info(self) -> dict:
            self.info_calls += 1
            return {"num_docs": 7}

        async def create_index(self, fields, definition=None):
            self.create_calls += 1
            return True

    spy = _InfoOk()
    cache, _ = _backend()
    cache._client = _FakeClient(ft_obj=spy)
    assert asyncio.run(cache._ensure_index()) is True
    assert cache._index_ready is True
    assert (spy.info_calls, spy.create_calls) == (1, 0), "已就绪不该再发 FT.CREATE"


def test_the_index_lock_makes_the_second_waiter_reuse_the_result():
    """双检锁的内层判据不是装饰：内层 `if self._index_ready` 删掉后每次并发首读都多发一条命令。

    要并发才杀得动这一刀——单协程里 `_index_ready` 永远不会在"外层查过之后、拿到锁之前"变 True。
    表现不是崩溃而是 BUSYINDEX / 重复建索引，读数上只有 error 计数涨一点，属于最难归因的那一类。
    """

    class _SlowCreate(_FakeSearch):
        def __init__(self) -> None:
            super().__init__()
            self.info_calls = 0
            self.create_calls = 0
            self.gate = asyncio.Event()

        async def info(self) -> dict:
            self.info_calls += 1
            if self.info_calls == 1:
                raise ResponseError("Unknown Index name")
            return {"num_docs": 0}

        async def create_index(self, fields, definition=None):
            self.create_calls += 1
            await self.gate.wait()  # 停在建索引中途，让第二个协程有机会堆到锁上
            return True

    spy = _SlowCreate()
    cache, _ = _backend()
    cache._client = _FakeClient(ft_obj=spy)

    async def _main() -> list[bool]:
        first = asyncio.ensure_future(cache._ensure_index())
        await asyncio.sleep(0)  # first 跑到 gate.wait()，锁仍在它手上
        second = asyncio.ensure_future(cache._ensure_index())
        await asyncio.sleep(0)  # second 走到 `async with self._index_lock` 上排队
        spy.gate.set()
        return await asyncio.gather(first, second)

    assert asyncio.run(_main()) == [True, True]
    assert (spy.info_calls, spy.create_calls) == (1, 1), "第二个等待者不许再发 FT.INFO / FT.CREATE"
    assert cache._index_ready is True
