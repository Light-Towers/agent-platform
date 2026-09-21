# 03 — 上下文简报（S3）

> Tier A×4 深入接手卡 + Tier B×4 卡头 + Tier C×1 仅卡头。每卡含 30 秒定位 → 必读 3 文件 → 改动落点 → 验证命令 → 已知雷区。

## Tier A（深入接手卡）

### agent-core

**30 秒定位**：`packages/agent-core/` — 零依赖基础内核（9 能力：tracing/guardrails/llm/memory/tools/resilience/events/config/intent）。被所有 workspace 成员引用。铁律：`dependencies=[]`，重型依赖降级为 extra + 惰性导入。

**必读 3 文件**：
1. `pyproject.toml` — 零依赖声明 + extra 矩阵 + ruff select（**缺 I**，F-S0-07）
2. `agent_core/memory/__init__.py` — **P0 红线违规点**（:34 模块级 import mongo_checkpointer → langgraph 硬依赖）
3. `agent_core/resilience.py` — CircuitBreaker 引擎（:408，被 agent-runtime 继承）

**改动落点**：
- `memory/__init__.py:34` — **P0**：改为惰性导入
- `mongo_checkpointer.py:24,31` — langgraph/langchain_core 移入函数内
- `pyproject.toml:84` — ruff select 补 "I"

**验证命令**：
```bash
uv run pytest packages/agent-core/tests -q          # 19 文件，门禁内 ✓
uv run ruff check packages/agent-core/ --statistics
python -c "import agent_core.memory"                # P0 核验：无 langgraph 会 ImportError
```

**已知雷区**：
- 🔴 **F-S1-03（P0）**：memory 模块级硬依赖 langgraph + langchain_core
- 🟡 F-S0-07（P3）：ruff select 缺 I
- 🟡 `fallback_lc.py:24` 模块级 import langchain_core — 合规（可选适配 extra）

---

### agent-runtime

**30 秒定位**：`packages/agent-runtime/` — Plan-F 核心运行时中间件（成形期）。提供 Planner/Skill/SkillRegistry/Workflow/ExecutionContext/admission/coordinator/circuit_breaker/cache/tracing/otel/revert/mcp_client。依赖 agent-core + shared-schemas。

**必读 3 文件**：
1. `agent_runtime/planner/protocol.py` — Planner ABC（:561）+ ExecutionContext（:170）+ PlannerRuntime（:295）+ Plan（:71）
2. `agent_runtime/circuit_breaker.py` — CircuitBreaker（:21），**继承 agent-core** ✓
3. `agent_runtime/otel.py` — _NoOpTracer（:57），**独立实现**（F-S1-06）

**改动落点**：
- `otel.py:57` — 改为 `from agent_core.tracing import _NoOpTracer`（F-S1-06）
- `tests/test_graph_planner_dynamic.py:14` — 移除 agent_server 依赖，用 mock（F-S1-01）
- `pyproject.toml` — 补 pytest 配置（F-S0-10）

**验证命令**：
```bash
uv run pytest packages/agent-runtime/tests -q   # 12 文件 62 tests，⚠️ 门禁外（F-S0-01）
uv run ruff check packages/agent-runtime/
```

**已知雷区**：
- 🔴 F-S0-01（P1）：12 测试文件在 CI 门外
- 🟠 F-S1-01（P2）：测试反向依赖 agent_server
- 🟠 F-S1-06（P2）：_NoOpTracer 独立实现，接口不一致
- 🟡 F-S0-10（P3）：无 ruff/pytest 配置
- 🟡 `mcp_client.py:211` — TODO: MVP 桩

---

### agent_server

**30 秒定位**：`applications/agent_server/` — 根项目本体，单进程 Supervisor 平台。包名 `agent_server`（原 `app/`，2026-08-19 改名）。依赖 agent-core + shared-schemas + agent-runtime。

**必读 3 文件**：
1. `agent/graph.py` — Supervisor 图定义（route_node/rag_node/synthesize_node）
2. `planners/__init__.py` — Planner 消费入口（:19 消费 agent-runtime，:38 惰性 import agent_federation）
3. `api/routes.py` — API 端点（/query /history /import）

**改动落点**：
- `planners/unified.py:90` + `planners/__init__.py:38` — 惰性 import agent_federation（F-S1-02，收敛期可接受）
- `agent/router.py` — 路由特征已外置到 `data/route_hints.json`（TD-7 已修复）

**验证命令**：
```bash
uv run pytest tests -q                    # 82 文件，门禁内 ✓
uv run pytest tests/api -q
uv run python eval/run_eval.py            # 12 golden
```

**已知雷区**：
- 🟠 F-S1-02（P2）：惰性 import agent_federation.AgenticPlanner
- 🟡 v3 代际混合：pyproject.toml:4 描述仍为旧架构
- 🟡 测试在根 `tests/`（非 `applications/agent_server/tests/`）

---

### agent_federation

**30 秒定位**：`applications/agent_federation/` — 联邦网关编排（生产级），原名 `deepagents/`。包名 `agent-federation-app`。依赖 agent-core + shared-schemas + agent-runtime + deepagents + langchain + langgraph。

