# 04 — 剩余债务评估与立项计划

> 2026-09-21；对 [02-debt-diagnosis](02-debt-diagnosis.md) 中"仍成立"且未立方案的较大项给出评估方向与立项建议。
> 这些项均"较大，需单独立项"——本文档给出立项输入，具体方案待逐项深入调研后立。

## 概述

| ID | 优先级 | 类型 | 立项建议 |
|----|--------|------|---------|
| F-S0-08 | P2 | 包名迁移 | 单独立方案（高成本，需迁移期） |
| F-S1-02 | P2 | 收敛期收口 | ✅ 已修复（3616a2e）：AgenticPlanner 迁入 agent_runtime + entry_points |
| F-S1-04 | P2 | 重复实现收敛 | ✅ 已修复（7680c76）：CB 复用 agent_core SlidingWindowPolicy + singleflight 迁入 agent_runtime |
| F-S1-05 | P2 | 重复实现收敛 | 单独立方案（需先确认 exhibition 定位） |
| TB-7 | P3 | 环境依赖 | 可选，不单独立项 |
| TB-11 | P2 | 配置收敛 | 待 pydantic-settings 收敛需求驱动 |
| TB-13 | P2 | 结构性 | 随 Plan-F 收敛自然消解，不单独立项 |

## 1. F-S0-08 — zhanggui-zhiku 包名仍为 app

**现状**：✅ 已修复。包目录已从 `app/` 改名为 `zhanggui_zhiku/`，`import app.*` 已全量替换为 `import zhanggui_zhiku.*`。

**评估方向**：
- 改包目录 `app/` → `zhanggui_zhiku/`，全量替换 `import app` → `import zhanggui_zhiku`；
- 影响面：zhanggui 内所有 .py + tests（unit 223 + integration）+ pyproject + 可能的 sys.path 注入；
- 风险：包名 `app` 在 zhanggui 内部深度嵌入，迁移后需全量回归；integration 层有 `ZHIKU_INTEGRATION=1` 守卫。

**前置依赖**：无，但建议在 F-S1-04/05 收敛后做（避免迁移期多线作战）。
**立项建议**：单独立 `plan-fix-f-s0-08-zhanggui-rename.md`，含全量 import 影响清单 + 迁移脚本 + 回归计划。**工期较大（半天~1天）**。

## 2. F-S1-02 — agent_server 惰性 import agent_federation

**现状**：✅ 已修复（3616a2e，2026-09-21）。

**修复方案**：AgenticPlanner 类从 `agent_federation/planners/agentic.py` 迁入 `agent_runtime/planner/agentic.py`（通用适配器），执行器 `_execute_agent_core` 经 Python entry_points（`agent_runtime.agentic_executor` 组）发现注入。agent_federation 在 pyproject.toml 声明 entry point 并自动注册工厂。agent_server 改从 agent_runtime 导入 AgenticPlanner，消除对 agent_federation 的直接 import。

## 3. F-S1-04 — agent_federation CircuitBreaker+Cache 独立实现

**现状**：✅ 已修复（7680c76，2026-09-21）。

**修复方案**：
- **CircuitBreaker**：`agent_federation/agent/circuit_breaker.py` 重构为委托 `agent_core.resilience.CircuitBreaker(SlidingWindowPolicy)` 引擎，外层保留 async 接口 + 指标上报 + per-name 注册表。同时修复 agent_core `_evaluate_locked` 用 `_min_requests`（非 `_window_size`）作评估阈值的 bug。
- **Singleflight**：`agent_federation/agent/cache/singleflight.py` 迁入 `agent_runtime/singleflight.py`（通用，无 federation 依赖），原位置改为重导出。
- **Cache layers**：`layers.py` 已复用 `agent_core.cache.build_cache_key`（TB-4 闭环），Valkey 后端有意保留（与 agent_runtime PG 后端面向不同场景）。

## 4. F-S1-05 — exhibition-agent 独立实现 Skill+ExecutionContext

**现状**：`applications/exhibition-agent/exhibition_agent/skills/base_skill.py` + `contract/execution_context.py` 独立实现，与 agent_runtime 的 Skill/ExecutionContext 重复（红线 4）。

**评估方向**：
- 评估 exhibition-agent 是否应接入 agent-runtime（作为其又一个应用宿主）；
- 接口契约对齐：exhibition 的 Skill/ExecutionContext 与 agent_runtime 的协议差异；
- exhibition 当前是"平台侧骨架"（跨项目契约 v1.1），接入 agent-runtime 可能改变其定位。

**前置依赖**：exhibition-agent 定位决策（H-S1-02 假设）——**已出评估**（[05-exhibition-positioning-evaluation](05-exhibition-positioning-evaluation.md)），推荐选项 A（保持独立，契约载体非运行时内核能力，红线 4 有意豁免）。
**立项建议**：待维护者拍板。若认可选项 A，F-S1-05 标记"有意豁免"关闭；若选 B/C，立 `plan-fix-f-s1-05-exhibition-runtime-converge.md`。

## 5. TB-7 — docker compose 冒烟需 Docker

**现状**：`Makefile` `compose-smoke` 需 Docker；本机 Windows 无 Docker。

**评估方向**：环境依赖，非代码债务。可选：标注 `requires_docker` + CI Linux 跑。
**立项建议**：**不单独立项**，作为环境约定记录在 02-debt 即可。

## 6. TB-11 — 双轨配置体系部分修复

**现状**：KernelConfig 已落地（agent-core），但 pydantic-settings 收敛保留（agent_federation 等仍有独立配置）。

**评估方向**：待实际需求驱动（H-S2-01 假设）——是否有应用因双轨配置产生 bug？
**立项建议**：**不在现在立**，待需求驱动或 Plan-F 收敛时统一处理。

## 7. TB-13 — 双轨认知/维护成本

**现状**：v3 代际混合，双轨认知成本。

**评估方向**：随 Plan-F 收敛自然消解（H-S2-02 假设）。
**立项建议**：**不单独立项**，作为 Plan-F 收敛的成效指标跟踪。

## 立项顺序建议

1. ✅ **已完成**：F-S0-08 / F-S1-05 / F-S1-02 / F-S1-04
2. **不单独立项**：TB-7 / TB-11 / TB-13（环境 / 设计合理 / 已消解）

## 建议下一步

- 全部剩余项已闭合或附条件关闭，无待立项任务。
- Plan-F 演进方向：Plan.notes → 显式字段 ✅ 完成、Dynamic Agent 纬入 Skill 体系 ✅ 完成、Workflow Definition → Workflow Skill 编译 ✅ 已实现。剩余 SkillRegistry/SkillRuntime 分离暂缓（无真实需求驱动）。
