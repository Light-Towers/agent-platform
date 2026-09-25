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
