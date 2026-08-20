"""Context Pipeline 测试（Plan-F）：budget 分层/回流、assembler 组装/裁剪/snapshot 注入、
tool_result 压缩外置、memory gate、skill slicing。"""

from __future__ import annotations

import json

import pytest
from agent_runtime.context.assembler import ContextAssembler
from agent_runtime.context.budget import ContextBudget, Layer
from agent_runtime.context.compact import compact_messages, estimate_tokens, should_compact
from agent_runtime.context.memory_gate import MemoryGate, MemoryItem
from agent_runtime.context.skill_context import slice_skill_context, summarize_child_result
from agent_runtime.context.tool_result import ToolResultCompressor, is_tool_result_ref, read_tool_result

# ---------- budget ----------


def test_budget_static_caps():
    budget = ContextBudget(model_window=100_000)
    assert budget.input_budget == 100_000 - 4096
    caps = budget.static_caps()
    assert caps[Layer.SYSTEM] == int(budget.input_budget * 0.05)
    assert caps[Layer.TOOL_RESULTS] == int(budget.input_budget * 0.35)
    # 合计等于输入预算（整数截断误差 ≤ 层数）
    assert abs(sum(caps.values()) - budget.input_budget) <= len(caps)


def test_budget_reflow_to_conversation():
    """system/task 未用满时，余量回流给 conversation（receiver 优先）。"""
    budget = ContextBudget(model_window=100_000)
    used = {
        Layer.SYSTEM: 100,  # 静态 cap 约 4795，剩 ~4695
        Layer.TOOL_DEFS: 100,
        Layer.TASK: 50,
        Layer.MEMORY: 100,
        Layer.TOOL_RESULTS: 100,  # 这是 receiver，其未用余量不参与回流计算
        Layer.CONVERSATION: 10_000,
        Layer.EXECUTION: 100,
    }
    caps = budget.effective_caps(used)
    static = budget.static_caps()
    # conversation 拿到回流（大于静态上限）
    assert caps[Layer.CONVERSATION] > static[Layer.CONVERSATION]
    # system 等非接收层上限不变
    assert caps[Layer.SYSTEM] == static[Layer.SYSTEM]


def test_budget_reflow_skips_when_no_surplus():
    budget = ContextBudget(model_window=100_000)
    used = {
        Layer.SYSTEM: 10**9,  # 全层超限，无余量
        Layer.TOOL_DEFS: 10**9,
        Layer.TASK: 10**9,
        Layer.MEMORY: 10**9,
        Layer.TOOL_RESULTS: 10**9,
        Layer.CONVERSATION: 10**9,
        Layer.EXECUTION: 10**9,
    }
    caps = budget.effective_caps(used)
    assert caps == budget.static_caps()


def test_budget_requires_sum_one():
    with pytest.raises(ValueError):
        ContextBudget(model_window=1000, layers={Layer.SYSTEM: 0.5, Layer.TASK: 0.6})


# ---------- assembler ----------


def _assembler(llm=None) -> ContextAssembler:
    budget = ContextBudget(model_window=100_000)
    return ContextAssembler(budget, llm=llm, model=None)


@pytest.mark.asyncio
async def test_assemble_basic_order_and_report():
    messages, report = await _assembler().assemble(
        user_message="你好",
        system_prompt="你是助手",
        conversation=[{"role": "user", "content": "旧消息1"}, {"role": "user", "content": "旧消息2"}],
    )
    # system 最前，其次当前用户消息
    assert messages[0] == {"role": "system", "content": "你是助手"}
    assert any(m.get("content") == "你好" for m in messages)
    assert report.total_tokens > 0
    assert report.messages_count == len(messages)
    assert "conversation" in report.layers


@pytest.mark.asyncio
async def test_assemble_snapshot_injects_task_layer():
    snapshot = {
        "task": {"goal": "分析项目", "completed_steps": ["fetch"], "pending": ["analyze"], "constraints": {}},
        "execution": {"outputs": {"search": "结果"}, "errors": {}},
    }
    messages, _report = await _assembler().assemble(snapshot=snapshot)
    texts = [m["content"] for m in messages]
    joined = "\n".join(texts)
    assert "分析项目" in joined
    assert "fetch" in joined
    assert "结果" in joined  # execution.outputs 注入


@pytest.mark.asyncio
async def test_assemble_tool_results_without_budget_pressure():
    messages, report = await _assembler().assemble(tool_results=["结果A", "结果B"])
    assert any("结果A" in m.get("content", "") for m in messages)
    # 未超预算：不产生外置/丢弃动作
    assert all(a["action"] != "dropped" for a in report.actions)


