"""V3-9 单测：Execution Forensic / Reproducibility。

验证：
- ForensicContext：版本指纹序列化 / 反序列化；
- StepForensic：per-step 版本指纹；
- divergence_diagnosis：对比两次执行定位漂移源；
- TrajectoryRecord / TrajectoryStep forensic 字段。
"""


from agent_runtime.forensic import (
    DivergenceFinding,
    ForensicContext,
    StepForensic,
    divergence_diagnosis,
)
from agent_runtime.trajectory.models import TrajectoryRecord, TrajectoryStep

# ===== ForensicContext =====

def test_forensic_context_to_dict():
    ctx = ForensicContext(
        model="gpt-4o",
        model_version="2024-08-06",
        provider="openai",
        prompt_version="v2.3",
        skill_version="exhibition-v1.2",
        planner_version="agentic-v2",
        policy_version="rate-limit-v1.5",
    )
    d = ctx.to_dict()
    assert d["model"] == "gpt-4o"
    assert d["prompt_version"] == "v2.3"


def test_forensic_context_from_dict_roundtrip():
    ctx = ForensicContext(
        model="gpt-4o",
        external_inputs={"api": "hash123"},
        effect_receipts={"order": "receipt456"},
    )
    d = ctx.to_dict()
    restored = ForensicContext.from_dict(d)
    assert restored.model == "gpt-4o"
    assert restored.external_inputs == {"api": "hash123"}
    assert restored.effect_receipts == {"order": "receipt456"}


def test_forensic_context_empty():
    ctx = ForensicContext()
    d = ctx.to_dict()
    assert d["model"] is None
    assert d["external_inputs"] == {}


# ===== StepForensic =====

def test_step_forensic_to_dict():
    sf = StepForensic(
        skill_name="search",
        skill_version="v1.0",
        tool_name="vector_search",
        tool_version="v2",
        external_call_receipt="hash_abc",
    )
    d = sf.to_dict()
    assert d["skill_name"] == "search"
    assert d["external_call_receipt"] == "hash_abc"


def test_step_forensic_from_dict_roundtrip():
    sf = StepForensic(skill_name="search", skill_version="v1.0", model="gpt-4o")
    restored = StepForensic.from_dict(sf.to_dict())
    assert restored.skill_name == "search"
    assert restored.model == "gpt-4o"


# ===== divergence_diagnosis =====

def test_divergence_no_drift():
    ctx1 = ForensicContext(model="gpt-4o", prompt_version="v1", skill_version="v1")
    ctx2 = ForensicContext(model="gpt-4o", prompt_version="v1", skill_version="v1")
    assert divergence_diagnosis(ctx1, ctx2) == []


def test_divergence_model_changed():
    ctx1 = ForensicContext(model="gpt-4o", model_version="2024-08-06")
    ctx2 = ForensicContext(model="gpt-4o-mini", model_version="2024-07-18")
    findings = divergence_diagnosis(ctx1, ctx2)
    dims = {f.dimension for f in findings}
    assert "model" in dims
    assert "model_version" in dims


def test_divergence_prompt_changed():
    ctx1 = ForensicContext(prompt_version="v1")
    ctx2 = ForensicContext(prompt_version="v2")
    findings = divergence_diagnosis(ctx1, ctx2)
    assert len(findings) == 1
    assert findings[0].dimension == "prompt_version"
    assert findings[0].baseline_value == "v1"
    assert findings[0].comparison_value == "v2"


def test_divergence_external_inputs_changed():
    ctx1 = ForensicContext(external_inputs={"api": "hash_a", "db": "hash_b"})
    ctx2 = ForensicContext(external_inputs={"api": "hash_a", "db": "hash_c"})
    findings = divergence_diagnosis(ctx1, ctx2)
    assert len(findings) == 1
    assert findings[0].dimension == "external_inputs.db"


def test_divergence_effect_receipts_changed():
    ctx1 = ForensicContext(effect_receipts={"order": "r1"})
    ctx2 = ForensicContext(effect_receipts={"order": "r2"})
    findings = divergence_diagnosis(ctx1, ctx2)
    assert findings[0].dimension == "effect_receipts.order"


def test_divergence_none_values_ignored():
    """None 值不参与对比（未记录的维度不诊断）。"""
    ctx1 = ForensicContext(model="gpt-4o", prompt_version=None)
    ctx2 = ForensicContext(model="gpt-4o", prompt_version="v1")
    assert divergence_diagnosis(ctx1, ctx2) == []


def test_divergence_finding_to_dict():
    f = DivergenceFinding("model", "gpt-4o", "gpt-4o-mini")
    d = f.to_dict()
    assert d["dimension"] == "model"
    assert d["baseline"] == "gpt-4o"
    assert d["comparison"] == "gpt-4o-mini"


# ===== TrajectoryRecord forensic 字段 =====

def test_trajectory_record_forensic():
    ctx = ForensicContext(model="gpt-4o", prompt_version="v1")
    record = TrajectoryRecord(
        execution_id="e1",
        forensic=ctx.to_dict(),
    )
    d = record.to_dict()
    assert d["forensic"]["model"] == "gpt-4o"


def test_trajectory_step_forensic():
    sf = StepForensic(skill_name="search", skill_version="v1.0")
    step = TrajectoryStep(name="search", forensic=sf.to_dict())
    d = step.to_dict()
    assert d["forensic"]["skill_name"] == "search"


def test_trajectory_record_default_forensic_none():
    record = TrajectoryRecord()
    assert record.forensic is None
    d = record.to_dict()
    assert d["forensic"] is None
