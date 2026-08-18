"""P3：子 Agent 委派防护（熔断器 + 健康短路 + 本地 fallback）。

无真实网络/API 调用：用 FakeRemoteSubAgent 注入失败，验证熔断器状态机、
健康探活短路、指数退避重试与本地 fallback 降级响应。
"""
import asyncio


class FakeRemoteSubAgent:
    """可注入失败行为的远程 subagent（兼容 ainvoke 接口）。"""

    def __init__(self, name="fake-svc", fail_times=0):
        self.name = name
        self.fail_times = fail_times
        self.calls = 0

    async def ainvoke(self, input: dict) -> dict:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError(f"{self.name} down")
        return {"answer": "remote-ok"}


class FakeLocalAgent:
    def __init__(self):
        self.called = False

    async def ainvoke(self, input: dict) -> dict:
        self.called = True
        return {"answer": "local-ok"}


class _FakeSvc:
    def __init__(self, name, healthy=True, local_agent=None):
        self.name = name
        self.graph_id = name
        self.url = "http://fake"
        self.endpoint = "/invoke"
        self.description = name
        self.healthy = healthy
        self.local_agent = local_agent


class TestCircuitBreaker:
    def test_trips_open_after_failure_ratio(self):
        from agent.circuit_breaker import CircuitState, get_breaker_sync

        br = get_breaker_sync("test-trip")
        br._state = CircuitState.CLOSED
        br._successes = []
        br._failures = []
        br.min_requests = 5

        async def run():
            for _ in range(5):
                assert await br.allow()
                await br.record_failure()
            # 5/5 失败 -> 超过 0.5 阈值 -> OPEN
            assert br.state() == CircuitState.OPEN
            # OPEN 且冷却未到期 -> 拒绝
            assert not await br.allow()

        asyncio.run(run())

    def test_recovers_after_cooldown(self):
        from agent.circuit_breaker import CircuitState, get_breaker_sync

        br = get_breaker_sync("test-recover")
        br._state = CircuitState.OPEN
        br._opened_at = 0.0  # 很久以前
        br.cooldown_seconds = 0.0

        async def run():
            assert await br.allow()  # 冷却到期 -> HALF_OPEN
            assert br.state() == CircuitState.HALF_OPEN
            for _ in range(br.half_open_probes):
                await br.record_success()
            assert br.state() == CircuitState.CLOSED

        asyncio.run(run())


class TestDelegatingSubAgent:
    def test_health_short_circuit_without_local(self):
        from agent.async_subagents import DelegatingSubAgent

        svc = _FakeSvc("svc-unhealthy", healthy=False)
        agent = DelegatingSubAgent("k", FakeRemoteSubAgent(), svc, "d")
        out = asyncio.run(agent.ainvoke({"query": "x"}))
        assert out["degraded"] is True
        assert out["degraded_reason"] == "unhealthy"
        assert "不可用" in out["answer"]

    def test_health_short_circuit_uses_local_fallback(self):
        from agent.async_subagents import DelegatingSubAgent

        local = FakeLocalAgent()
        svc = _FakeSvc("svc-local", healthy=False, local_agent={"name": "L"})
        agent = DelegatingSubAgent("k", FakeRemoteSubAgent(), svc, "d")
        agent._local_agent = local  # 跳过编译，直接注入
        out = asyncio.run(agent.ainvoke({"query": "x"}))
        assert out["degraded"] is True
        assert local.called

    def test_retry_then_success(self):
        from agent.async_subagents import DelegatingSubAgent

        svc = _FakeSvc("svc-retry", healthy=True)
        # 首次失败，重试后成功
        agent = DelegatingSubAgent("k", FakeRemoteSubAgent(fail_times=1), svc, "d")
        agent.RETRIES = 1
        out = asyncio.run(agent.ainvoke({"query": "x"}))
        assert out == {"answer": "remote-ok"}

    def test_failure_triggers_circuit_and_fallback(self):
        from agent.async_subagents import DelegatingSubAgent

        svc = _FakeSvc("svc-fail", healthy=True)
        agent = DelegatingSubAgent("k", FakeRemoteSubAgent(fail_times=99), svc, "d")
        agent.RETRIES = 0  # 不重试，直接失败
        out = asyncio.run(agent.ainvoke({"query": "x"}))
        assert out["degraded"] is True
        assert out["degraded_reason"] == "remote_failed"
        # 熔断器已记录一次失败（窗口非空）
        assert len(agent._breaker._failures) >= 1


class TestP3Observability:
    """P3 可观测性回归：熔断状态变化与委派结果须进入 metrics + monitor。"""

    def test_circuit_open_emits_metric_and_monitor(self, monkeypatch):
        from agent_core.monitor import monitor

        from agent import metrics as M
        from agent.circuit_breaker import CircuitState, get_breaker_sync

        # 重置计数 + 捕获 monitor 上报事件
        M.circuit_open_total = 0
        events = []
        monkeypatch.setattr(
            monitor, "report_circuit",
            lambda state, msg, data=None: events.append((state, msg, data)),
        )

        br = get_breaker_sync("obs-trip")
        br._state = CircuitState.CLOSED
        br._successes = []
        br._failures = []
        br.min_requests = 2

        async def run():
            for _ in range(2):
                assert await br.allow()
                await br.record_failure()
            assert br.state() == CircuitState.OPEN

        asyncio.run(run())

        # 熔断 OPEN 计数 +1
        assert M.snapshot()["circuit_open_total"] == 1
        # monitor 收到 circuit_state_change 事件，state=open
        assert any(e[0] == "open" for e in events)

    def test_delegation_success_records_metric(self, monkeypatch):
        from agent import metrics as M
        from agent.async_subagents import DelegatingSubAgent

        M.delegation_success_total = 0
        M.degrade_total = 0

        svc = _FakeSvc("obs-retry", healthy=True)
        agent = DelegatingSubAgent("k", FakeRemoteSubAgent(fail_times=1), svc, "d")
        agent.RETRIES = 1
        out = asyncio.run(agent.ainvoke({"query": "x"}))
        assert out == {"answer": "remote-ok"}
        # 远程成功路径计 success，不计 degraded
        assert M.snapshot()["delegation_success_total"] == 1
        assert M.snapshot()["degrade_total"] == 0

    def test_degraded_fallback_records_metric(self, monkeypatch):
        from agent import metrics as M
        from agent.async_subagents import DelegatingSubAgent

        M.delegation_success_total = 0
        M.degrade_total = 0

        svc = _FakeSvc("obs-unhealthy", healthy=False)
        agent = DelegatingSubAgent("k", FakeRemoteSubAgent(), svc, "d")
        out = asyncio.run(agent.ainvoke({"query": "x"}))
        assert out["degraded"] is True
        # 降级兜底路径计 success(degraded) + degrade
        assert M.snapshot()["degrade_total"] == 1
        assert M.snapshot()["delegation_success_total"] == 1
