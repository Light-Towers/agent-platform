# Agent Platform 架构总图（Monorepo 分层契约）

> 本文是仓库顶层的**架构契约（Architecture Contract）**，定义目录分层、依赖方向与不可逾越的红线。
> 具体的两两边界调研见 `docs/architecture-boundary-*.md`，本文是它们的上位汇总，不重复细节。
>
> 状态：2026-08-19 确立并**已落地物理分层**（初版仅固化契约，同日完成目录搬移 + `app`→`agent_server` 改名）。

## 1. 核心论断：本仓库是「Platform + Applications」的 monorepo

根目录的 13 个顶层条目其实分属两类，**视觉平铺导致误判为同级架构层**：

- **Packages（平台基础设施）**：`agent-core`、`agent-runtime`、`shared-schemas`
  —— 它们是**库**，被其它成员以 `workspace = true` 依赖引用（见根 `pyproject.toml` 的 `[tool.uv.sources]`）。
- **Applications（应用 / 产品）**：`app`（拟改名 `agent-server`）、`agent_federation`、`dialogue-framework`、`kefu-service`、`wenda-data-agent`、`zhanggui-zhiku`
  —— 它们是**独立可部署单元**，各自带 `pyproject.toml` / `Dockerfile` / `docker-compose.yml` / `README`。

目录平铺是历史遗留；逻辑分层早已由 `uv workspace` 隐式承认（仅 3 个 packages 出现在 `[tool.uv.sources]`）。

## 2. 分层模型

```text
                         agent-platform  (monorepo)
                                   │
              ┌────────────────────┴────────────────────┐
              │                                         │
        Packages (平台 SDK)                       Applications (应用)
              │                                         │
    ┌─────────┼──────────┐                  ┌────────────┼─────────────┐
    │         │          │                  │            │             │
agent-core  agent-runtime  shared-schemas  agent-server  agent_federation  dialogue-framework
 (基础原语)   (执行模型)     (数据契约)         kefu-service  wenda-data-agent  zhanggui-zhiku
```

### 2.1 Packages（平台基础设施，仅 3 个）

| 目录 | 定位 | 职责 | 稳定性 |
|------|------|------|--------|
| `agent-core` | **基础 Agent 能力内核** | logging / tracing / metrics / llm / memory（含 MemoryStore 统一门面） / tools / guardrails / resilience / events（EventBus 多 sink 扇出） / config（KernelConfig + 类型化 env 解析） / intent（L1 分类器） | 稳定、底层、框架无关（不得 import 任何宿主） |
| `agent-runtime` | **Agent 执行 / 组合运行时** | Planner / Plan / Skill / SkillRegistry / Workflow / ExecutionContext / ExecutionRuntime | 重点建设，当前仍在成形期 |
| `shared-schemas` | **跨边界数据 / 协议契约** | Request / Response / Event / Error / Protocol DTO | 稳定，跨进程通信单一事实来源 |

> `agent-core` 提供**零件**，`agent-runtime` 把零件**组装成执行引擎**。二者不可反向依赖。
> `shared-schemas` 与 `agent-core` 并列：前者是「数据/协议基础设施」，后者是「行为/能力基础设施」。

### 2.2 Applications（应用，独立部署）

| 目录 | 定位 | 部署形态 |
|------|------|----------|
| `app` → **`agent-server`**（拟改名） | 默认宿主 / 单进程 Supervisor 平台参考应用 | 根 `docker-compose.yml` 编排，:8000 |
| `agent_federation` | 多 Agent 联邦网关编排系统（生产级） | 自带 `docker-compose.yml` + 全套可观测栈 |
| `dialogue-framework` | 对话领域框架 / 上层对话引擎 | 独立 package，当前主供内部 |
| `kefu-service` / `wenda-data-agent` / `zhanggui-zhiku` | 联邦下游子服务 / 领域应用 | 各自独立部署 |

> `app` 不是「平台层」，而是「使用平台能力的应用」。改名 `agent-server` 以明确其为「默认 Runtime 宿主」。
> `agent_federation` / `dialogue-framework` 是**独立 Agent 应用 / 领域框架**，不是 `agent-runtime` 的底层模块。