@pytest.mark.asyncio
async def test_assemble_conversation_trims_without_llm():
    """无 LLM：对话层超预算时只保留最近 N 条（禁用回流以确定性触发裁剪）。"""
    assembler = ContextAssembler(
        ContextBudget(
            model_window=100_000,
            layers={
                Layer.SYSTEM: 0.05,
                Layer.TOOL_DEFS: 0.05,
                Layer.TASK: 0.05,
                Layer.CONVERSATION: 0.05,  # 压小对话预算，制造超限
                Layer.MEMORY: 0.05,
                Layer.TOOL_RESULTS: 0.6,
                Layer.EXECUTION: 0.15,
            },
            reflow_receivers=(),  # 关闭回流：conversation 只有静态 5% 上限
        )
    )
    conv = [{"role": "user", "content": "x" * 500} for _ in range(20)]
    messages, report = await assembler.assemble(conversation=conv)
    assert any(a["action"] == "truncated" for a in report.actions)
    assert report.total_tokens <= assembler.budget.input_budget


@pytest.mark.asyncio
async def test_assemble_conversation_only_compact_with_llm():
    """assemble_conversation_only：超阈值且有 LLM 时产出 summary + 最近 N 条。"""
    class _MockLLM:
        async def ainvoke(self, messages, **kwargs):
            return type("R", (), {"content": "这是摘要"})()
    assembler = ContextAssembler(
        ContextBudget(
            model_window=100_000,
            layers={
                Layer.SYSTEM: 0.05,
                Layer.TOOL_DEFS: 0.05,
                Layer.TASK: 0.05,
                Layer.CONVERSATION: 0.05,
                Layer.MEMORY: 0.05,
                Layer.TOOL_RESULTS: 0.6,
                Layer.EXECUTION: 0.15,
            },
            reflow_receivers=(),  # 关闭回流：conversation 只有静态 5% 上限
        ),
        llm=_MockLLM(),
    )
    conv = [{"role": "user", "content": "x" * 1200} for _ in range(10)]  # ~8000 tokens > 静态上限 4795
    compacted, report = await assembler.assemble_conversation_only(messages=conv)
    assert compacted is not None
    assert compacted[0]["role"] == "system"
    assert "摘要" in compacted[0]["content"]
    assert len(compacted) == 4 + 1  # 保留最近 4 条 + summary
    assert any(a["action"] == "compacted" for a in report.actions)


@pytest.mark.asyncio
async def test_assemble_conversation_only_no_llm_returns_none():
    messages, _report = await _assembler().assemble_conversation_only(
        messages=[{"role": "user", "content": "x" * 1000} for _ in range(10)]
    )
    assert messages is None  # 无 LLM：不触发压缩（与旧行为一致：跳过）


@pytest.mark.asyncio
async def test_assemble_conversation_only_below_cap():
    messages, _report = await _assembler().assemble_conversation_only(
        messages=[{"role": "user", "content": "短"}],
        conversation_cap=10**9,
    )
    assert messages is None


# ---------- tool_result ----------


def test_tool_result_normalize_and_compress():
    compressor = ToolResultCompressor(max_tokens=10)  # 极小阈值强制压缩
    big = {"items": [f"行{i}" * 20 for i in range(50)]}
    out = compressor.compress(big)
    assert out["truncated"] is True
    assert out["ref"]
    assert is_tool_result_ref(out["ref"])
    assert "完整结果已外置" in out["text"]


def test_tool_result_within_budget_untouched():
    compressor = ToolResultCompressor(max_tokens=10_000)
    out = compressor.compress("短结果")
    assert out["truncated"] is False
    assert out["text"] == "短结果"


def test_tool_result_externalize_and_read(tmp_path):
    compressor = ToolResultCompressor(max_tokens=10, store_dir=tmp_path)
    big = "x" * 5000
    out = compressor.compress(big)
    assert out["full_path"]
    full = read_tool_result(out["ref"], tmp_path)
    assert full == big


# ---------- memory gate ----------


def test_memory_gate_dedup_and_rank():
    gate = MemoryGate(top_k=10)
    items = [
        MemoryItem(content="北京天气", score=0.9),
        MemoryItem(content="北京天气！", score=0.5),  # 归一化后与上一条重复 → 保留 0.9
        MemoryItem(content="上海天气", score=0.8),
    ]
    out = gate.gate(items)
    assert [i.content for i in out] == ["北京天气", "上海天气"]


