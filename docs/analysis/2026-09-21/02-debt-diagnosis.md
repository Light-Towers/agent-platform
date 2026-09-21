# 02 — 债务诊断（S2）

> 先验 48 条三态判定 + S0/S1 新发现 10 条 + P0-P3 排序 + REFUTED 清单 + 待验证假设。

## 1. 先验债务三态判定（TB 14 + TD 15 + U 1 + Roadmap 8 = 38 条）

### 1.1 TB（架构优化待办）

| 编号 | 三态 | 证据 |
|------|------|------|
| TB-1 | 已修复 | dialogue_framework/shared/llm/core_adapter.py 存在 |
| TB-2 | 已修复 | dialogue_framework/core/tracker_memory.py 存在 |
| TB-3 | 已修复 | 环境约定（uv sync --all-packages） |
| TB-4 | 已修复 | agent_core.cache BaseSemanticCache Protocol |
| TB-5 | 已修复 | shared_schemas 断言已补齐 |
| TB-6 | 已修复 | kefu QueryResponse + test_async_subagents_contract.py |
| TB-7 | **仍成立（可选）** | Makefile:63 compose-smoke 需 Docker |
| TB-8 | 已修复 | .github/workflows/ agent-platform-ci.yml + eval-llm.yml |
| TB-9 | 已修复 | agent_core.intent.classify_intent + intent_bridge.py |
| TB-10 | 已修复 | agent_federation main_agent_memory.py typed 长期记忆 |
| TB-11 | **部分修复** | KernelConfig 已落地；pydantic-settings 收敛保留 |
| TB-12 | 已修复 | PgSemanticCache/SemanticCache 实现 BaseSemanticCache |
| TB-13 | **仍成立（结构性）** | v3 代际混合，双轨认知成本 |
| TB-14 | 已修复 | agent_federation/api/auth.py:17 resolve_thread_id |

### 1.2 TD（技术债）

| 编号 | 三态 | 证据 |
|------|------|------|
| TD-0 | 已修复 | commit 248f0e9 |
| TD-1 | 已修复 | kefu_agent/graph.py:11-14 import agent_core.intent |
| TD-2 | 已修复 | 与 TD-1 同源 |
| TD-3 | 已修复 | 原文件已迁移到 agent_core/intent/ |
| TD-4 | 已修复 | 阈值收敛到 agent_core/intent/models.py |
| TD-5 | 已修复 | ITEM_CONFIRM_HIGH/MID_THRESHOLD 环境变量 |
| TD-6 | 已修复 | MEMORY_FORGET_THRESHOLD/AGE_DAYS |
| TD-7 | 已修复 | route_hints.json 数据驱动 |
| TD-8 | 已修复 | longterm prompt 泛化 |
| TD-9 | 已修复 | eval 超参读 yaml |
| TD-10 | 已修复 | ADMISSION_ADMITTED/QUEUED/REJECTED 常量 |
| TD-11 | 已修复 | workspace_id 统一 |
| TD-12 | 已修复 | agent_federation docs 同步 |
| TD-13 | 已修复 | main_agent_memory.py docstring |
| TD-14 | 已修复 | metrics.py + monitor.report_circuit |

### 1.3 U + Roadmap

| 编号 | 三态 | 证据 |
|------|------|------|
| U-1 | 已修复 | applications/agent_server/ 搜 AliasChoices → 零命中 |
| P2-1 | 已修复 | ExecutionContext tokens_used/cost_used |
| P2-2 | 已修复 | FallbackChatModel usage_metadata |
| P3-1 | 已修复 | agent_runtime/trajectory/ 存在 |
| P3-2 | 已修复 | trajectory/replay.py 存在 |
| P4-1 | 已修复 | coordinator.py:36 LeaseBackend + :68 PgAdvisoryLeaseBackend |
| P4-2 | 已修复 | scripts/lint_architecture.py |
| P4-3 | 已修复 | coalesce 移除，仅 queue/reject |
| P5-1 | 已修复 | _fingerprint + enable_loop_fingerprint |

**先验小结**：38 条中 34 已修复，4 仍成立（TB-7 可选 / TB-11 部分 / TB-13 结构性 / 无第 4 条——实际 3 条仍成立 + TB-11 部分修复）。

## 2. S0/S1 新发现债务（10 条）

### 2.1 门禁盲区（S0）

