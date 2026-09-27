"""四类 Memory 阶段 3 单测：Procedural Memory 持久化。

验证：
- ProceduralEntry：数据结构；
- InMemoryProceduralStore：save / load / list_all / list_by_name / delete；
- ProceduralMemory：save_skill_definition / load_skill / recall / delete_skill；
- ProceduralExtractor：从 Episode 挖掘候选 Skill；
- CandidateSkill：success_rate / confidence。
"""


from agent_runtime.episodic_memory import Episode, EpisodeOutcome
from agent_runtime.procedural_memory import (
    CandidateSkill,
    InMemoryProceduralStore,
    ProceduralEntry,
    ProceduralExtractor,
    ProceduralMemory,
)
from agent_runtime.skill_lifecycle import SkillLifecycle

# 隔离域（plan T1）：store/façade 方法必显式传 tenant_id（无 'default' 兜底）。
TENANT = "t-proc"

# ===== ProceduralEntry =====

def test_entry_to_dict():
    entry = ProceduralEntry(
        name="search", version="1.0.0", kind="function", description="搜索能力"
    )
    d = entry.to_dict()
    assert d["name"] == "search"
    assert d["version"] == "1.0.0"


# ===== InMemoryProceduralStore =====

async def test_store_save_and_load():
    store = InMemoryProceduralStore()
    entry = ProceduralEntry(
        name="search", version="1.0.0", kind="function", description="搜索"
    )
    await store.save(entry, tenant_id=TENANT)
    loaded = await store.load("search", "1.0.0", tenant_id=TENANT)
    assert loaded is not None
    assert loaded.description == "搜索"


async def test_store_load_latest_stable():
    store = InMemoryProceduralStore()
    await store.save(ProceduralEntry(
        name="search", version="1.0.0", kind="function",
        description="v1", lifecycle=SkillLifecycle.STABLE.value,
    ), tenant_id=TENANT)
    await store.save(ProceduralEntry(
        name="search", version="2.0.0", kind="function",
        description="v2", lifecycle=SkillLifecycle.STABLE.value,
    ), tenant_id=TENANT)
    await store.save(ProceduralEntry(
        name="search", version="1.5.0", kind="function",
        description="v1.5", lifecycle=SkillLifecycle.DEPRECATED.value,
    ), tenant_id=TENANT)

    loaded = await store.load("search", tenant_id=TENANT)  # version=None → 最新 stable
    assert loaded is not None
    assert loaded.version == "2.0.0"


async def test_store_list_all():
    store = InMemoryProceduralStore()
    await store.save(ProceduralEntry(name="a", version="1.0", kind="function", description=""), tenant_id=TENANT)
    await store.save(ProceduralEntry(name="b", version="1.0", kind="function", description=""), tenant_id=TENANT)
    assert len(await store.list_all(tenant_id=TENANT)) == 2


async def test_store_list_by_name():
    store = InMemoryProceduralStore()
    await store.save(ProceduralEntry(name="search", version="1.0", kind="function", description=""), tenant_id=TENANT)
    await store.save(ProceduralEntry(name="search", version="2.0", kind="function", description=""), tenant_id=TENANT)
    await store.save(ProceduralEntry(name="other", version="1.0", kind="function", description=""), tenant_id=TENANT)
    assert len(await store.list_by_name("search", tenant_id=TENANT)) == 2


async def test_store_delete():
    store = InMemoryProceduralStore()
    await store.save(ProceduralEntry(name="search", version="1.0", kind="function", description=""), tenant_id=TENANT)
    assert await store.delete("search", "1.0", tenant_id=TENANT) is True
    assert await store.delete("search", "1.0", tenant_id=TENANT) is False


async def test_store_cross_tenant_isolated():
    """plan T1：同 (name, version) 由两租户各存一行、互不可见（PK 命名空间化）。"""
    store = InMemoryProceduralStore()
    await store.save(ProceduralEntry(name="auto_x", version="auto", kind="function", description="A"), tenant_id="tA")
    await store.save(ProceduralEntry(name="auto_x", version="auto", kind="function", description="B"), tenant_id="tB")
    a = await store.load("auto_x", "auto", tenant_id="tA")
    b = await store.load("auto_x", "auto", tenant_id="tB")
    assert a.description == "A" and b.description == "B"
    assert len(await store.list_all(tenant_id="tA")) == 1


# ===== ProceduralMemory =====

async def test_proc_save_and_load():
    proc = ProceduralMemory(InMemoryProceduralStore())
    await proc.save_skill_definition(
        name="search", version="1.0.0", kind="function",
        description="向量搜索能力",
        input_schema={"type": "object"},
        tenant_id=TENANT,
    )
    loaded = await proc.load_skill("search", "1.0.0", tenant_id=TENANT)
    assert loaded is not None
    assert loaded.description == "向量搜索能力"


