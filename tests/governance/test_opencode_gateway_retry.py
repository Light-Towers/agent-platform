"""opencode-gateway 限流重试/退避 + 错误分类（scripts/opencode_gateway.py）。

守护两件事：
1. **瞬时限流退避重试**——免费层 "Detect Abuse Traffic"(403) 是突发限流非永久封禁，
   重试可恢复；不重试则那次调用的错误文本被下游当 SQL、废掉整查询。
2. **确定性错误不重试**——402 余额 / 400 token 类型 / 模型不存在，重试无益，直接透出。

脚本非包，用 importlib 按文件路径加载；mock `_run_opencode_once` 免真实 opencode。
"""

from __future__ import annotations

import asyncio
import importlib.util
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "opencode_gateway.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("opencode_gateway_under_test", _SCRIPT)
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def gw():
    return _load_module()


def _ok(text="SELECT 1", usage=None):
    return ([text], usage or {"total": 5, "input": 3, "output": 2}, "", "", 0)


def _rate_limited():
    return ([], {"total": 0, "input": 0, "output": 0}, "Forbidden, Detect Abuse Traffic", "", 0)


def _balance():
    return ([], {"total": 0, "input": 0, "output": 0}, "Sorry, your account balance is insufficient", "", 0)


async def _collect(events: AsyncIterator[dict[str, Any]]) -> tuple[str, int]:
    """消费 chunk 流，返回 (拼接 content, 带 usage 的收尾 chunk数)。"""
    content, usage_chunks = "", 0
    async for ch in events:
        for choice in ch.get("choices", []):
            content += choice.get("delta", {}).get("content", "")
        if "usage" in ch:
            usage_chunks += 1
    return content, usage_chunks


class TestIsRateLimit:
    def test_rate_limit_detected(self, gw):
        assert gw._is_rate_limit("Forbidden, Detect Abuse Traffic")
        assert gw._is_rate_limit("429 Too Many Requests")

    def test_deterministic_errors_not_retried(self, gw):
        assert not gw._is_rate_limit("Sorry, your account balance is insufficient")
        assert not gw._is_rate_limit("Personal Access Tokens are not supported")
        assert not gw._is_rate_limit("")


class TestRetryBehaviour:
    async def test_success_first_try_no_retry(self, gw, monkeypatch):
        calls = {"n": 0}

        async def once(prompt, model):
            calls["n"] += 1
            return _ok("SELECT 1")

        monkeypatch.setattr(gw, "_run_opencode_once", once)
        slept: list[float] = []

        async def fake_sleep(d):
            slept.append(d)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)
        content, usage = await _collect(gw._opencode_events("p", "m", "r"))
        assert calls["n"] == 1 and slept == [] and content == "SELECT 1" and usage == 1

    async def test_rate_limit_retries_then_succeeds(self, gw, monkeypatch):
        seq = [_rate_limited(), _rate_limited(), _ok("SELECT 2")]
        calls = {"n": 0}

        async def once(prompt, model):
            r = seq[min(calls["n"], len(seq) - 1)]
            calls["n"] += 1
            return r

        monkeypatch.setattr(gw, "_run_opencode_once", once)
        slept: list[float] = []

        async def fake_sleep(d):
            slept.append(d)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)
        content, usage = await _collect(gw._opencode_events("p", "m", "r"))
        # 前两次限流 → 退避重试 → 第三次成功：拿到的是成功文本，不是错误文本
        assert calls["n"] == 3 and content == "SELECT 2"
        assert slept == [2.0, 4.0], "指数退避 2s→4s"
        assert usage == 1  # 正常收尾发 usage/[DONE]

    async def test_rate_limit_exhausts_retries_then_surfaces_error(self, gw, monkeypatch):
        async def once(prompt, model):
            return _rate_limited()

        monkeypatch.setattr(gw, "_run_opencode_once", once)

        async def fake_sleep(d):
            pass

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)
        content, usage = await _collect(gw._opencode_events("p", "m", "r"))
        # 默认 3 次重试全限流 → 透出真实错误（而非空壳），且仍正常收尾
        assert "Detect Abuse Traffic" in content and usage == 1

    async def test_balance_error_not_retried(self, gw, monkeypatch):
        calls = {"n": 0}

        async def once(prompt, model):
            calls["n"] += 1
            return _balance()

        monkeypatch.setattr(gw, "_run_opencode_once", once)

        async def fake_sleep(d):
            pass

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)
        content, _ = await _collect(gw._opencode_events("p", "m", "r"))
        assert calls["n"] == 1, "402 余额不足是确定性错误，不重试"
        assert "balance" in content


# ---------------------------------------------------------------------------
# 附：全局串行闸 + 最小间隔（免费层 IP 级限额：并发 1 才是安全点）
# ---------------------------------------------------------------------------
async def test_gate_serializes_concurrent_calls(gw, monkeypatch):
    """并发 5 个 _run_opencode_once：持闸执行段同一时刻只有 1 个（闸容量 1）。"""

    monkeypatch.setattr(gw, "_MIN_INTERVAL", 0.0)  # 本用例只验串行，不验间隔
    state = {"in_flight": 0, "max_in_flight": 0}

    async def fake_locked(prompt, model):
        state["in_flight"] += 1
        state["max_in_flight"] = max(state["max_in_flight"], state["in_flight"])
        await asyncio.sleep(0.02)
        state["in_flight"] -= 1
        return (["ok"], {"total": 1, "input": 1, "output": 1}, "", "", 0)

    monkeypatch.setattr(gw, "_run_opencode_locked", fake_locked)
    await asyncio.gather(*[gw._run_opencode_once(f"p{i}", "m") for i in range(5)])
    assert state["max_in_flight"] == 1, f"闸未串行化：同时在飞 {state['max_in_flight']} 个"


async def test_gate_enforces_min_interval(gw, monkeypatch):
    """相邻两次放行至少间隔 _MIN_INTERVAL（把 burst 形状压平再发）。"""
    import time as _time  # noqa: PLC0415

    monkeypatch.setattr(gw, "_MIN_INTERVAL", 0.05)
    monkeypatch.setattr(gw, "_LAST_CALL_TS", 0.0)

    stamps: list[float] = []

    async def fake_locked(prompt, model):
        stamps.append(_time.monotonic())
        return (["ok"], {"total": 1, "input": 1, "output": 1}, "", "", 0)

    monkeypatch.setattr(gw, "_run_opencode_locked", fake_locked)
    await gw._run_opencode_once("a", "m")
    await gw._run_opencode_once("b", "m")
    await gw._run_opencode_once("c", "m")
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert all(g >= 0.045 for g in gaps), f"间隔不足（含调度误差应 ≥0.045s）: {gaps}"