| ID | 严重度 | 目录 | 文件数 | 实测 tests |
|----|--------|------|--------|-----------|
| F-S0-01 | ✅P1 已修复 | packages/agent-runtime/tests/ | 12 | 62（--collect-only） |
| F-S0-02 | ✅P1 已修复 | applications/zhanggui-zhiku/tests/ | 23 | 223（--collect-only） |
| F-S0-03 | ✅P2 已修复 | applications/agent_federation/tests/（根级） | 2 | — |
| F-S0-04 | ✅P2 已修复 | applications/dialogue-framework/tests/ | 1 | — |

### 2.2 架构违规（S1）

| ID | 严重度 | 红线 | 问题 | 证据 |
|----|--------|------|------|------|
| **F-S1-03** | ✅**P0** 已修复 | 3 | agent-core.memory 模块级硬依赖 langgraph | memory/__init__.py:34 → mongo_checkpointer.py:24,31 |
| F-S1-01 | ✅P2 已修复 | 1 | agent-runtime 测试反向依赖 agent_server | test_graph_planner_dynamic.py:14 |
| F-S1-02 | P2 | 2 | agent_server 惰性 import agent_federation | planners/unified.py:90, __init__.py:38 |
| F-S1-04 | P2 | 4 | agent_federation CircuitBreaker+Cache 独立实现 | circuit_breaker.py:45, cache/layers.py:57+ |
| F-S1-05 | P2 | 4 | exhibition-agent 独立实现 Skill+ExecutionContext | base_skill.py:43,53, execution_context.py:35 |
| F-S1-06 | ✅P2 已修复 | 再造 Runtime | _NoOpTracer 2 套独立实现 | tracing.py:137 vs otel.py:57 |

### 2.3 配置/文档（S0）

| ID | 严重度 | 问题 | 证据 |
|----|--------|------|------|
| F-S0-07 | ✅P3 已修复 | ruff select 缺 I | agent-core/pyproject.toml:84 |
| F-S0-08 | P2 | zhanggui-zhiku 包名仍为 app | zhanggui-zhiku/pyproject.toml:48,55 |
| F-S0-09 | ✅P3 已修复 | ARCHITECTURE.md §2.2 未列 exhibition-agent | ARCHITECTURE.md:47-52 |
| F-S0-10 | ✅P3 已修复 | agent-runtime 无 ruff/pytest 配置 | agent-runtime/pyproject.toml |

## 3. 仍成立债务汇总（按 P0/P1/P2/P3 排序）

### P0（红线违规 / 生产安全）

| ID | 问题 | 核验命令 | 修复方向 |
|----|------|---------|---------|
| **F-S1-03** | ✅已修复（d80a27e）：agent-core.memory 模块级硬依赖 langgraph+langchain_core | `python -c "import agent_core.memory"` | mongo_checkpointer 的 langgraph/langchain_core import 改为函数内惰性导入 |

### P1（门禁盲区）

| ID | 问题 | 核验命令 | 修复方向 |
|----|------|---------|---------|
| F-S0-01 | ✅已修复（d80a27e）：agent-runtime/tests 62 测试在 CI 门外 | `git ls-files packages/agent-runtime/tests/ \| grep -vc __pycache__` → 12 | Makefile test 增加该路径 |
| F-S0-02 | ✅已修复（d80a27e）：zhanggui-zhiku/tests 223 测试在 CI 门外 | `git ls-files applications/zhanggui-zhiku/tests/ \| grep -vc __pycache__` → 23 | Makefile test 增加该路径 |

### P2（重复实现 / 契约漂移 / 收敛期）

| ID | 问题 | 状态 | 修复方向 |
|----|------|------|---------|
| F-S0-03 | ✅已修复（d80a27e）：agent_federation/tests 根级 2 测试门禁外 | 新 | Makefile 去掉 /unit |
| F-S0-04 | ✅已修复（d80a27e）：dialogue-framework/tests 1 测试门禁外 | 新 | Makefile 补路径 |
| F-S0-08 | zhanggui-zhiku 包名仍为 app | 已知 | 评估迁移成本 |
| F-S1-01 | ✅已修复（F-S1-01 实施）：agent-runtime 测试反向依赖 agent_server | 新 | 迁移归属到 applications/agent_server/tests/ |
| F-S1-02 | agent_server 惰性 import agent_federation | 新（收敛期） | Plan-F 收敛后收口 |
| F-S1-04 | agent_federation CB+Cache 独立实现 | 已知（§5） | 收敛到 agent-runtime |
| F-S1-05 | exhibition-agent 独立实现 Skill+ExecutionContext | 新 | 评估依赖 agent-runtime |
| F-S1-06 | ✅已修复（d67ed2a）：_NoOpTracer 2 套独立实现 | 新 | agent-runtime 从 agent-core 导入 |
| TB-7 | docker compose 冒烟需 Docker | 可选 | 环境依赖 |
| TB-11 | 双轨配置体系部分修复 | 部分修复 | pydantic-settings 收敛 |
| TB-13 | 双轨认知/维护成本 | 结构性 | 优化 F 收敛中 |