async def test_proc_recall():
    proc = ProceduralMemory(InMemoryProceduralStore())
    await proc.save_skill_definition(
        name="vector_search", version="1.0", kind="function", description="向量搜索", tenant_id=TENANT
    )
    await proc.save_skill_definition(
        name="sql_query", version="1.0", kind="function", description="SQL查询", tenant_id=TENANT
    )

    results = await proc.recall("搜索", tenant_id=TENANT)
    assert len(results) == 1
    assert results[0].name == "vector_search"


async def test_proc_delete():
    proc = ProceduralMemory(InMemoryProceduralStore())
    await proc.save_skill_definition(
        name="search", version="1.0", kind="function", description="搜索", tenant_id=TENANT
    )
    assert await proc.delete_skill("search", "1.0", tenant_id=TENANT) is True
    assert await proc.load_skill("search", "1.0", tenant_id=TENANT) is None


# ===== ProceduralExtractor =====

def test_extractor_no_pattern_insufficient_success():
    extractor = ProceduralExtractor(min_success=3)
    episodes = [
        Episode(execution_id="e1", task_summary="分析", outcome=EpisodeOutcome.SUCCESS,
                skill_names=["query", "analyze"]),
        Episode(execution_id="e2", task_summary="分析", outcome=EpisodeOutcome.SUCCESS,
                skill_names=["query", "analyze"]),
    ]
    assert extractor.extract_patterns(episodes) == []


def test_extractor_finds_pattern():
    extractor = ProceduralExtractor(min_success=3, min_confidence=0.0)
    episodes = [
        Episode(execution_id="e1", task_summary="招商分析", outcome=EpisodeOutcome.SUCCESS,
                skill_names=["query", "analyze", "report"], total_tokens=300),
        Episode(execution_id="e2", task_summary="招商分析", outcome=EpisodeOutcome.SUCCESS,
                skill_names=["query", "analyze", "report"], total_tokens=400),
        Episode(execution_id="e3", task_summary="招商分析", outcome=EpisodeOutcome.SUCCESS,
                skill_names=["query", "analyze", "report"], total_tokens=500),
        Episode(execution_id="e4", task_summary="招商分析", outcome=EpisodeOutcome.FAILURE,
                skill_names=["query", "analyze"], total_tokens=100),
    ]
    candidates = extractor.extract_patterns(episodes)
    assert len(candidates) == 1
    assert candidates[0].name == "auto_招商分析"
    assert candidates[0].success_count == 3
    assert candidates[0].total_count == 4
    assert candidates[0].pattern_steps == ["query", "analyze", "report"]


def test_extractor_multiple_tasks():
    extractor = ProceduralExtractor(min_success=2, min_confidence=0.0)
    episodes = [
        Episode(execution_id="e1", task_summary="分析A", outcome=EpisodeOutcome.SUCCESS,
                skill_names=["a1", "a2"]),
        Episode(execution_id="e2", task_summary="分析A", outcome=EpisodeOutcome.SUCCESS,
                skill_names=["a1", "a2"]),
        Episode(execution_id="e3", task_summary="分析B", outcome=EpisodeOutcome.SUCCESS,
                skill_names=["b1", "b2"]),
        Episode(execution_id="e4", task_summary="分析B", outcome=EpisodeOutcome.SUCCESS,
                skill_names=["b1", "b2"]),
    ]
    candidates = extractor.extract_patterns(episodes)
    assert len(candidates) == 2


def test_extractor_confidence_filter():
    """低 confidence 被过滤。"""
    extractor = ProceduralExtractor(min_success=2, min_confidence=1.5)
    episodes = [
        Episode(execution_id="e1", task_summary="分析", outcome=EpisodeOutcome.SUCCESS,
                skill_names=["s1"]),
        Episode(execution_id="e2", task_summary="分析", outcome=EpisodeOutcome.SUCCESS,
                skill_names=["s1"]),
    ]
    candidates = extractor.extract_patterns(episodes)
    assert candidates == []  # confidence 不够


# ===== CandidateSkill =====

def test_candidate_success_rate():
    c = CandidateSkill(name="test", pattern_steps=[], success_count=3, total_count=5)
    assert c.success_rate == 0.6


def test_candidate_to_dict():
    c = CandidateSkill(name="test", pattern_steps=["a", "b"], success_count=3, total_count=4)
    d = c.to_dict()
    assert d["success_rate"] == 0.75
    assert d["pattern_steps"] == ["a", "b"]