**必读 3 文件**：
1. `planners/agentic.py` — AgenticPlanner（:77），**继承 agent-runtime Planner** ✓
2. `agent/circuit_breaker.py` — CircuitBreaker（:45），**完全独立实现** ✗（F-S1-04）
3. `agent/cache/layers.py` — L1/L2/L3Cache/NullCache（:57/:105/:222/:259），独立实现 ✗

**改动落点**：
- `agent/circuit_breaker.py:45` — 收敛到 agent-runtime（F-S1-04）
- `agent/cache/layers.py` + `semantic_cache.py` — Cache 收敛（F-S1-04）
- `tests/test_auth.py` + `tests/test_semantic_memory_typed.py` — 门禁外（F-S0-03）

**验证命令**：
```bash
uv run pytest applications/agent_federation/tests/unit -q   # 15 文件，门禁内 ✓
uv run pytest applications/agent_federation/tests -q         # 19 文件（含根级 2 门禁外）
```

**已知雷区**：
- 🟠 F-S1-04（P2）：CB + 3 级 Cache 独立实现
- 🟠 F-S0-03（P2）：根级 2 测试门禁外
- 🟡 包名 `agent-federation-app` ≠ 目录名 `agent_federation`
- 🟡 `circuit_breaker.py:42` 状态常量 `HALF_OPEN="half_open"` vs agent-runtime `"half-open"`

---

## Tier B（卡头）

### zhanggui-zhiku

| 字段 | 值 |
|------|-----|
| 定位 | 掌柜智库 RAG（:8900） |
| 包名 | **app**（setuptools，F-S0-08） |
| 依赖 | agent-core（不依赖 agent-runtime/shared-schemas） |
| 测试 | 23 文件 223 tests，**全部门禁外**（F-S0-02） |
| ruff | 缺 I（F-S0-07） |
| 雷区 | 包名 `app` 导致 sys.path 遮蔽；无 pytest 依赖 |

### kefu-service

| 字段 | 值 |
|------|-----|
| 定位 | 客服迁移版（Agent Protocol 兼容） |
| 包名 | kefu_agent（hatchling） |
| 依赖 | agent-core[memory-embed-local] + shared-schemas |
| 测试 | 1 文件，门禁内 ✓ |
| 已修复 | TD-1/TD-2（graph.py:11-14 确认） |

### wenda-data-agent

| 字段 | 值 |
|------|-----|
| 定位 | Text-to-SQL |
| 包名 | wenda_data_agent（hatchling） |
| 依赖 | agent-core + shared-schemas |
| 测试 | 根 tests/wenda_data_agent/（4 文件），门禁内 ✓ |

### dialogue-framework

| 字段 | 值 |
|------|-----|
| 定位 | LLM 对话框架基础设施 |
| 包名 | dialogue_framework（hatchling） |
| 依赖 | agent-core + shared-schemas |
| 测试 | 根 tests/（5 文件门禁内）+ applications/.../tests/（1 文件门禁外 F-S0-04） |
| 已修复 | TB-1/TB-2（桥接适配） |

### exhibition-agent

| 字段 | 值 |
|------|-----|
| 定位 | 会展 Agent（新，commit d0c3800） |
| 包名 | exhibition_agent（hatchling） |
| 依赖 | agent-core（**不依赖 agent-runtime**） |
| 测试 | 12 文件，门禁内 ✓ |
| 雷区 | F-S1-05（P2）：独立实现 Skill+ExecutionContext；ARCHITECTURE.md §2.2 未列入 |

---

## Tier C（仅卡头）

### shared-schemas

| 字段 | 值 |
|------|-----|
| 定位 | 跨进程契约（QueryRequest/QueryResponse/ThreadState 等 12 类） |
| 依赖 | 仅 pydantic |
| 测试 | 无 |
| 红线 5 | 合规（提供权威契约） |

---

## 接手卡使用指南

### 改动前检查清单

1. 确认目标单元 Tier（A 深入 / B 卡头 / C 仅卡头）
2. 读必读 3 文件建立心智模型
3. 查已知雷区（特别是 P0/P1）
4. 确认验证命令（注意门禁内/外状态）
5. 查改动落点定位到 file:line

### 跨单元改动回归

```
agent-core → agent-runtime → agent_server / agent_federation
                ↑                    ↑
          （改 core 跑 runtime 测试）  （改 runtime 跑 app 测试）
```

- 改 agent-core：跑 `packages/agent-core/tests` + `packages/agent-runtime/tests` + `tests/`
- 改 agent-runtime：跑 `packages/agent-runtime/tests` + `tests/` + `applications/agent_federation/tests/unit`

### 门禁外测试提醒

以下目录**不在 `make ci` 内**，改动后需手动验证：

| 目录 | 文件数 | 手动验证命令 |
|------|--------|-------------|
| packages/agent-runtime/tests/ | 12 | `uv run pytest packages/agent-runtime/tests -q` |
| applications/zhanggui-zhiku/tests/ | 23 | `uv run pytest applications/zhanggui-zhiku/tests -q` |
| applications/agent_federation/tests/（根级） | 2 | `uv run pytest applications/agent_federation/tests -q` |
| applications/dialogue-framework/tests/ | 1 | `uv run pytest applications/dialogue-framework/tests -q` |