## 3. 依赖方向（红线依据）

```text
                         ┌───────────────────┐
                         │  shared-schemas   │  (数据契约，被所有人依赖)
                         └─────────▲─────────┘
                                   │
                         ┌─────────┴─────────┐
                         │                   │
                  ┌──────┴──────┐     ┌─────┴──────┐
                  │ agent-core  │◄────│agent-runtime│  (runtime 依赖 core 原语)
                  └──────▲──────┘     └──────▲──────┘
                         │                   │
              ┌──────────┼──────────┬────────┼──────────┐
              │          │          │        │          │
              ▼          ▼          ▼        ▼          ▼
        agent-server  agent_federation  dialogue  kefu  wenda  zhiku
        (applications 仅向下依赖 packages)
```

**唯一合法依赖方向**：`application → agent-runtime → agent-core`，且任意层均可依赖 `shared-schemas`。

## 4. 架构红线（不可逾越）

1. **Package 互不可反向依赖**：`agent-core` 不得 import `agent-runtime` / `app` / 任何 application；`agent-runtime` 不得 import 任何 application。
2. **Application 不得互相 import 内部模块**：`agent_federation` 不得 `import app.`；各 application 仅通过 HTTP + `shared-schemas` 契约交互。
3. **`agent-core` 内核零宿主依赖**：不得 import `app.core.config`、LangGraph、FastAPI 等宿主/PaaS 依赖（设计铁律）。
4. **禁止再造 Runtime**：任何 application（`dialogue-framework` / `agent_federation` 等）需要的 Planner / Skill / Workflow，应从 `agent-runtime` 消费，不得另起一套执行引擎（当前 `agent-runtime` 仍在成形期，是收敛窗口）。
5. **跨进程通信必须走 `shared-schemas`**：Request / Response / Event 不得各自定义导致字段漂移。

## 5. 当前已知技术债（登记，非本期处理）

- **`agent-runtime` 未长成**：应用层（`dialogue-framework`、`agent_federation`）各自实现 planner/agent，需随 runtime 成形逐步收敛到红线 4。
- **协议冗余**：DF 自有 `BaseChatClient` 与 `agent-core` 的 `BaseLLMProvider` 并存；DF `Tracker` 与 `agent_core.memory` 两套会话抽象。详见 `docs/architecture-boundary-agent-core-vs-dialogue-framework.md`。
- **历史命名残留**：`docs/architecture-boundary-app-vs-agent-federation.md` 中仍出现的 `deepagents/` 旧名，已于 2026-08-19 清理为 `agent_federation/`；本文统一使用新名。

> 2026-08-20 更新：WS-1~WS-8 八工作流全量落地后，内核记忆/可靠性/可观测/配置/意图/Skill 中间件/LLM 缓存八大维度已收敛，详见 CHANGELOG 对应条目。兼容期为一个小版本（弃用路径保留 + DeprecationWarning），下轮清理专项删除。

## 6. 当前实际结构（2026-08-19 已落地）

```text
agent-platform/
├── packages/                # 平台 SDK，被 workspace=true 依赖
│   ├── agent-core
│   ├── agent-runtime
│   └── shared-schemas
├── applications/            # 独立可部署应用
│   ├── agent_server/       # (原 app/，根宿主，包名同步 agent_server)
│   ├── agent_federation/
│   ├── dialogue-framework/
│   ├── kefu-service/
│   ├── wenda-data-agent/
│   └── zhanggui-zhiku/
├── tests/                   # 根项目测试（测 agent_server）
├── docs/  scripts/  eval/   # 仓库级
└── pyproject.toml / Dockerfile / Makefile / docker-compose.yml
```

> 注：`agent_server`（原 `app`）是**根项目本体**，不是独立 workspace 成员（无自身 `pyproject.toml`），由根 `pyproject.toml` 的 `[tool.hatch.build.targets.wheel] packages=["applications/agent_server"]` 管理；其余 5 个 applications 是独立成员。
> 物理分层 + `app`→`agent_server` 改名已于 2026-08-19 完成，根 `pytest` 17 passed、`uv sync` 通过、`uvicorn agent_server.main:app` 可导入。
