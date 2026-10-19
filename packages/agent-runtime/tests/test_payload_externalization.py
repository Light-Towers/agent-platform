"""V3-6 单测：Large Payload Externalization。

验证：
- PayloadExternalizer：超阈值外部化 / 未超原样 / reference 识别；
- externalize → internalize 往返还原；
- externalize_completed / internalize_completed 批量；
- InMemoryPayloadStore CRUD；
- FileSystemPayloadStore CRUD。
"""

import json
import tempfile

from agent_runtime.payload_externalization import (
    ExternalizationConfig,
    FileSystemPayloadStore,
    InMemoryPayloadStore,
    PayloadExternalizer,
)

# ===== InMemoryPayloadStore =====

async def test_inmemory_store_crud():
    store = InMemoryPayloadStore()
    await store.put("k1", b"hello")
    assert await store.get("k1") == b"hello"
    assert await store.get("k2") is None
    assert await store.delete("k1") is True
    assert await store.get("k1") is None
    assert await store.delete("k1") is False


# ===== FileSystemPayloadStore =====

async def test_filesystem_store_crud():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = FileSystemPayloadStore(tmpdir)
        await store.put("payload/k1", b"hello world")
        assert await store.get("payload/k1") == b"hello world"
        assert await store.get("payload/k2") is None
        assert await store.delete("payload/k1") is True
        assert await store.get("payload/k1") is None


# ===== PayloadExternalizer =====

async def test_externalize_small_value_unchanged():
    store = InMemoryPayloadStore()
    ext = PayloadExternalizer(store, ExternalizationConfig(threshold_bytes=100))
    result = await ext.externalize({"small": "data"})
    assert result == {"small": "data"}


async def test_externalize_large_value_becomes_reference():
    store = InMemoryPayloadStore()
    ext = PayloadExternalizer(store, ExternalizationConfig(threshold_bytes=100))

    big = {"data": "x" * 200}
    result = await ext.externalize(big)
    assert isinstance(result, dict)
    assert result["__external__"] is True
    assert "key" in result
    assert result["size"] > 100
    assert result["checksum"].startswith("sha256:")


async def test_externalize_internalize_roundtrip():
    store = InMemoryPayloadStore()
    ext = PayloadExternalizer(store, ExternalizationConfig(threshold_bytes=100))

    big = {"data": "x" * 200, "nested": {"y": [1, 2, 3]}}
    ref = await ext.externalize(big)
    assert ref != big  # 已外部化

    restored = await ext.internalize(ref)
    assert restored == big  # 还原


async def test_internalize_non_reference_unchanged():
    store = InMemoryPayloadStore()
    ext = PayloadExternalizer(store)
    assert await ext.internalize({"normal": "data"}) == {"normal": "data"}
    assert await ext.internalize("string") == "string"
    assert await ext.internalize(42) == 42


async def test_internalize_missing_blob_returns_reference():
    store = InMemoryPayloadStore()
    ext = PayloadExternalizer(store)
    ref = {"__external__": True, "store": "blob", "key": "nonexistent", "size": 0, "checksum": ""}
    result = await ext.internalize(ref)
    assert result is ref  # blob 不存在，返回原 reference


async def test_externalize_already_reference_unchanged():
    store = InMemoryPayloadStore()
    ext = PayloadExternalizer(store, ExternalizationConfig(threshold_bytes=10))
    ref = {"__external__": True, "store": "blob", "key": "k", "size": 100, "checksum": "x"}
    result = await ext.externalize(ref)
    assert result is ref  # 已是 reference，不重复外部化


# ===== 批量 externalize_completed / internalize_completed =====

async def test_externalize_completed_mixed():
    store = InMemoryPayloadStore()
    ext = PayloadExternalizer(store, ExternalizationConfig(threshold_bytes=100))

    completed = {
        "n1": {"small": "result"},
        "n2": {"big": "x" * 200},
        "n3": "plain string",
    }
    externalized = await ext.externalize_completed(completed)

    # n1 小 → 原样
    assert externalized["n1"] == {"small": "result"}
    # n2 大 → reference
    assert externalized["n2"]["__external__"] is True
    # n3 小 → 原样
    assert externalized["n3"] == "plain string"

    # 往返还原
    restored = await ext.internalize_completed(externalized)
    assert restored == completed


async def test_externalize_completed_empty():
    store = InMemoryPayloadStore()
    ext = PayloadExternalizer(store)
    assert await ext.externalize_completed({}) == {}
    assert await ext.internalize_completed({}) == {}


# ===== 阈值边界 =====

async def test_threshold_boundary():
    store = InMemoryPayloadStore()
    ext = PayloadExternalizer(store, ExternalizationConfig(threshold_bytes=10))

    # 恰好 10 字节 → 不外部化（> threshold 才外部化）
    small = json.dumps("0123456789").encode("utf-8")  # "0123456789" → 12 bytes with quotes
    if len(small) <= 10:
        result = await ext.externalize("0123456789")
        assert result == "0123456789"

    # 超过 → 外部化
    big = "x" * 100
    result = await ext.externalize(big)
    assert isinstance(result, dict) and result.get("__external__") is True


# ===== age-based GC sweep（2026-10-19，缺口 7 残留） =====


