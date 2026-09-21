# 04 — 剩余债务评估与立项计划

> 2026-09-21；对 [02-debt-diagnosis](02-debt-diagnosis.md) 中"仍成立"且未立方案的较大项给出评估方向与立项建议。
> 这些项均"较大，需单独立项"——本文档给出立项输入，具体方案待逐项深入调研后立。

## 概述

| ID | 优先级 | 类型 | 立项建议 |
|----|--------|------|---------|
| F-S0-08 | P2 | 包名迁移 | 单独立方案（高成本，需迁移期） |
| F-S1-02 | P2 | 收敛期收口 | 待 Plan-F 收敛里程碑后立 |
| F-S1-04 | P2 | 重复实现收敛 | 单独立方案（依赖 agent-runtime 能力对齐 + F-S1-02） |
| F-S1-05 | P2 | 重复实现收敛 | 单独立方案（需先确认 exhibition 定位） |
| TB-7 | P3 | 环境依赖 | 可选，不单独立项 |
| TB-11 | P2 | 配置收敛 | 待 pydantic-settings 收敛需求驱动 |
| TB-13 | P2 | 结构性 | 随 Plan-F 收敛自然消解，不单独立项 |

## 1. F-S0-08 — zhanggui-zhiku 包名仍为 app

**现状**：`applications/zhanggui-zhiku/pyproject.toml:6` `name = "zhanggui-zhiku"`，但实际包目录为 `app/`（`[tool.setuptools.packages.find]` 发现 `app`），全仓 `import app.*` 命中 zhanggui。AGENTS.md 已警告"勿在根测试/共享代码 import app"（会遮蔽其他 `app`）。

**评估方向**：
- 改包目录 `app/` → `zhanggui_zhiku/`，全量替换 `import app` → `import zhanggui_zhiku`；
- 影响面：zhanggui 内所有 .py + tests（unit 223 + integration）+ pyproject + 可能的 sys.path 注入；
- 风险：包名 `app` 在 zhanggui 内部深度嵌入，迁移后需全量回归；integration 层有 `ZHIKU_INTEGRATION=1` 守卫。

**前置依赖**：无，但建议在 F-S1-04/05 收敛后做（避免迁移期多线作战）。
**立项建议**：单独立 `plan-fix-f-s0-08-zhanggui-rename.md`，含全量 import 影响清单 + 迁移脚本 + 回归计划。**工期较大（半天~1天）**。

## 2. F-S1-02 — agent_server 惰性 import agent_federation

**现状**：`agent_server/planners/unified.py:90`、`__init__.py:38` 惰性 import agent_federation（收敛期产物）。

**评估方向**：Plan-F「单 Runtime + 多 Planner」收敛后，agent_server 应不再需要 agent_federation 的具体实现（Planner 策略可插拔）。收口方向：删除惰性 import，agent_server 仅依赖 agent-runtime + 自身 Planner 实现。

**前置依赖**：Plan-F 收敛里程碑（agent_federation 是否仍作为独立编排中枢，还是其能力下沉到 agent-runtime）。
**立项建议**：**不在现在立**，待 Plan-F 收敛方向明确后作为收口任务立项。

## 3. F-S1-04 — agent_federation CircuitBreaker+Cache 独立实现

**现状**：`applications/agent_federation/agent/circuit_breaker.py` + `agent/cache/`（`layers.py` / `semantic_cache.py` / `singleflight.py`）独立实现，与 `agent_runtime` 的 circuit_breaker/cache 重复（红线 4）。

**评估方向**：
- 评估 agent_federation 的 CB/Cache 能力是否可改用 agent-runtime 的对应实现；
- 差异点盘点（语义、配置、持久化）→ 决定"替换"还是"保留+桥接"；
- agent_federation 是否在 Plan-F 后继续存在（若下沉，本项随 F-S1-02 收口）。

**前置依赖**：F-S1-02 方向明确（agent_federation 去留）。
**立项建议**：单独立 `plan-fix-f-s1-04-federation-cb-cache-converge.md`，但**在 F-S1-02 立项后做**（避免 agent_federation 去留未定就收敛其内部实现）。

## 4. F-S1-05 — exhibition-agent 独立实现 Skill+ExecutionContext

**现状**：`applications/exhibition-agent/exhibition_agent/skills/base_skill.py` + `contract/execution_context.py` 独立实现，与 agent_runtime 的 Skill/ExecutionContext 重复（红线 4）。

**评估方向**：
- 评估 exhibition-agent 是否应接入 agent-runtime（作为其又一个应用宿主）；
- 接口契约对齐：exhibition 的 Skill/ExecutionContext 与 agent_runtime 的协议差异；
- exhibition 当前是"平台侧骨架"（跨项目契约 v1.1），接入 agent-runtime 可能改变其定位。

**前置依赖**：exhibition-agent 定位决策（独立骨架 vs agent-runtime 宿主，对应 H-S1-02 假设）。
**立项建议**：单独立 `plan-fix-f-s1-05-exhibition-runtime-converge.md`，需先与维护者确认 exhibition 定位。

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

1. **现在可立**：F-S0-08（独立、无前置，但工期大）
2. **待定位/收敛决策后立**：F-S1-05（待 exhibition 定位）→ F-S1-02（待 Plan-F 收敛）→ F-S1-04（跟 F-S1-02）
3. **不单独立项**：TB-7 / TB-11 / TB-13（环境 / 需求驱动 / 自然消解）

## 建议下一步

- 若认可，先立 F-S0-08 方案（最大独立项）；
- F-S1-05 立 exhibition 定位评估（轻量调研，为后续决策提供输入）；
- F-S1-02/04 等 Plan-F 收敛里程碑。