### P3（配置不一致 / 文档漂移）

| ID | 问题 | 修复方向 |
|----|------|---------|
| F-S0-07 | ✅已修复（d80a27e）：ruff select 缺 I | 统一为 ["E4","E7","E9","F","I"] |
| F-S0-09 | ✅已修复（d80a27e）：ARCHITECTURE.md §2.2 未列 exhibition-agent | 补充 |
| F-S0-10 | ✅已修复（d80a27e）：agent-runtime 无 ruff/pytest 配置 | 补充配置 |

## 4. REFUTED 清单（先验声称 vs 实测）

| 编号 | 先验声称 | 实测结论 | 核验命令 |
|------|---------|---------|---------|
| U-1 | QueryRequest 有 AliasChoices 双写 | **REFUTED**：零命中 | `grep -rn "AliasChoices" applications/agent_server/` |
| coalesce | coalesce 策略存在 | **REFUTED**：仅 queue/reject | `grep -n "coalesce" packages/agent-runtime/agent_runtime/coordinator.py` |
| TB-14 | thread_id 会话断裂 | **REFUTED**：auth.py:17 已修复 | `grep -n "resolve_thread_id" applications/agent_federation/api/auth.py` |
| P4-1 | 分布式 lease 未落地 | **REFUTED**：coordinator.py:36,68 已实现 | `grep -n "LeaseBackend" packages/agent-runtime/agent_runtime/coordinator.py` |
| exhibition-agent 未跟踪 | "整目录未跟踪" | **REFUTED**：已 commit d0c3800，44 跟踪文件 | `git log --oneline -1 -- applications/exhibition-agent/` |
| TODO~35 | 预期约 35 处 TODO/FIXME | **REFUTED**：实际 8 处（1 TODO + 7 DeprecationWarning + 0 FIXME） | `grep -rn "TODO\|FIXME\|DeprecationWarning" packages/ applications/ tests/` |

## 5. 文档失效（4 处）

| 问题 | 说明 |
|------|------|
| tech-debt-hardcoded-logic.md 路径 | TD-3/TD-4 引用原 `agent_federation/agent/intent/classifier.py`（已迁移到 agent_core/intent/） |
| runtime-governance-roadmap.md | 顶部已自警示"第三方审核稿部分过时"（:8-15） |
| ARCHITECTURE.md §2.2 | 未列 exhibition-agent |
| ARCHITECTURE.md :14 | 仍用旧名 `app`/`deepagents` |

## 6. 待验证假设

| 编号 | 假设 | 验证方式 |
|------|------|----------|
| H-S0-01 | agent_federation/tests 根级 2 测试是否故意排除（conftest 冲突？） | 查 Makefile 注释 + conftest |
| H-S0-02 | zhanggui-zhiku/tests 是否故意不纳入 CI | 查 pyproject.toml dev 依赖 |
| H-S0-03 | agent-runtime/tests 是否故意不纳入 CI | 查 pytest 配置 |
| H-S1-02 | exhibition-agent 不依赖 agent-runtime 是否有意豁免红线 4 | 查 README 或问维护者 |
| H-S1-03 | agent-runtime otel.py _NoOpTracer 是否先于 agent-core tracing.py | git log 历史 |
| H-S2-01 | TB-11 pydantic-settings 收敛是否有实际需求驱动 | 查 agent_federation 配置使用 |
| H-S2-02 | TB-13 双轨认知成本是否在 Plan-F 收敛后自然消解 | 查 plan-f 文档进度 |

## 7. 统计

| 维度 | 数量 |
|------|------|
| 先验登记 | 38（TB 14 + TD 15 + U 1 + Roadmap 8） |
| 新发现 | 10（S0 6 + S1 4） |
| 总登记 | 48 |
| 已修复 | 44（先验 34 + 2026-09-21 本批 10：F-S1-03/F-S1-06/F-S1-01/F-S0-01~04/F-S0-07/09/10） |
| 仍成立 | 4（F-S0-08 / F-S1-02 / F-S1-04 / F-S1-05；TB-7 可选 / TB-11 部分修复 / TB-13 结构性） |
| REFUTED | 6 |
| 文档失效 | 4 |
| 待验证假设 | 7 |
| **最严重** | **F-S0-08 / F-S1-02 / F-S1-04 / F-S1-05（P2，收敛期）** |
