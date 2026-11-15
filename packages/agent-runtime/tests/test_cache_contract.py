"""真 Valkey 语义缓存契约测试（需要含 Search 模块的 Valkey，推荐 valkey-bundle）。

CI 通过 service container 提供 Valkey 并设置 ``CACHE_CONTRACT_REQUIRED=1``：
此时服务不可达/缺 Search 模块即红。本地未启动 Valkey 时整模块 skip，但**不允许**
在 CI 里 skip——否则"契约没跑"会长得像通过。

覆盖：L1 精确命中 / L2 语义命中 / 阈值拒绝 / 负缓存 / TTL / 精确失效 /
命名空间失效 / 租户·scope·KB·灰度隔离 / 空租户 fail-closed / PII 写入门禁 /
索引被外部摘掉后的自愈 / 健康态。
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import time
import uuid
from urllib.parse import urlsplit

import pytest
import valkey.asyncio as valkey_asyncio
from agent_core.memory.embedder import MockEmbedder
from valkey.commands.search.query import Query
from valkey.exceptions import ValkeyError

from agent_runtime.cache.config import CacheConfig
from agent_runtime.cache.valkey_backend import ValkeySemanticCache, _is_missing_index_error, _vec_bytes

_URL = os.getenv("VALKEY_URL", "redis://127.0.0.1:6379/0")
_REQUIRED = os.getenv("CACHE_CONTRACT_REQUIRED", "").strip() == "1"
_DIM = 8
_V1 = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
_V_ORTH = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
# 隔离类用例的读侧一律用这句：与写入时的措辞不同 ⇒ L1 精确键必然不命中，
# "读不到"才只能由 L2 的 TAG 分区解释。用原句会让 L1 短路，正/反两组断言都变成
# 在测 L1（2026-10-26 真机首跑时 L2 整条是坏的，这六条照样全绿——就是没测到 L2 的证据）。
_L2_PROBE_Q = "换一种说法问退款"


def _tcp_reachable(url: str) -> tuple[bool, str]:
    parts = urlsplit(url)
    if parts.scheme not in ("redis", "rediss"):
        return False, f"仅支持 TCP URL 的契约测试，当前 scheme={parts.scheme!r}"
    host = parts.hostname or "127.0.0.1"
    port = parts.port or 6379
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True, ""
    except OSError as exc:
        return False, f"{host}:{port} 不可达: {exc}"


_REACHABLE, _UNREACHABLE_REASON = _tcp_reachable(_URL)
if not _REACHABLE and not _REQUIRED:
    pytest.skip(
        f"Valkey 契约测试跳过（{_UNREACHABLE_REASON}）。"
        "启动：docker compose up -d valkey；CI 中必须设置 CACHE_CONTRACT_REQUIRED=1",
        allow_module_level=True,
    )


def _decode(value):
    return value.decode("utf-8") if isinstance(value, bytes) else value


@pytest.fixture
def prefix() -> str:
    return f"cachetest:{uuid.uuid4().hex[:10]}"


@pytest.fixture
def embedder() -> MockEmbedder:
    return MockEmbedder(dim=_DIM)


@pytest.fixture
async def admin():
    client = valkey_asyncio.Valkey.from_url(_URL, decode_responses=True, socket_connect_timeout=1.0, socket_timeout=2.0)
    if not _REACHABLE:
        raise RuntimeError(f"Valkey 契约测试要求真实服务，但{_UNREACHABLE_REASON}")
    try:
        try:
            await client.ping()
        except (ValkeyError, OSError) as exc:
            raise RuntimeError(f"Valkey PING 失败（{_URL}）: {exc}") from exc
        modules = await client.module_list()
        names = {_decode(m.get("name") if isinstance(m, dict) else None) for m in modules}
        names.discard(None)
        if "search" not in names:
            msg = f"Valkey 缺 Search 模块（module list={sorted(names)}）；请使用 valkey-bundle 镜像"
            if _REQUIRED:
                raise RuntimeError(msg)
            pytest.skip(msg)
        yield client
    finally:
        await client.aclose()


@pytest.fixture
async def cache_factory(prefix, embedder, admin):
    created: list[tuple[CacheConfig, ValkeySemanticCache]] = []

    async def make(scope: str = "contract", startup: bool = True, **overrides) -> ValkeySemanticCache:
        """startup=False 给"先有存量哈希、后建索引"的用例：startup() 会把索引先建好，
        那样就测不到首次扫描会不会收编存量数据（索引改名的前提，见下面的用回这条的用例）。"""
        options = {
            "enabled": True,
            "backend": "valkey",
            "valkey_url": _URL,
            "l1_ttl_seconds": 60,
            "l2_ttl_seconds": 60,
            "null_ttl_seconds": 30,
            "threshold": 0.05,
            "federation_threshold": 0.08,
            "vector_dim": _DIM,
            "embedding_model": "mock",
            "connect_timeout_ms": 500,
            "command_timeout_ms": 2000,
            "write_queue_max": 100,
            "write_flush_timeout_seconds": 5.0,
            "key_prefix": prefix,
        }
        options.update(overrides)
        cfg = CacheConfig(**options)
        backend = ValkeySemanticCache(cfg, scope, embedder=embedder)
        if startup:
            await backend.startup()
        created.append((cfg, backend))
        return backend

    yield make

    for cfg, backend in created:
        await backend.flush()
        await backend.aclose()
        index = cfg.index_name(backend._scope, backend._model, backend._dim)
        try:
            await admin.ft(index).dropindex(delete_documents=True)
        except ValkeyError:
            pass
    async for key in admin.scan_iter(match=f"{prefix}*"):
        await admin.delete(key)


@pytest.mark.asyncio
async def test_l1_exact_hit(cache_factory):
    cache = await cache_factory()
    await cache.set(
        tenant_id="t-l1",
        intent="refund",
        rewritten_query="如何退款",
        value={"answer": "A"},
        embedding=_V1,
    )
    await cache.flush()
    hit = await cache.get(tenant_id="t-l1", intent="refund", rewritten_query="如何退款", embedding=_V1)
    assert hit is not None and hit.layer == "l1" and hit.value["answer"] == "A"
    assert cache.get_stats()["l1_hit"] == 1


@pytest.mark.asyncio
async def test_l2_semantic_hit_and_threshold(cache_factory):
    cache = await cache_factory()
    await cache.set(
        tenant_id="t-l2",
        intent="refund",
        rewritten_query="如何退款",
        value={"answer": "A"},
        embedding=_V1,
    )
    await cache.flush()

    hit = await cache.get(tenant_id="t-l2", intent="refund", rewritten_query="退款流程是什么", embedding=_V1)
    assert hit is not None and hit.layer == "l2"
    assert hit.distance is not None and hit.distance <= 0.05

    # 措辞必须与写入时**不同**：L1 是 `sha256(intent|rewritten_query|…)` 的精确键，
    # 用原句会让 L1 直接命中并短路，这条就变成"测了 L1"而不是"L2 按距离拒绝"。
    # （2026-10-26 真机首跑就是被这一点抓红的：返回的是 layer='l1' 的命中。）
    miss = await cache.get(tenant_id="t-l2", intent="refund", rewritten_query="退款进度查询", embedding=_V_ORTH)
    assert miss is None  # 正交向量距离 1.0 超过阈值 0.05，必须按未命中处理
    assert cache.get_stats()["miss"] >= 1


@pytest.mark.asyncio
async def test_negative_cache(cache_factory):
    cache = await cache_factory()
    await cache.set_negative(tenant_id="t-null", intent="refund", rewritten_query="无答案问题")
    await cache.flush()
    hit = await cache.get(tenant_id="t-null", intent="refund", rewritten_query="无答案问题", embedding=_V1)
    assert hit is not None and hit.layer == "null" and hit.value == {}
    assert cache.get_stats()["null_hit"] == 1


@pytest.mark.asyncio
async def test_explicit_ttl_expires_both_layers(cache_factory):
    cache = await cache_factory()
    await cache.set(
        tenant_id="t-ttl",
        intent="refund",
        rewritten_query="短TTL",
        value={"answer": "A"},
        embedding=_V1,
        ttl_seconds=1,
    )
    await cache.flush()
    assert await cache.get(tenant_id="t-ttl", intent="refund", rewritten_query="短TTL", embedding=_V1)
    await asyncio.sleep(1.2)
    assert await cache.get(tenant_id="t-ttl", intent="refund", rewritten_query="短TTL", embedding=_V1) is None


@pytest.mark.asyncio
async def test_exact_invalidate(cache_factory):
    cache = await cache_factory()
    await cache.set(tenant_id="t-inv", intent="refund", rewritten_query="q", value={"answer": "A"}, embedding=_V1)
    await cache.flush()
    await cache.invalidate(tenant_id="t-inv", intent="refund", rewritten_query="q")
    assert await cache.get(tenant_id="t-inv", intent="refund", rewritten_query="q", embedding=_V1) is None


@pytest.mark.asyncio
async def test_namespace_invalidate_by_epoch(cache_factory):
    cache = await cache_factory()
    await cache.set(tenant_id="t-ns", intent="refund", rewritten_query="q", value={"answer": "A"}, embedding=_V1)
    await cache.flush()
    await cache.invalidate_namespace(tenant_id="t-ns")
    assert await cache.get(tenant_id="t-ns", intent="refund", rewritten_query="q", embedding=_V1) is None


@pytest.mark.asyncio
async def test_tenant_isolation(cache_factory):
    cache = await cache_factory()
    await cache.set(tenant_id="tenant-a", intent="refund", rewritten_query="q", value={"answer": "A"}, embedding=_V1)
    await cache.flush()
    assert await cache.get(tenant_id="tenant-b", intent="refund", rewritten_query=_L2_PROBE_Q, embedding=_V1) is None
    baseline = await cache.get(tenant_id="tenant-a", intent="refund", rewritten_query=_L2_PROBE_Q, embedding=_V1)
    assert baseline is not None and baseline.layer == "l2", "同租户必须经 L2 读到，否则上面的 None 说明不了隔离"
    # L1 面另守一刀：**同一句**换租户也必须读不到。上面两条都把措辞换了（为了强制走 L2），
    # 于是"租户从 L1 键里被摘掉"这个变异两头都不红——真机反证 m09 实测 19 条全绿，
    # 这条就是补那一格空缺的（去掉它，m09 又没人守）。
    assert await cache.get(tenant_id="tenant-b", intent="refund", rewritten_query="q", embedding=_V1) is None


@pytest.mark.asyncio
async def test_tenant_isolation_is_case_sensitive(cache_factory):
    cache = await cache_factory()
    await cache.set(tenant_id="Tenant-A", intent="refund", rewritten_query="q", value={"answer": "A"}, embedding=_V1)
    await cache.flush()
    assert await cache.get(tenant_id="tenant-a", intent="refund", rewritten_query=_L2_PROBE_Q, embedding=_V1) is None
    baseline = await cache.get(tenant_id="Tenant-A", intent="refund", rewritten_query=_L2_PROBE_Q, embedding=_V1)
    assert baseline is not None and baseline.layer == "l2"


@pytest.mark.asyncio
async def test_pipe_in_tenant_cannot_inject_or_filter(cache_factory):
    cache = await cache_factory()
    await cache.set(tenant_id="victim", intent="refund", rewritten_query="q", value={"answer": "A"}, embedding=_V1)
    await cache.flush()
    assert await cache.get(tenant_id="victim|attacker", intent="refund", rewritten_query=_L2_PROBE_Q, embedding=_V1) is None
    baseline = await cache.get(tenant_id="victim", intent="refund", rewritten_query=_L2_PROBE_Q, embedding=_V1)
    assert baseline is not None and baseline.layer == "l2"


@pytest.mark.asyncio
async def test_scope_isolation(cache_factory):
    app_cache = await cache_factory(scope="contract-a")
    fed_cache = await cache_factory(scope="contract-b")
    await app_cache.set(tenant_id="t-scope", intent="refund", rewritten_query="q", value={"answer": "A"}, embedding=_V1)
    await app_cache.flush()
    assert await fed_cache.get(tenant_id="t-scope", intent="refund", rewritten_query=_L2_PROBE_Q, embedding=_V1) is None
    baseline = await app_cache.get(tenant_id="t-scope", intent="refund", rewritten_query=_L2_PROBE_Q, embedding=_V1)
    assert baseline is not None and baseline.layer == "l2"


@pytest.mark.asyncio
async def test_kb_version_isolation(cache_factory):
    cache = await cache_factory()
    await cache.set(
        tenant_id="t-kb",
        intent="refund",
        rewritten_query="q",
        value={"answer": "A"},
        kb_versions={"kb": "v1"},
        embedding=_V1,
    )
    await cache.flush()
    assert (
        await cache.get(
            tenant_id="t-kb",
            intent="refund",
            rewritten_query=_L2_PROBE_Q,
            kb_versions={"kb": "v2"},
            embedding=_V1,
        )
        is None
    )
    baseline = await cache.get(
        tenant_id="t-kb",
        intent="refund",
        rewritten_query=_L2_PROBE_Q,
        kb_versions={"kb": "v1"},
        embedding=_V1,
    )
    assert baseline is not None and baseline.layer == "l2"


@pytest.mark.asyncio
async def test_gray_pct_isolation(cache_factory):
    cache = await cache_factory()
    await cache.set(
        tenant_id="t-gray",
        intent="refund",
        rewritten_query="q",
        value={"answer": "A"},
        gray_pct=0.0,
        embedding=_V1,
    )
    await cache.flush()
    assert (
        await cache.get(
            tenant_id="t-gray",
            intent="refund",
            rewritten_query=_L2_PROBE_Q,
            gray_pct=0.5,
            embedding=_V1,
        )
        is None
    )
    baseline = await cache.get(
        tenant_id="t-gray", intent="refund", rewritten_query=_L2_PROBE_Q, gray_pct=0.0, embedding=_V1
    )
    assert baseline is not None and baseline.layer == "l2"


@pytest.mark.asyncio
async def test_empty_tenant_fail_closed(cache_factory):
    cache = await cache_factory()
    assert await cache.get(tenant_id="", intent="refund", rewritten_query="q", embedding=_V1) is None
    await cache.set(tenant_id="", intent="refund", rewritten_query="q", value={"answer": "A"}, embedding=_V1)
    await cache.flush()
    assert cache.get_stats()["skipped_no_tenant"] == 2


@pytest.mark.asyncio
async def test_pii_answer_is_never_written(cache_factory):
    """真 Valkey 侧确认 PII 写入门禁：既不入 L1/L2，也不留下可命中的副本。"""
    cache = await cache_factory()
    await cache.set(
        tenant_id="t-pii",
        intent="refund",
        rewritten_query="如何退款",
        value={"answer": "联系 13800138000"},
        embedding=_V1,
    )
    await cache.flush()
    assert cache.get_stats()["skipped_pii"] == 1
    assert await cache.get(tenant_id="t-pii", intent="refund", rewritten_query="如何退款", embedding=_V1) is None


@pytest.mark.asyncio
async def test_health_reports_ready_and_index(cache_factory):
    cache = await cache_factory()
    health = await cache.health()
    assert health.backend == "valkey"
    assert health.ready is True
    assert health.index and health.index.startswith("semantic_cache_idx_")


@pytest.mark.asyncio
async def test_dropped_index_self_heals_on_next_read(cache_factory):
    """索引被外部摘掉（运维按 ADR §9 的建议跑 FT.DROPINDEX）后，L2 必须自愈，
    不能永久静默 miss 而健康态还报 ready=true。

    这条同时核对服务器"索引不存在"的**真实措辞**：wire 层用的是我抄进假客户端的
    字符串，不算证据；不匹配时失败信息直接给出服务器原文。
    """
    cache = await cache_factory()
    await cache.set(
        tenant_id="t-drop",
        intent="refund",
        rewritten_query="如何退款",
        value={"answer": "A"},
        embedding=_V1,
    )
    await cache.flush()
    hit = await cache.get(tenant_id="t-drop", intent="refund", rewritten_query="退款流程是什么", embedding=_V1)
    assert hit is not None and hit.layer == "l2"

    # 不带 DD：只删索引，保留哈希正文。刻意不用 `ft().dropindex()`：valkey-py 6.2.0 在
    # delete_documents=False 时把空串当第三个参数发出去（`FT.DROPINDEX <idx> ""`），
    # 服务器直接报 `wrong number of arguments for 'FT.DROPINDEX' command`（2026-10-26 真机读数）；
    # 只有 delete_documents=True 那条路径能走通。裸命令绕开这个客户端缺陷。
    await cache._client.execute_command("FT.DROPINDEX", cache._index)

    with pytest.raises(ValkeyError) as exc_info:
        await cache._client.ft(cache._index).search(Query("@tenant:{t-drop}"))
    observed = str(exc_info.value)
    assert _is_missing_index_error(observed), f"未识别的服务器措辞，需补进 _is_missing_index_error：{observed!r}"

    assert (
        await cache._search_l2(
            tenant_id="t-drop",
            vector=_V1,
            epoch=0,
            kb_versions=None,
            gray_pct=0.0,
        )
        is None
    )
    assert cache._index_ready is False
    assert cache.get_stats()["index_missing"] == 1

    assert await cache._ensure_index() is True
    await cache._client.ft(cache._index).info()


@pytest.mark.asyncio
async def test_star_suffix_tenant_cannot_prefix_match_other_tenant(cache_factory):
    """星号结尾的租户被 fail-closed，且这条判据的**理由**在同一次真机取数里被钉住。

    前身是"我们发了转义所以安全"——真机（bundle 9.1.2 / search 1.2.1）实测否掉了它：
    反斜杠在 TAG 里不关闭通配，`{acme\\*}` 与 `{acme*}` 一样把 `acme` 前缀命中。
    所以这里分两步：先用裸命令把引擎行为取下来（转义无效＝事实），再断言后端**根本不发**
    这个查询（fail-closed＝我们的处置）。两步合在一起才叫证据：只有后者红了不知道为什么，
    只有前者红了说明没人拦。
    """
    cache = await cache_factory()
    await cache.set(
        tenant_id="acme",
        intent="refund",
        rewritten_query="如何退款",
        value={"answer": "A"},
        embedding=_V1,
    )
    await cache.flush()

    # ① 引擎事实：裸查询两种写法都命中 acme ⇒ 转义不构成防线（不依赖被测代码）
    raw_prefix = await cache._client.execute_command(
        "FT.SEARCH", cache._index, "@tenant:{acme*}", "NOCONTENT"
    )
    raw_escaped = await cache._client.execute_command(
        "FT.SEARCH", cache._index, r"@tenant:{acme\*}", "NOCONTENT"
    )
    assert int(raw_prefix[0]) >= 1, raw_prefix
    assert int(raw_escaped[0]) == int(raw_prefix[0]), (
        f"转义若真的关闭通配，两者应不同；实测相同 ⇒ fail-closed 是唯一可行处置（{raw_escaped}）"
    )

    # ② 处置：名为 acme* 的租户读不到任何东西，且原因单独记账
    assert (
        await cache.get(tenant_id="acme*", intent="refund", rewritten_query="退款流程是什么", embedding=_V1)
        is None
    )
    assert cache.get_stats()["skipped_unsafe_tag"] >= 1
    # 反证基线：同租户照常可读，说明上面那次 miss 不是"整个 L2 都坏了"
    ok = await cache.get(tenant_id="acme", intent="refund", rewritten_query="退款流程是什么", embedding=_V1)
    assert ok is not None and ok.layer == "l2"


async def _num_docs(cache: ValkeySemanticCache) -> int:
    return int((await cache._client.ft(cache._index).info())["num_docs"])


@pytest.mark.asyncio
async def test_delete_and_expiry_shrink_the_index(cache_factory):
    """TTL 与精确失效必须真的把条目从索引里摘掉，而不是留 ghost 占 KNN 名额。

    这条依赖链已在源码核实，因此**不需要**在部署清单里开 `notify-keyspace-events`：
    - valkey-search 订阅 `GENERIC|EXPIRED|EVICTED`（`src/attribute_data_type.h:67-69`）；
    - valkey core 先派发给模块、再看配置开关（`src/notify.c:125` 早于 `:132` 的
      `server.notify_keyspace_events` 门），注释原文 "This bypasses the notifications
      configuration"。
    结论此前只有文档转述级依据；本条把它钉在真机上（本机整模块 skip，CI 取实数）。
    """
    cache = await cache_factory()
    for i in range(3):
        await cache.set(
            tenant_id="t-sync",
            intent="refund",
            rewritten_query=f"q{i}",
            value={"answer": "A"},
            embedding=_V1,
            ttl_seconds=3600,
        )
    await cache.flush()
    # 写入客户端会被阻塞到各索引更新完成（docs/topics/search.md:50），所以这里的读数是确定的
    assert await _num_docs(cache) == 3

    await cache.invalidate(tenant_id="t-sync", intent="refund", rewritten_query="q1")
    assert await _num_docs(cache) == 2

    await cache.set(
        tenant_id="t-sync",
        intent="refund",
        rewritten_query="short-lived",
        value={"answer": "A"},
        embedding=_V1,
        ttl_seconds=1,
    )
    await cache.flush()
    assert await _num_docs(cache) == 3

    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        await asyncio.sleep(0.25)
        if await _num_docs(cache) == 2:
            break
    else:  # pragma: no cover - 只有真机上不收敛才会走到
        pytest.fail(
            f"过期 8s 后索引仍有 ghost：num_docs={await _num_docs(cache)}"
            "（主动过期没派发，或模块订阅没生效）"
        )


@pytest.mark.asyncio
async def test_existing_hashes_are_backfilled_when_index_is_created(cache_factory):
    """先写哈希、后建索引：存量数据必须被首次扫描收编。

    这条钉的是"改索引名 = 换索引"的前提。索引名 2026-10-26 起含 CACHE_KEY_PREFIX 的 token
    （不同前缀必须不同名），换名后老数据靠新索引的首次扫描回收入库；前提若不成立，
    改名就等于把缓存清空，而 ADR §9 当时是按"不丢数据、不需要重放写入"写的，只有推断没有读数。
    真机读数（bundle 9.1.2 / search 1.2.1）：建索引前 num_docs 取不到（索引不存在），
    `_ensure_index()` 后 num_docs 0→1、state backfill_in_progress→ready 约 0.5s。
    """
    cache = await cache_factory(startup=False)
    key = f"{cache._ns}l2:0:preexisting"
    await cache._client.hset(
        key,
        mapping={
            "tenant": "t-backfill",
            "scope": "contract",
            "kb_version": "none",
            "gray_pct": "0",
            "epoch": "0",
            "intent": "refund",
            "query_text": "如何退款",
            "value_json": json.dumps({"answer": "A"}, ensure_ascii=False),
            "query_vec": _vec_bytes(_V1),
        },
    )
    # 索引确实还不存在（这条 raise 是可达的：真机原文 "Index with name 'X' not found ..."）
    with pytest.raises(ValkeyError):
        await cache._client.ft(cache._index).info()

    assert await cache._ensure_index() is True
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if await _num_docs(cache) >= 1:
            break
        await asyncio.sleep(0.2)
    else:  # pragma: no cover - 只有真机不收编才会走到
        pytest.fail(f"首次扫描没收编存量哈希：num_docs={await _num_docs(cache)}（改名即清空缓存的前提不成立）")

    hit = await cache.get(
        tenant_id="t-backfill",
        intent="refund",
        rewritten_query="退款流程是什么",
        embedding=_V1,
    )
    assert hit is not None and hit.layer == "l2" and hit.value == {"answer": "A"}
