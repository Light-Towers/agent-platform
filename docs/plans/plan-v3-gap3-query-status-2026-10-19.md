# V3 缺口 3 残差：QUERY_STATUS 执行体（_mark_for_query 桩→真查）

- 日期：2026-10-19
- 来源：TODO §2 V3 缺口 3 残差（承接 #99 之后转出的新缺口）
- 类型：桩 → 生产实现（查外部真实状态并按态动作）

## 1. 问题与取证

缺口 3 原文：「execution_recovery 虽已接线（Reaper + ControlPlane.recover），但 `Rescheduler._mark_for_query` 仍是只记日志的桩（原文『不改队列状态，由外部 resolver 处理』）⇒『恢复时查外部系统真实状态』这个能力依然没有实现」。

**取证**：
- `_mark_for_query`（execution_recovery.py:221-227）仅 `logger.info`，无查询、无状态变更；
- 可用的查询源**已在场**：`PgAwaitableTaskStore.list_by_execution(execution_id) -> list[AwaitableTask]`（外部任务回执持久化，`awaitable_task_pg.py:112`），状态机 `AwaitableState`：PENDING / SUBMITTED / RUNNING / COMPLETED / FAILED / TIMED_OUT；
- 生产装配已在造 store：`agent_server/main.py:435-441`（pool 在场 → PG store，否则内存）；
- 契约语义来自 `EffectContract.failure_recovery = QUERY_BEFORE_RETRY`（#99 接入后该档决策真正可达）。

## 2. 设计：查 + 四态映射

`Rescheduler` 增可选 `awaitable_store`（经 RecoveryOrchestrator 透传，main 装配块传入在场实例）。`_mark_for_query` 从日志桩变为：

| 查询结果 | 动作 | 理由 |
|---|---|---|
| store 缺席（未装配） | 仅记日志（现值逐字保持） | 降级不猜 |
| `list_by_execution` 空 | 记 WARNING + **无动作** | 无外部状态可查 ⇒ 不从"缺席" fabrication retry/fail；留待下周期/人工 |
| 任一任务 COMPLETED | 重新入队 `:resume:N`（continuation） | 外部工作已落地 ⇒ 执行应从 checkpoint 续跑而非重跑（重跑=重复副作用） |
| 任一任务 FAILED / TIMED_OUT | `complete(FAILED)` | 外部侧已失败 ⇒ 重试无意义 |
| 全部 PENDING/SUBMITTED/RUNNING | **无动作** | 外部执行中 ⇒ **QUERY_BEFORE_RETRY 的核心价值**：防止重复提交副作用 |

`:resume:` 请求复刻 `_retry` 的构造（新 id / metadata 记账），差异仅在 id 前缀与 `recovery_action="resume"` 标记——graph 侧按 checkpoint 续跑（既有机制，本项不改 graph）。

查询自身异常（store 抛错）⇒ try/except 兜住记 WARNING，不崩恢复周期（与 resolve_contract 同款容错）。

## 3. 不在本项（登记）

- `:resume:` 请求入队后**由谁驱动 checkpoint 续跑**——scheduler worker 侧消费路径已存在（execution 从队列取出即走 graph，graph 从 checkpoint 恢复）；本项不新造 worker 逻辑，仅保证入队 + 标记正确；
- 人工审批（HUMAN kind）的 resume 走 `HumanTaskResolver`（已接线），与本路径并存不冲突；
- 多任务混合态（一个 COMPLETED 一个 FAILED）按上表优先级（COMPLETED 优先 resume）——混合态的语义精细判定属执行层设计，此处取保守可解释序并记录。

## 4. 改动清单

1. `execution_recovery.py`：`Rescheduler.__init__(..., awaitable_store=None)`；`_mark_for_query` 实现四态映射；`RecoveryOrchestrator.__init__` 增 `awaitable_store` 透传；模块 docstring 边界行订正；
2. `main.py`：recovery 装配块传入在场的 `awaitable_task_store`；
3. 测试（test_execution_recovery.py 新增）：store 缺席=仅日志 / 空=无动作 / COMPLETED=resume 入队（id 与 metadata 断言）/ FAILED=MARK_FAILED / in-flight=无动作（反重复副作用）/ store 抛错=容错不崩；
4. TODO §2 缺口 3 状态订正（「桩」→ 已实现 + 四态语义表）。

## 5. 验收

- 新测试全绿；agent-runtime / agent_server 会话不减分（23 个存量环境失败计数不变）；
- ruff（BLE001 收窄捕获）/ docsync rc=0；
- 「剥掉防线必红」：删 main.py 传入 ⇒ 装配层行为回退为 store 缺席档（有测试钉住四态）。

## 6. 回滚

单 commit，`git revert` 整体回退；回退后 `_mark_for_query` 回到日志桩（无状态变更，安全）。
