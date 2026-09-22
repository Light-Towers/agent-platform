"""Gateway guards 测试：rate_limit / output_guard / gray。

三个完全裸奔的 guard 模块补测。
"""

from __future__ import annotations

from gateway.gray import get_gray_config, is_in_gray
from gateway.output_guard import check_quality, detect_output_pii, guard_output
from gateway.rate_limit import TokenBucket, check_rate_limit, get_rate_limit_stats


# ---------------------------------------------------------------------------
# rate_limit
# ---------------------------------------------------------------------------
class TestTokenBucket:
    def test_burst_then_exhaust(self):
        bucket = TokenBucket(rpm=60, burst=3)
        assert bucket.acquire() is True
        assert bucket.acquire() is True
        assert bucket.acquire() is True
        assert bucket.acquire() is False

    def test_refill_after_time(self):
        import time

        bucket = TokenBucket(rpm=6000, burst=1)
        assert bucket.acquire() is True
        assert bucket.acquire() is False
        time.sleep(0.05)
        assert bucket.acquire() is True


class TestCheckRateLimit:
    def test_default_tenant(self):
        result = check_rate_limit()
        assert isinstance(result, bool)

    def test_tenant_isolation(self):
        for _ in range(100):
            check_rate_limit("tenant_a")
        result_b = check_rate_limit("tenant_b")
        assert result_b is True


def test_get_rate_limit_stats_shape():
    stats = get_rate_limit_stats()
    assert isinstance(stats, dict)


# ---------------------------------------------------------------------------
# output_guard
# ---------------------------------------------------------------------------
class TestDetectOutputPii:
    def test_clean_text(self):
        assert detect_output_pii("这是一段正常文本") == []

    def test_phone(self):
        result = detect_output_pii("联系电话13812345678")
        assert "phone" in result

    def test_id_card(self):
        result = detect_output_pii("身份证号 110101199001011234")
        assert "id_card" in result

    def test_bank_card(self):
        result = detect_output_pii("银行卡 6222021234567890123")
        assert "bank_card" in result


class TestCheckQuality:
    def test_too_short(self):
        result = check_quality("")
        assert result["pass"] is False

    def test_normal_text(self):
        result = check_quality("这是一段足够长的正常回复文本")
        assert result["pass"] is True

    def test_hallucination_marker(self):
        result = check_quality("作为AI语言模型，我不知道这个问题")
        assert result["pass"] is True
        assert "warning" in result or result.get("warning")


class TestGuardOutput:
    def test_safe_text(self):
        result = guard_output("这是一段足够长的正常回复文本，没有敏感信息")
        assert result["safe"] is True
        assert result["pii_leaked"] == []

    def test_unsafe_pii(self):
        result = guard_output("电话13812345678")
        assert result["safe"] is False
        assert "phone" in result["pii_leaked"]

    def test_unsafe_too_short(self):
        result = guard_output("")
        assert result["safe"] is False


# ---------------------------------------------------------------------------
# gray
# ---------------------------------------------------------------------------
class TestIsInGray:
    def test_zero_pct_always_false(self):
        assert is_in_gray("user1", 0.0) is False
        assert is_in_gray("user2", 0.0) is False

    def test_full_pct_always_true(self):
        assert is_in_gray("user1", 100.0) is True
        assert is_in_gray("user2", 100.0) is True

    def test_deterministic(self):
        r1 = is_in_gray("user1", 50.0)
        r2 = is_in_gray("user1", 50.0)
        assert r1 == r2

    def test_distribution(self):
        count = sum(1 for i in range(10000) if is_in_gray(f"user_{i}", 30.0))
        assert 2700 <= count <= 3300


class TestGetGrayConfig:
    def test_shape(self):
        config = get_gray_config()
        assert "gray_pct" in config
        assert "enabled" in config