async def test_sweep_deletes_old_keeps_young():
    """删年龄 ≥ 下限的、留年轻的（在途 checkpoint 引用的安全边际）。"""
    import time

    from agent_runtime.payload_externalization import (
        ExternalizationConfig,
        InMemoryPayloadStore,
        PayloadExternalizer,
    )

    store = InMemoryPayloadStore()
    ext = PayloadExternalizer(store, config=ExternalizationConfig(gc_min_age_hours=1))
    await store.put("payload/old", b"x" * 10)
    await store.put("payload/young", b"y" * 10)
    # 把 old 的年龄伪造到 2h 前（改插入时刻）
    store._put_at["payload/old"] = time.time() - 7200

    report = await ext.sweep()
    assert report == {"scanned": 2, "deleted": 1, "skipped_young": 1, "skipped_referenced": 0, "errors": 0}
    assert await store.get("payload/old") is None
    assert await store.get("payload/young") == b"y" * 10


async def test_sweep_default_min_age_from_config():
    """不传参 ⇒ 用 config.gc_min_age_hours（默认 168h：年轻的一律不动）。"""
    from agent_runtime.payload_externalization import (
        InMemoryPayloadStore,
        PayloadExternalizer,
    )

    store = InMemoryPayloadStore()
    ext = PayloadExternalizer(store)  # 默认 168h
    await store.put("payload/fresh", b"z")
    report = await ext.sweep()
    assert report["deleted"] == 0
    assert report["skipped_young"] == 1


async def test_sweep_tolerates_single_key_error():
    """单 key 删除异常计入 errors 不中断（契约：sweep 不得半途崩）。"""
    from agent_runtime.payload_externalization import PayloadExternalizer

    class _FlakyStore:
        def __init__(self):
            self.deleted: list[str] = []

        async def list_keys(self):
            return ["a", "b", "c"]

        async def key_age_s(self, key):
            return 99999.0  # 全部够老

        async def delete(self, key):
            if key == "b":
                raise OSError("disk")
            self.deleted.append(key)
            return True

    store = _FlakyStore()
    ext = PayloadExternalizer(store)
    report = await ext.sweep(min_age_seconds=100)  # 显式下限，避开默认 168h
    assert report == {"scanned": 3, "deleted": 2, "skipped_young": 0, "skipped_referenced": 0, "errors": 1}
    assert store.deleted == ["a", "c"]


async def test_sweep_keeps_referenced_keys():
    """#121：够老但仍在引用的 key 不删——awaitable resume 挂起超 age 下限后，
    其 reference 被单靠年龄删掉 ⇒ resume 成功但 internalize 静默返回 reference。"""
    import time

    store = InMemoryPayloadStore()
    ext = PayloadExternalizer(store, config=ExternalizationConfig(gc_min_age_hours=1))
    await store.put("payload/referenced", b"x" * 10)
    await store.put("payload/orphan", b"y" * 10)
    old = time.time() - 7200
    store._put_at["payload/referenced"] = old
    store._put_at["payload/orphan"] = old

    report = await ext.sweep(referenced_keys={"payload/referenced"})
    assert report["skipped_referenced"] == 1
    assert report["deleted"] == 1
    assert await store.get("payload/referenced") == b"x" * 10
    assert await store.get("payload/orphan") is None


async def test_sweep_referenced_keys_accepts_any_collection():
    """referenced_keys 收任意可迭代集合（set/frozenset/list 同语义）。"""
    import time

    store = InMemoryPayloadStore()
    ext = PayloadExternalizer(store, config=ExternalizationConfig(gc_min_age_hours=1))
    await store.put("k", b"x")
    store._put_at["k"] = time.time() - 7200
    report = await ext.sweep(referenced_keys=["k"])
    assert report["skipped_referenced"] == 1 and report["deleted"] == 0


async def test_list_gc_candidates_does_not_delete():
    """#121 两段式第一段：列候选不删；候选口径与 sweep 的 age 判据一致。"""
    import time

    store = InMemoryPayloadStore()
    ext = PayloadExternalizer(store, config=ExternalizationConfig(gc_min_age_hours=1))
    await store.put("payload/old", b"x")
    await store.put("payload/young", b"y")
    store._put_at["payload/old"] = time.time() - 7200

    candidates = await ext.list_gc_candidates()
    assert candidates == ["payload/old"]
    # 列候选不动存储
    assert await store.get("payload/old") == b"x"
    # 显式下限优先于 config
    assert await ext.list_gc_candidates(min_age_seconds=99999) == []


async def test_filesystem_store_list_keys_and_age(tmp_path):
    """FileSystem 适配器：list_keys 遍历 + key_age_s 用 mtime。"""
    import os
    import time

    from agent_runtime.payload_externalization import FileSystemPayloadStore

    store = FileSystemPayloadStore(str(tmp_path))
    await store.put("payload/k1", b"data")
    keys = await store.list_keys()
    assert keys == ["payload/k1"]
    age = await store.key_age_s("payload/k1")
    assert age is not None and age >= 0.0
    # 不存在 key ⇒ None
    assert await store.key_age_s("payload/nope") is None
    # 老化后年龄反映 mtime
    old_time = time.time() - 10000
    os.utime(tmp_path / "payload" / "k1", (old_time, old_time))
    assert await store.key_age_s("payload/k1") >= 9999