def test_memory_gate_top_k_and_budget():
    gate = MemoryGate(top_k=2)
    items = [MemoryItem(content=f"记忆{i}", score=float(i)) for i in range(5)]
    out = gate.gate(items)
    assert len(out) == 2  # top_k 截断
    assert out[0].content == "记忆4"

    gate_budget = MemoryGate(top_k=10, max_tokens=3)  # 极小预算
    out2 = gate_budget.gate(items)
    assert len(out2) == 1  # 预算内只进一条


def test_memory_gate_conflict_latest_wins():
    gate = MemoryGate(top_k=10)
    items = [
        MemoryItem(content="同一事实", kind="fact", timestamp=1.0),
        MemoryItem(content="同一事实", kind="fact", timestamp=5.0),
    ]
    out = gate.gate(items)
    assert len(out) == 1
    assert out[0].timestamp == 5.0


# ---------- skill slicing ----------


def test_slice_skill_context_inherits_goal_only():
    snapshot = {"task": {"goal": "分析项目", "completed_steps": ["a"], "pending": ["b"], "constraints": {"k": "v"}}}
    ctx = slice_skill_context(task_snapshot=snapshot, params={"query": "x"}, gated_memory=["相关记忆"])
    assert ctx.inherited["goal"] == "分析项目"
    assert ctx.inherited["constraints"] == {"k": "v"}
    assert "completed_steps" not in ctx.inherited  # 未在 inherit_keys 中
    assert ctx.task_specific == {"query": "x"}
    assert ctx.memory == ["相关记忆"]
    text = ctx.to_prompt_text()
    assert "父任务上下文" in text and "本次任务参数" in text


def test_slice_skill_context_empty_ok():
    ctx = slice_skill_context()
    assert ctx.empty


@pytest.mark.asyncio
async def test_summarize_child_result():
    out = await summarize_child_result({"data": ["x" * 500 for _ in range(10)]}, max_tokens=10)
    assert out["truncated"] is True


# ---------- compact（下沉后行为不变） ----------


def test_compact_should_compact_semantics():
    msgs = [{"role": "user", "content": "x" * 200} for _ in range(10)]
    assert should_compact(msgs, 100)
    assert not should_compact(msgs, 10**9)
    assert estimate_tokens([]) == 0


@pytest.mark.asyncio
async def test_compact_messages_dict_form():
    class _MockLLM:
        async def ainvoke(self, messages, **kwargs):
            return type("R", (), {"content": "摘要"})()
    msgs = [{"role": "user", "content": f"问题{i}"} for i in range(8)]
    compacted, err = await compact_messages(msgs, _MockLLM())
    assert err is None
    assert compacted[0] == {"role": "system", "content": "[上下文摘要] 摘要"}
    assert len(compacted) == 4 + 1


@pytest.mark.asyncio
async def test_compact_messages_failure_degrades():
    class _Fail:
        async def ainvoke(self, messages, **kwargs):
            raise RuntimeError("boom")

    msgs = [{"role": "user", "content": "x"} for _ in range(10)]
    compacted, err = await compact_messages(msgs, _Fail())
    assert err is not None and "COMPACTION_FAILED" in err
    assert compacted is msgs


@pytest.mark.asyncio
async def test_tool_result_compression_middleware(tmp_path):
    """P1 接线：ToolResultCompressionMiddleware 挂洋葱链，超预算结果外置 + 截断视图。"""
    from agent_runtime.skills.middleware import ToolResultCompressionMiddleware

    big = "x" * 50_000
    calls = {"n": 0}

    async def call_next(name, kwargs):
        calls["n"] += 1
        return [big]

    mw = ToolResultCompressionMiddleware(max_tokens=10, store_dir=tmp_path)
    out = await mw.around("search", {"query": "q"}, call_next)
    assert isinstance(out, dict) and out.get("truncated") is True
    assert out.get("ref") and is_tool_result_ref(out["ref"])
    assert calls["n"] == 1
    restored = read_tool_result(out["ref"], tmp_path)
    assert restored == json.dumps([big], ensure_ascii=False)


@pytest.mark.asyncio
async def test_tool_result_compression_middleware_scope():
    """skill_names 限定：未列出的技能不压缩。"""
    from agent_runtime.skills.middleware import ToolResultCompressionMiddleware

    mw = ToolResultCompressionMiddleware(max_tokens=10, skill_names=("search",))
    small = ["ok"]

    async def call_next(name, kwargs):
        return small

    assert await mw.around("rag", {"query": "q"}, call_next) is small
    out = await mw.around("search", {"query": "q"}, call_next)
    assert isinstance(out, dict) and out["truncated"] is False  # 命中作用域但未超预算：返回视图
    assert "ok" in out["text"]