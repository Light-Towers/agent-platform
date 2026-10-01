# Plan: P0/P1 修复 — HA 门禁真实性 + 租户安全边界（2026-09-25）

> 来源：v3 分支外部审计（36 commits, HEAD c6b60a55）逐项核实后确认的 P0/P1 问题。
> 原则：**全局视角** —— 不逐点打补丁，按「根因收敛 + 门禁强制 + 测试分层补位」三层处理。

## 1. 问题清单（已核实证据）

| # | 级别 | 问题 | 证据 |
|---|------|------|------|
| F1 | P0 | `_try_baseline_stamp` 把 Python tuple 传给 `ANY(%s)`，psycopg 将 tuple 适配为 record 而非 array，真实 PG 报 `malformed array literal` | `runner.py:228-231`；GitHub Actions `agent-platform-ha` kill 脚本真实复现 |
| F2 | P0 | `_read_tenant_scope` 过渡读：真实租户额外读 `default` 桶 → tenantA/tenantB 共享 `default/ws` 记忆源，跨租户可见 | `typed.py:113-129, 330-332` |
| F3 | P0/P1 | `tests/ha/conftest.py` 无条件 skip：CI 有 PG service 时 init 失败也 skip → 「15 skipped」假绿。**核实补充：15 skipped 与 F1 同根因**（`init_pool → ensure_schema → run_migrations` 在 F1 处抛错 → conftest `except Exception → skip`） | `tests/ha/conftest.py:56-63`；`db.py:78-91`；tests/ha 共 15 个 test 函数 |
| F4 | P1 | `rollback(target_version)` 静默跳过无 down 的 migration → 「目标版本 ≠ 实际版本」语义不一致 | `runner.py:282-286` |
| F5 | P1 | `CapabilityReport` 缺 `supports_tenant_isolation`；`VectorMemoryStore.recall` 忽略 tenant_id 但协议层看不出 | `store.py:32-58, 252-261` |
| F6 | P1 | migration 全部依赖 FakeConnection 单测，无真实 PG 参数适配测试（F1 正是漏网原因） | `test_schema_migrations.py` |
| F7 | P2 | HA workflow 触发含 `applications/**`，任一子服务小改都跑重型 HA | `.github/workflows/ha.yml` |

## 2. 全局设计决策

1. **F2 安全原则**：无法判定归属的 legacy 记忆，**宁可暂时不可见，也不跨租户可见**。租户读谓词收敛为精确 `tenant_id = %s`（与 consolidate/forget 的删除路径一致，读写同一严格语义）；legacy 数据只经 `default` 租户或管理员迁移工具处理，不在业务查询路径自动扩 scope。
2. **F3 门禁语义**：`CI=true` 时环境不满足 = **FAIL**（workflow 名字是 `agent-platform-ha`，不是 `ha-if-postgres-happens-to-work`）；本地无 PG 保留 skip。这与 P2「统一异常处理」同构：环境守卫不能吞掉 CI 的真实故障信号。
3. **F6 分层补位**：新增 `tests/ha/test_migrations_real_pg.py`（L3 真实 PG）：空库 → run_migrations → 版本/幂等/checksum。定位原则：**不让 L1 冒充 L3**。
4. **F5 能力显式化**：`supports_tenant_isolation` 纳入 `CapabilityReport`（pg-typed=True / vector=False），`/health` 直接暴露，调用方不再靠猜。

## 3. 变更清单

| 文件 | 变更 |
|------|------|
| `packages/agent-runtime/agent_runtime/migrations/runner.py` | F1: tuple→list；F4: rollback 拒绝不可回滚 migration |
| `packages/agent-core/agent_core/memory/typed.py` | F2: 删除 `_read_tenant_scope`/`_LEGACY_TENANT_BUCKET`，读谓词精确 tenant |
| `packages/agent-core/agent_core/memory/store.py` | F5: `supports_tenant_isolation` 字段 + 两实现 probe 如实声明 |
| `tests/ha/conftest.py` | F3: CI 模式 fail-not-skip |
| `tests/ha/test_migrations_real_pg.py` | F6: 新增真实 PG migration 集成测试 |
| `packages/agent-core/tests/test_typed_memory.py` | F2: 更新受影响单测 |
| `packages/agent-runtime/tests/test_schema_migrations.py` | F4: 新增 rollback 拒绝/执行单测 |
| `.github/workflows/ha.yml` | F7: 移除 `applications/**` 触发 |

## 4. 影响面与迁移策略

- **行为变化（有意）**：真实租户升级后不再读到 legacy `default` 桶记忆（安全性 > 历史可见性）；`SEMANTIC_MEMORY_TYPED` 语义不变（本计划不触碰）。
- **兼容性**：`CapabilityReport.as_dict` 新增 key，为 /health 追加字段，非破坏。
- **HA workflow**：narrow 后 push/PR 仅在 packages + tests/ha + 脚本/配置变更时触发。

## 5. 验收标准

1. `uv run pytest packages/agent-runtime/tests/test_schema_migrations.py packages/agent-core/tests/test_typed_memory.py packages/agent-core/tests -q` 全绿；
2. `ruff check` 通过；
3. push 后 GitHub Actions：`agent-platform-ha` 的 pytest 步骤 **全 passed（0 skipped）**（用例数随 tests/ha 增长，不锁定具体数字；实施记录：86e3077/b77be4e 两轮均 17 passed + 2 项新增 migration 集成测试 + kill-9 接管 PASS「effectively-once 成立」）；
4. 若 HA 仍红，新失败点即下一轮真实问题（门禁语义已可信）。
