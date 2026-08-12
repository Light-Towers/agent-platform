# -*- coding: utf-8 -*-
"""
test_concurrency.py —— M6 并发与水平扩展单测（方案 §10.3 / §10.4）。

覆盖：
1. **fan-out 超时隔离**（`app/query_process/agent/fanout.guarded_call`）：
   - 单路超时 → 返回 {}（空状态更新），整体不抛异常；
   - 单路异常 → 返回 {}，不拖垮整体；
   - 正常路径透传节点返回的 dict；非 dict 结果（如 None）归一为 {}；
   - `wrap_channel_node` 从 retrieval.yaml 读 enabled/timeout_s（可注入假配置验证）。
2. **reranker 并发闸门**（`app/utils/rerank_concurrency`）：
   - mock compute_score 并发调用数 ≤ max_concurrency；
   - 非法 max_concurrency 收敛到 1。
3. **M6 探针豁免回归**：/health/live、/health/ready 免鉴权 / 免限流
   （M5 安全护栏豁免逻辑随 M6 新增探针扩展）。

【依赖策略】本文件只 import 轻量纯模块（fanout 依赖 retrieval_config/tracing/logger，
rerank_concurrency 纯 stdlib，security_guard_utils 纯 stdlib），无 fastapi / torch /
pymilvus 等重型依赖，本地 venv 即可全绿。
"""

import threading
import time

from app.conf.yaml_config_utils import CfgDict
from app.query_process.agent import fanout
from app.utils.rerank_concurrency import call_under_semaphore, make_rerank_semaphore
from app.utils.security_guard_utils import should_skip_all_guards, should_skip_auth, should_skip_rate_limit


# ===========================================================================
# 1) fan-out 超时隔离（guarded_call / wrap_channel_node）
# ===========================================================================
def test_guarded_call_returns_result():
    def fast(state):
        return {"embedding_chunks": [{"chunk_id": "c1"}]}

    result = fanout.guarded_call(fast, "embedding", timeout_s=1.0, state={"session_id": "s"})
    assert result == {"embedding_chunks": [{"chunk_id": "c1"}]}


def test_guarded_call_timeout_returns_empty():
    def slow(state):
        time.sleep(0.5)
        return {"embedding_chunks": [{"chunk_id": "c1"}]}

    start = time.monotonic()
    result = fanout.guarded_call(slow, "embedding", timeout_s=0.05, state={"session_id": "s"})
    elapsed = time.monotonic() - start
    # 超时上界生效：返回 {} 且整体等待被截断（不含被放弃线程的收尾时间）
    assert result == {}
    assert elapsed < 0.4


def test_guarded_call_exception_returns_empty():
    def boom(state):
        raise RuntimeError("channel boom")

    result = fanout.guarded_call(boom, "kg", timeout_s=1.0, state={"session_id": "s"})
    assert result == {}


def test_guarded_call_non_dict_result_normalized():
    def none_result(state):
        return None  # 如 node_query_kg 占位实现返回 None

    assert fanout.guarded_call(none_result, "kg", timeout_s=1.0, state={"session_id": "s"}) == {}


def test_guarded_call_state_update_merges_failures():
    """模拟四路中两路成功、两路失败：成功路结果保留，失败路 {} 不抛异常（聚合语义）。"""

    def ok_embedding(state):
        return {"embedding_chunks": [{"chunk_id": "e1"}]}

    def ok_hyde(state):
        return {"hyde_embedding_chunks": [{"chunk_id": "h1"}]}

    def timeout_kg(state):
        time.sleep(0.5)
        return {"kg_chunks": [{"chunk_id": "k1"}]}

    def fail_web(state):
        raise RuntimeError("web down")

    results = {
        "embedding": fanout.guarded_call(ok_embedding, "embedding", 0.2, {"session_id": "s"}),
        "hyde": fanout.guarded_call(ok_hyde, "hyde", 0.2, {"session_id": "s"}),
        "kg": fanout.guarded_call(timeout_kg, "kg", 0.05, {"session_id": "s"}),
        "web": fanout.guarded_call(fail_web, "web", 0.2, {"session_id": "s"}),
    }
    assert results["embedding"]["embedding_chunks"][0]["chunk_id"] == "e1"
    assert results["hyde"]["hyde_embedding_chunks"][0]["chunk_id"] == "h1"
    assert results["kg"] == {}  # 超时路降级为空
    assert results["web"] == {}  # 异常路降级为空
    # 整体成功（无异常抛出）


