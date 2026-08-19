"""CacheStats 单元测试。"""

from agent_core.cache import CacheStats


class TestCacheStats:
    def test_empty_snapshot(self):
        stats = CacheStats()
        snap = stats.snapshot()
        assert snap["hit_rate"] == 0.0
        assert snap.get("total", 0) == 0

    def test_record_single_hit(self):
        stats = CacheStats()
        stats.record("l1_hit")
        snap = stats.snapshot()
        assert snap["l1_hit"] == 1
        assert snap["total"] == 1
        assert snap["hit_rate"] == 1.0

    def test_record_miss(self):
        stats = CacheStats()
        stats.record("miss")
        snap = stats.snapshot()
        assert snap["miss"] == 1
        assert snap["total"] == 1
        assert snap["hit_rate"] == 0.0

    def test_mixed_records(self):
        stats = CacheStats()
        for _ in range(3):
            stats.record("l1_hit")
        for _ in range(2):
            stats.record("l2_hit")
        stats.record("null_hit")
        for _ in range(4):
            stats.record("miss")
        snap = stats.snapshot()
        assert snap["l1_hit"] == 3
        assert snap["l2_hit"] == 2
        assert snap["null_hit"] == 1
        assert snap["miss"] == 4
        assert snap["total"] == 10
        assert snap["hit_rate"] == 0.6

    def test_reset(self):
        stats = CacheStats()
        stats.record("l1_hit")
        stats.record("miss")
        stats.reset()
        snap = stats.snapshot()
        assert snap.get("total", 0) == 0
        assert snap["hit_rate"] == 0.0

    def test_hit_rate_rounding(self):
        stats = CacheStats()
        stats.record("l1_hit")
        for _ in range(3):
            stats.record("miss")
        snap = stats.snapshot()
        assert snap["hit_rate"] == 0.25
