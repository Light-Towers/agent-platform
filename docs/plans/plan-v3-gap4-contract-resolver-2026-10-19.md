# V3 缺口 4 残差：生产接入 contract_resolver（#99）

- 日期：2026-10-19
- 来源：GitHub issue #99 / TODO §2 V3 缺口 4 残差
- 类型：装配补齐（机制已在，缺生产接线）

## 1. 问题与取证

`RecoveryOrchestrator` 生产构造（`agent_server/main.py` 的 recovery 装配块）未传 `contract_resolver` ⇒ 契约恒 None ⇒ `RecoveryManager.decide` 恒走「无契约默认可重试」，四类 `FailureRecovery`（RETRY_SAFE / QUERY_BEFORE_RETRY / NO_RETRY / MANUAL）的恢复语义在生产路径上落空。TODO §2 缺口 4 原文：「生产未接 contract_resolver ⇒ 契约恒 None，退化为『无契约默认可重试』，不等于已按契约恢复」。

**数据链已存在**（不必新造）：`PgTrajectoryStore.get(execution_id)` → `TrajectoryRecord.plan`（序列化 `Plan`）→ deterministic 模式 `plan["route"]` = skill 名 → `registry.get(name).effect_contract`（`PlannerRuntime.get_effect_contract` 同款查表）。

## 2. 设计

### 2.1 工厂函数（`agent_runtime/execution_recovery.py`）

```python
def make_trajectory_contract_resolver(trajectory_store: Any, registry: Any):
    """execution_id → EffectContract：读轨迹取 plan.route，经 registry 查契约。

    四类落空一律返回 None（= 保持「无契约默认可重试」的现状语义，不静默改判）：
    记录不存在 / route 空（graph·agentic 多 skill 模式，另案）/ skill 未注册 /
    skill 无 contract。
    """
    async def _resolve(execution_id: str):
        record = await trajectory_store.get(execution_id)
        if record is None:
            return None
        route = (record.plan or {}).get("route") or ""
        if not route:
            return None
        try:
            skill = registry.get(route)
        except Exception:      # 未注册 skill：KeyError 等
            return None
        return getattr(skill, "effect_contract", None)
    return _resolve
```

依赖方向：recovery 模块经**参数**拿到 store/registry（不 import 具体实现）⇒ 可单测、不引新依赖边。

### 2.2 装配（`agent_server/main.py`）

recovery 装配块内：`trajectory_store` 在场才构造并传入 resolver；缺席则不传（现值逐字保持）。resolver 的 store/registry 取自同一 lifespan 内已在场的实例（`_build_pg_stores` 的返回值与 skill registry），不新开连接。

### 2.3 不在本项的（登记不粉饰）

- **graph/agentic 模式的逐 skill 契约恢复决策**：一次执行多 skill 时「按哪个契约恢复」需要独立设计（最保守合并？按失败步骤的 skill？）——本项 route 为空即降级 None，该面转新缺口；
- **QUERY_STATUS 动作的执行体**（缺口 3 的 `_mark_for_query` 桩）：本项只让「决策」按契约走，「查外部状态」的执行体仍缺，分属缺口 3。

## 3. 改动清单

1. `execution_recovery.py`：加 `make_trajectory_contract_resolver` + 模块 docstring 的边界行订正（「生产尚未接」→ 已接，附降级语义）；
2. `main.py`：recovery 装配块接线；
3. 测试：
   - `packages/agent-runtime/tests/test_execution_recovery.py` 新增：happy×2（route 命中且有 contract / 命中但无 contract）+ 降级×4（无记录 / route 空 / skill 未注册 / store.get 抛错）；
   - `applications/agent_server/tests/test_v3_wiring_assembly.py` 新增装配判据：trajectory_store 在场 ⇒ RecoveryOrchestrator 收到非 None resolver；缺席 ⇒ 不收（现值保持）；
4. TODO §2 缺口 4 残差行订正 + 追记。

## 4. 验收判据

- 新单测全绿；agent-runtime / agent_server 会话不减分；
- 「剥掉防线必红」自证：把 main.py 的接线删掉 ⇒ 装配用例红；
- ruff / docsync rc=0；TODO 订正（缺口 4 残差清零，graph/agentic 面转新缺口登记）。

## 5. 回滚

单 commit（工厂 + 装配 + 测试），`git revert` 整体回退；回退后行为 = 现状（契约恒 None）。