def _channels_cfg(**channels):
    """构造嵌套 CfgDict 假配置（顶层/嵌套均需 CfgDict 才支持属性访问）。"""
    return CfgDict({"channels": CfgDict({k: CfgDict(v) for k, v in channels.items()})})


def test_wrap_channel_node_uses_channel_timeout(monkeypatch):
    fake_cfg = _channels_cfg(embedding={"enabled": True, "timeout_s": 0.05})
    monkeypatch.setattr(fanout, "retrieval_cfg", fake_cfg)

    def slow(state):
        time.sleep(0.5)
        return {"embedding_chunks": [{"chunk_id": "c1"}]}

    node = fanout.wrap_channel_node(slow, "embedding")
    assert node({"session_id": "s"}) == {}  # 0.05s 超时生效


def test_wrap_channel_node_disabled_returns_empty(monkeypatch):
    fake_cfg = _channels_cfg(embedding={"enabled": False, "timeout_s": 1.0})
    monkeypatch.setattr(fanout, "retrieval_cfg", fake_cfg)
    node = fanout.wrap_channel_node(lambda state: {"embedding_chunks": [1]}, "embedding")
    assert node({"session_id": "s"}) == {}


def test_wrap_channel_node_passthrough_when_ok(monkeypatch):
    fake_cfg = _channels_cfg(embedding={"enabled": True, "timeout_s": 1.0})
    monkeypatch.setattr(fanout, "retrieval_cfg", fake_cfg)
    node = fanout.wrap_channel_node(lambda state: {"embedding_chunks": [{"chunk_id": "c1"}]}, "embedding")
    assert node({"session_id": "s"}) == {"embedding_chunks": [{"chunk_id": "c1"}]}


# ===========================================================================
# 2) reranker 并发闸门（Semaphore 语义）
# ===========================================================================
def test_rerank_semaphore_limits_concurrency():
    sem = make_rerank_semaphore(2)
    lock = threading.Lock()
    active = {"n": 0}
    peak = {"n": 0}

    def slow_compute(pairs):
        with lock:
            active["n"] += 1
            peak["n"] = max(peak["n"], active["n"])
        time.sleep(0.05)
        with lock:
            active["n"] -= 1
        return [0.9] * len(pairs)

    def worker():
        for _ in range(5):
            call_under_semaphore(sem, slow_compute, [("q", "d")] * 3)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert peak["n"] <= 2  # mock 模型调用并发数不超过 max_concurrency


def test_make_rerank_semaphore_min_one():
    # 非法值（<=0）收敛到 1：acquire 一次成功、第二次非阻塞失败
    sem = make_rerank_semaphore(0)
    assert sem.acquire(blocking=False) is True
    assert sem.acquire(blocking=False) is False
    sem.release()


# ===========================================================================
# 3) M6 探针豁免回归（/health/live、/health/ready 免鉴权 / 免限流）
# ===========================================================================
def test_health_probe_subpaths_exempt():
    assert should_skip_all_guards("/health/live") is True
    assert should_skip_all_guards("/health/ready") is True
    assert should_skip_auth("/health/ready") is True
    assert should_skip_rate_limit("/health/live") is True
    # 非探针路径不受影响
    assert should_skip_all_guards("/query") is False
    assert should_skip_auth("/query") is False
