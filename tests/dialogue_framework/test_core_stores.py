"""JSON/Postgres Store 测试。"""


from dialogue_framework.core.stores.json_store import JsonStore
from dialogue_framework.core.tracker import Tracker


async def test_json_store_save_load(tmp_path):
    store = JsonStore(base_dir=str(tmp_path / "store"))
    tracker = Tracker(session_id="s1")
    tracker.set_slot("intent", "test")
    await store.save_tracker(tracker)
    loaded = await store.load_tracker("s1")
    assert loaded is not None
    assert loaded.session_id == "s1"
    assert loaded.get_slot("intent").value == "test"


async def test_json_store_load_missing(tmp_path):
    store = JsonStore(base_dir=str(tmp_path / "store"))
    loaded = await store.load_tracker("nonexistent")
    assert loaded is None


async def test_tracker_roundtrip():
    tracker = Tracker(session_id="s1")
    tracker.set_slot("intent", "query")
    tracker.set_slot("target", "orders")
    tracker.update("search")
    data = tracker.to_dict()
    restored = Tracker.from_dict(data)
    assert restored.session_id == "s1"
    assert restored.get_slot("intent").value == "query"
    assert restored.latest_action == "search"
