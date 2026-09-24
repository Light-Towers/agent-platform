# 01 — 架构摸底（S1）

> 五条红线逐条审计 + 11 单元架构卡 + 再造 Runtime 专项。

## 1. 五条红线逐条审计（判据：ARCHITECTURE.md L79-85）

### 红线 1：Package 互不可反向依赖

| 方向 | 结论 | 证据 |
|------|------|------|
| agent-core → agent-runtime/app | **合规** | 零命中 |
| agent-runtime(生产) → app | **合规** | admission.py:15 是注释 |
| agent-runtime(测试) → agent_server | **CONFIRMED 违规** | test_graph_planner_dynamic.py:14 |

### 红线 2：Application 不得互相 import 内部模块

| 方向 | 结论 | 证据 |
|------|------|------|
| agent_federation → 其他 app | **合规** | 零命中 |
| agent_server → agent_federation | **CONFIRMED 违规**（惰性） | planners/unified.py:90, __init__.G.py:38 |

### 红线 3：agent-core 内核零宿主依赖

| import 位置 | 类型 | 结论 |
|------------|------|------|
| memory/__init__.py:34 → mongo_checkpointer.py:24,31 | **模块级** | **P0 硬违规** |
| llm/fallback_lc.py:24 | 模块级 | 合规（可选适配 extra） |
| monitor.py:232 / memory/__init__.py:84,108 / llm/embedding.py:34,52 / llm/providers.py:65 | 函数1内惰性 | 合规 |

### 红线 4：禁止再造 Runtime

| 单元 | 消费情况 | 结论 |
|------|---------|------|
| agent_server Planner | 继承 agent_runtime.Planner | 合规 ✓ |
| agent_federation Planner | 继承 agent_runtime.Planner | 合规 ✓ |
| agent_federation CircuitBreaker | 完全独立实现 | 违规 ✗（已知） |
| agent_federation Cache | 独立实现 L1/L2/L3 | 违规 ✗（已知） |
| exhibition-agent Skill | 独立实现 | 违规 ✗（新发现） |
| exhibition-agent ExecutionContext | 独立实现 |8 | 违规 ✗（新发现） |

### 红线 5：跨进程通信走 shared-schemas

**合规** ✓Eapplications 无自定义 Request/Response/QueryResponse/ThreadState/Event。

## 2. 架构卡（11 单元分 Tier）

### Tier A（深入）

#### agent-core
- 定位：零依赖基础内核（9 能力）
- 必读：pyproject.toml（dependencies=[]）, memory/__init__.py（**P0 违规点**）, resilience.py（CircuitBreaker 引擎）
- 红线 3：1 处 P0 硬违规（F-S1-03）
- 测试：19 文件（门禁内 ✓） / ruff 缺 I

#### agent-runtime
- 定位：Plan-F 核心运行时（成形期）
- 必读：planner/protocol.py（Planner ABC + ExecutionContext，555 行最大热点）, circuit_breaker.py（继承 agent-core）, otel.py（_NoOpTracer 独立实现）
- 红线 1：1 处测试违规 / _NoOpTracer 重复
- 测试：12 文件 62 tests（**门禁外** P1）

#### agent_server
- 定位：根项目本体，Supervisor 平台
- 必读：agent/graph.py, planners/__init__.py（消费 agent-runtime）, api/routes.py
- 红线 2：2 处惰性 import agent_federation
- 测试：根 tests/ 82 文件（门禁内 ✓）

#### agent_federation
- 定位：联邦网关编排（生产级）
- 必读：planners/agentic.py（继承 agent-runtime ✓）, agent/circuit_breaker.py（独立实现 ✗）, agent/cache/layers.py（3 级缓存独立 ✗）
- 红线 4：CircuitBreaker+Cache 独立实现
- 测试：19 文件（unit 15 门禁内，根级 2 门禁外）

### Tier B（卡头）

#### shared-schemas
- 定位：跨进程契约（QueryRequest/QueryResponse/ThreadState 等 12 类）
- 依赖：仅 pydantic / 无测试 / 无 ruff 配置
- 红线 5：合规（提供权威契约）

#### kefu-service
- 定位：客服迁移版 / 测试 1 文件门禁内 ✓ / TD-1 已修复

#### wenda-data-agent
- 定位：Text-to-SQL / 测试在根 tests/ 下（门禁内 ✓）

#### dialogue-framework
- 定位：对话框架 / 测试 5 文件门禁内 + 1 文件门禁外 / TB-1/TB-2 已修复

#### exhibition-agent
- 定位：会展 Agent（新，d0c3800）/ 不依赖 agent-runtime / 独立实现 Skill+ExecutionContext（红线 4 违规）/ 测试 12 文件门禁内 ✓

### Tier C（仅卡头）

#### zhanggui-zhiku
- 定位：掌柜智库 RAG（~110 文件，独立度最高）
- 包名 **app**（setuptools，非 hatchling）— sys.path 遮蔽风险
- 测试 23 文件 223 tests（**全部门禁外** P1）
- 无 pytest 依赖 / 无 testpaths / ruff 缺 I

## 3. 再造 Runtime 专项

### CircuitBreaker ×3

| 层 | 继承 | 状态常量 | 判定 |
|----|------|---------|------|
| agent-core | 基类 | HALF_OPEN（下划线） | 引擎 |
| agent-runtime | **继承 agent-core** | "half-open"（连字符） | 合规适配 ✓ |
| agent_federation | **无继承** | "half_open"（下划线） | 违规再造 ✗ |

### _NoOpTracer ×2

| 层 | 接口 | 判定 |
|----|------|------|
| agent-core | `start_span(name, *args, **kwargs)`, `__slots__` | 权威 |
| agent-runtime | `start_span(name, **kwargs)`, 无 `__slots__` | 独立实现 ✗ |

### exhibition-agent 是否为第二套 Runtime？

exhibition-agent 自带 graph/ + middleware/ + observability/ + skills/ + contract/，不依赖 agent-runtime。**是第二套 Runtime 的首要嫌疑**（F-S1-05），但可能有意作为独立工程豁免红线 4（H-S1-02 待拍板）。
