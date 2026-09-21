# 全局索引

> 三目标结论 + Top 10 债务 + REFUTED 清单 + 待人工拍板项 + R6 自检

## 三目标结论

### 目标 1：架构与代码结构摸底

10 个工程单元（3 packages + 7 applications），670 个 .py 文件，ruff 0 error。v3 处于代际混合迁移收敛期（旧 Supervisor → 新 Runtime+Planner）。五条红线中红线 3 有 1 处 P0 硬违规，红线 4 有 2 处收敛期违规，其余 3 条基本合规。

### 目标 2：技术债与问题诊断

48 条登记（TB 14 + TD 15 + U 1 + Roadmap 8 + S0/S1 新 10），34 已修复（抽查确认），14 仍成立。最严重为 P0 F-S1-03（agent-core.memory 模块级硬依赖 langgraph）。门禁盲区 40 文件/285 实际测试（--collect-only 实测确认）。

### 目标 3：模块上下文包

Tier A×4 深入接手卡 + Tier B×4 卡头 + Tier C×1 仅卡头（zhanggui-zhiku）。每卡含 30 秒定位 → 必读 3 文件 → 改动落点 → 验证命令 → 已知雷区。

---

## Top 10 债务

| # | ID | 严重度 | 问题 | 需先立方案 |
|---|-----|--------|------|-----------|
| 1 | F-S1-03 | **P0** | agent-core.memory 模块级硬依赖 langgraph | 是 |
| 2 | F-S0-01 | P1 | agent-runtime/tests 62 测试在 CI 门外 | 否 |
| 3 | F-S0-02 | P1 | zhanggui-zhiku/tests 223 测试在 CI 门外 | 否 |
| 4 | F-S1-04 | P2 | agent_federation CircuitBreaker+Cache 独立实现 | 是 |
| 5 | F-S1-06 | P2 | _NoOpTracer 2 套独立实现 | 否 |
| 6 | F-S1-05 | P2 | exhibition-agent 独立实现 Skill+ExecutionContext | 是 |
| 7 | F-S1-01 | P2 | agent-runtime 测试反向依赖 agent_server | 否 |
| 8 | F-S1-02 | P2 | agent_server 惰性 import agent_federation | 是 |
| 9 | F-S0-03 | P2 | agent_federation/tests 根级 2 测试门禁外 | 否 |
| 10 | F-S0-08 | P2 | zhanggui-zhiku 包名仍为 app | 是 |

---

## REFUTED 清单（防下游会话重复踩坑）

| 编号 | 先验声称 | 实测结论 | 证据 |
|------|---------|---------|------|
| U-1 | QueryRequest 有 AliasChoices 双写兼容 | **REFUTED**：applications/agent_server/ 搜索 AliasChoices → 零命中 | `grep -rn "AliasChoices" applications/agent_server/` |
| coalesce | coalesce 策略存在 | **REFUTED**：coordinator.py 仅 queue/reject | `grep -n "coalesce" packages/agent-runtime/agent_runtime/coordinator.py` |
| TB-14 | thread_id 会话断裂 | **REFUTED**：auth.py:17 resolve_thread_id 已修复 | `grep -n "resolve_thread_id" applications/agent_federation/api/auth.py` |
| P4-1 | 分布式 session lease 未落地 | **REFUTED**：coordinator.py:36,68 已实现 | `grep -n "LeaseBackend\|PgAdvisoryLeaseBackend" packages/agent-runtime/agent_runtime/coordinator.py` |
| exhibition-agent 未跟踪 | "整目录未跟踪" | **REFUTED**：已 commit d0c3800，44 跟踪文件 |"3 |D | `git log --oneline -1 -- applications/exhibition-agent/` |
| TODO~35 | 预期约 35 处 TODO/FIXME | **REFUTED**：实际 8 处（1 TODO + 7 DeprecationWarning + 0 FIXME） | `grep -rn "TODO\|FIXME\|DeprecationWarning" packages/ applications/ tests/` |

---

## 待人工拍板项

| 编号 | 问题 | 依据 |
|------|------|------|
| H-S0-01 | agent_federation/tests 根级 2 测试是否故意排除（conftest 冲突？） | Makefile 注释提冲突但根级共享 conftest |
| H-S0-02 | zhanggui-zhiku/tests 是否故意不纳入 CI（无 pytest 依赖） | zhanggui-zhiku/pyproject.toml 无 dev 依赖 |
| H-S0-03 | agent-runtime/tests 是否故意不纳入 CI | 无 pytest 配置 |
| H-S1-02 |&nbsp;exhibition-agent 不依赖 agent-runtime 是否有意豁免红线 4 | 独立工程设计 |
| H-S1-03 | agent-runtime otel.py 的 _NoOpTracer 是否先于 agent-core tracing.py | 历史遗留 vs 有意 |
| H-S2-01 | TB-11 长期 pydantic-settings 收敛是否有实际需求驱动 | — |
| H-S2-02 | TB-13 双轨认知成本是否在 Plan-F 收敛后自然消解 | — |

---

## 后续修复跟踪（2026-09-21 更新）

- 已修复（9 项）：F-S1-03 / F-S1-06 / F-S0-01~04 / F-S0-07 / F-S0-09 / F-S0-10 — 见 [02-debt-diagnosis](02-debt-diagnosis.md) §2/§3
- 方案已立待实施：F-S1-01 — 见 [plan-fix-f-s1-01](../../plans/plan-fix-f-s1-01-test-reverse-import.md)
- 剩余评估与立项计划：见 [04-remaining-evaluation](04-remaining-evaluation.md)
- exhibition 定位评估（F-S1-05 决策输入）：见 [05-exhibition-positioning-evaluation](05-exhibition-positioning-evaluation.md)

---

## R6 自检

- [x] 无未经复验的先验 ✅ 直引（A 级作判据引用，B 级逐条抽查）
- [x] 每条 CONFIRMED 有 file:line + 可执行命令
- [x] 旧路径已按映射翻译（app/ → applications/agent_server/ 等）
- [x] 结论与待验证假设分离（7 条假设入"待人工拍板项"）
- [x] 无风格噪音建议（所有建议为门禁/架构/契约层面）
- [x] 门禁盲区有 --collect-only 实测（62 + 223 tests collected）
- [x] 9 个陈旧目录未出现在任何证据路径中
- [x] 先验 ✅ 条目 100% 有三态判定（TB 14 + TD 15 + U 1 + Roadmap 8 = 38 条）
- [ ] 全程零文件写操作（注：用户明确要求"记录到 docs"后解除只读约束，仅新增 docs/analysis/ 产物）
