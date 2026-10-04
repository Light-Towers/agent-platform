# Agent Platform 架构总图（Monorepo 分层契约）

> 本文是仓库顶层的**架构契约（Architecture Contract）**，定义目录分层、依赖方向与不可逾越的红线。
> 具体的两两边界调研见 `docs/architecture-boundary-*.md`，本文是它们的上位汇总，不重复细节。
>
> 状态：2026-08-19 确立并**已落地物理分层**（初版仅固化契约，同日完成目录搬移 + `app`→`agent_server` 改名）。

## 1. 核心论断：本仓库是「Platform + Applications」的 monorepo

根目录的 16 个顶层条目其实分属两类，**视觉平铺导致误判为同级架构层**：

- **Packages（平台基础设施）**：`agent-core`、`agent-runtime`、`shared-schemas`
  —— 它们是**库**，被其它成员以 `workspace = true` 依赖引用（见根 `pyproject.toml` 的 `[tool.uv.sources]`）。
- **Applications（应用 / 产品）**：`agent_server`、`agent_federation`、`exhibition-agent`、`kefu-service`、`nl2sql-service`、`knowledge-service`
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
agent-core  agent-runtime  shared-schemas  agent-server  agent_federation  exhibition-agent
 (基础原语)   (执行模型)     (数据契约)         kefu-service  nl2sql-service  knowledge-service
```

### 2.1 Packages（平台基础设施，仅 3 个）

| 目录 | 定位 | 职责 | 稳定性 |
|------|------|------|--------|
| `agent-core` | **基础 Agent 能力内核** | logging / tracing / metrics / llm / memory（含 MemoryStore 统一门面） / tools / guardrails / resilience / events（EventBus 多 sink 扇出） / config（KernelConfig + 类型化 env 解析） / intent（L1 分类器） | 稳定、底层、框架无关（不得 import 任何宿主） |
| `agent-runtime` | **Agent 执行 / 组合运行时** | Planner / Plan / Skill（Function/Agent/Remote/Workflow 四型 SkillKind，MCP/Sandbox 经特化注册函数挂载） / SkillRegistry / Workflow / ExecutionContext / ExecutionRuntime / Sandbox | 重点建设，架构收口完成 |
| `shared-schemas` | **跨边界数据 / 协议契约** | Request / Response / Event / Error / Protocol DTO | 稳定，跨进程通信单一事实来源 |

> `agent-core` 提供**零件**，`agent-runtime` 把零件**组装成执行引擎**。二者不可反向依赖。
> `shared-schemas` 与 `agent-core` 并列：前者是「数据/协议基础设施」，后者是「行为/能力基础设施」。

### 2.2 Applications（应用，独立部署）

| 目录 | 定位 | 部署形态 |
|------|------|----------|
| `agent_server` | 默认宿主 / 单进程 Supervisor 平台参考应用 | 根 `docker-compose.yml` 编排，:8000 |
| `agent_federation` | 多 Agent 联邦网关编排系统（生产级） | 自带 `docker-compose.yml` + 全套可观测栈 |
| `exhibition-agent` | 会展行业 AI Agent（平台侧骨架；按跨项目接口契约 v1.2 接入 mingyang-warehouse） | 独立部署 |
| `kefu-service` / `nl2sql-service` / `knowledge-service` | 联邦下游子服务 / 领域应用 | 各自独立部署 |

> `agent_server` 不是「平台层」，而是「使用平台能力的应用」（默认 Runtime 宿主）。
> `agent_federation` 是**独立 Agent 应用**，不是 `agent-runtime` 的底层模块。

### 2.3 横切：服务端断言的租户身份层（2026-10-01 随 `integration/v3-into-main` 合流入库）

身份/租户是横切关注点，按「单一实现 + 全局装配 + 强制门禁」三层记录，缺一层即退化为约定：

| 层 | 实现 | 说明 |
|----|------|------|
| **单一实现** | `packages/agent-runtime/agent_runtime/identity.py` | RS256 `mint_token`/`verify_token`、网关→子服务内部头 `sign_internal_header`/`verify_internal_header`（HMAC-SHA256）、`load_public_keys`（kid→PEM，支持轮转）、`resolve_startup_tenant_mode`、`require_identity_startup_guard`。PyJWT 仅挂在 `agent-runtime` 的 `identity` extra，**不进 `agent-core`**（红线 1）。漏传租户的哨兵拦截在内核 `packages/agent-core/agent_core/memory/_tenant_gate.py`。 |
| **全局装配** | `packages/agent-runtime/agent_runtime/identity_middleware.py` | 纯 ASGI `IdentityMiddleware`，在 `applications/agent_server/main.py`（无条件）与 `applications/agent_federation/api/identity_bridge.py`（`X-Tenant-JWT`）挂载；**默认 observe 档零行为变更**（无凭据请求交下游既有语义）。**接线序属装配语义的一部分**：联邦侧 `mount_identity_middleware` 必在 `SecurityGuardsMiddleware` **之后**注册（Starlette 后注册者更外层）且 guards 传 `subject_provider=get_asserted_tenant_context`，否则限流/护栏执行时主体尚未绑定而退 IP 兜底；由 `applications/agent_federation/tests/unit/test_identity_guards_order.py` 以 AST + 行为双向锁住。 |
| **强制门禁** | `docs/adr/0006-isolation-dimension-contract.md`、`docs/adr/0007-server-asserted-tenant-identity.md` + `tests/governance/` | 红线用例：`test_identity_not_in_tool_schema.py`（身份不得进 LLM tool schema）、`test_tenant_default_forbidden.py`（`tenant_id="default"` 隐式缺省回潮即失败）、`test_isolation_dimension_contract.py`（每张业务表必含 `tenant_id`）；跨租户真 DB 行为级回归见 `tests/ha/test_tenant_isolation_real_pg.py`（CI 缺 PG = FAIL，不得以 skip 凑绿）。 |

**运行档位**：身份相关 env 共 12 项（清单见 `.env.example` 「租户身份断言」段）。**fail-fast 默认关**：`DEPLOY_ENFORCE_IDENTITY=false` 时零依赖冒烟不受影响；置 `true` 且既未配验签公钥又未显式声明 `SINGLE_TENANT` 则拒绝启动（2026-10-01 双向实跑：默认档 `agent_server.main:app` 构造成功且中间件栈含 `IdentityMiddleware`；开关置 true 则 `RuntimeError`）。执行细节见 `docs/plans/plan-isolation-hardening-2026-09-27.md`。

**与 CodeQL B7b 的关系（已合流）**：本身份层解决 **tenant 维**由服务端断言；`py/weak-sensitive-data-hashing` 的 `#38`/`#39` 源于会话身份仍在用「凭据摘要当标识」。B7b-4 已把会话身份接到本层的断言值（`resolve_thread_identity(principal)`，产物 `tenant-<主体>`、**不做摘要**）⇒ 会话身份不再是独立于本层的第二套身份机制，而是本层的一个消费者；**用户级（principal_id）细化仍待 A5 批次**，在本层之上替换主体来源。

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
▼          ▼          ▼        ▼          ▼          ▼
         agent-server  agent_federation  exhibition  kefu  nl2sql  knowledge
        (applications 仅向下依赖 packages)
```

**唯一合法依赖方向**：`application → agent-runtime → agent-core`，且任意层均可依赖 `shared-schemas`。

## 4. 架构红线（不可逾越）

1. **Package 互不可反向依赖**：`agent-core` 不得 import `agent-runtime` / `agent_server` / 任何 application；`agent-runtime` 不得 import 任何 application。
2. **Application 不得互相 import 内部模块**：`agent_federation` 不得 `import agent_server.`；各 application 仅通过 HTTP + `shared-schemas` 契约交互。
3. **`agent-core` 内核零宿主依赖**：不得 import `agent_server.core.config`、LangGraph、FastAPI 等宿主/PaaS 依赖（设计铁律）。
4. **禁止再造 Runtime**：任何 application（`agent_federation` 等）需要的 Planner / Skill / Workflow，应从 `agent-runtime` 消费，不得另起一套执行引擎。
5. **跨进程通信必须走 `shared-schemas`**：Request / Response / Event 不得各自定义导致字段漂移。

### 4.1 强制门禁登记表（lint 不变量，计入 `make ci`）

> 约定只靠自觉迟早被破窗，故每条横切收敛都对应一条全仓扫描 + 白名单的不变量，实现在 `scripts/lint_architecture.py`，违规直接 CI 失败。「消除 CodeQL 告警」不是目的，**防止同类问题再长出来**才是，故第③列记录被锁住的告警形状。

| 编号 | 不变量（白名单外即失败） | 锁住的告警形状 | 治理用例 |
|------|------------------------|------------------|----------|
| P4-2 | `registry.execute()` 只能经 `delegate()` 调用 | Skill 组合绕过运行时契约 | — |
| P2 | 生产 `FastAPI(` 必须经 `agent_core` 的 `build_api_app` | 异常处理/错误信封装配漏接 | — |
| P5 | workspace 成员间不得顶层包名重复 | editable `.pth` 解析取决于安装顺序 | — |
| P6 | 密钥类标识不得裸用 `hashlib`；**已退役的四个「凭据→摘要」入口名不得再现**（B7b-5 后白名单为空：kernel 单一实现已删） | `py/weak-sensitive-data-hashing` 的散点源头 + 改名绕过 / 死代码复生 | `tests/governance/test_thread_identity_migration.py` |
| P6-3 | 「凭据→摘要」入口名（含旧 `legacy_thread_id`）以调用/定义形式出现即失败（取代已作废的 P6-2「仅定义处+迁移脚本可调」：被治理对象已消失 ⇒ 门禁换代） | 同名旧实现被加回来 ⇒ 同一告警重现 | `tests/governance/test_thread_identity_migration.py` |
| P7 | 路径 containment 必走 `guardrails.fs`；api 层文件 I/O 必过 `safe_join`/`resolve_within` | `py/path-injection`、`py/clear-text-logging-sensitive-data` | `tests/governance/test_path_io_governance.py` |
| P8 | 对外响应体（HTTP JSON / SSE 帧）不回显异常消息或堆栈 | `py/stack-trace-exposure` | `tests/governance/test_exception_echo_governance.py` |
| P9 | app 层禁裸调 `monitor.report_tool*`（散点埋点） | 工具观测断点（v3 合流并入） | — |
| P10 | 禁 `from tools.*` 直引 `@tool` 绕过 `get_tool()` | 同上（v3 合流并入） | — |
| P11 | 根 `.github/workflows/*.yml` 必须声明顶层 `permissions:` 块 | `actions/missing-workflow-permissions`（GITHUB_TOKEN 未限权） | `tests/governance/test_workflow_permissions_governance.py` |
| P12 | 绑 `Depends(verify_api_key)` 的形参**值不得作为任何 `Call` 的实参外流**（仅扫 `applications/**`，无白名单） | 凭据被当审计主体/日志字段（**CodeQL 未报**，人工语义审计发现） | `tests/governance/test_audit_operator_principal.py` |

P11 只认顶层块：未声明 `permissions` 的 job 会回落到组织/仓库默认（常为读写），job 级声明易漏且不可核。背景与判定口径见 `docs/plans/plan-codeql-batch7-no-dismiss-real-fixes-2026-10-01.md` §7。

P12 是**名匹配粗筛**，不得当作「凭据不入审计」的全局完备门禁：抓不到「先赋给别名/属性再传」的间接流，也抓不到 `return` 等其它外流形状；kernel 侧对凭据的处理归 P6。行为面由上表用例与人工语义审计补齐。背景见 `docs/plans/plan-audit-operator-principal-2026-10-03.md` §4.3。

### 4.2 合入后复验脚本（判据 6 形态，必须可原样重跑）

> 门禁 lint 管「未来不再长出来」，本节管「合入后的结论能不能被第三者重跑」。账面把某些验收写成「任何一次合入后必须在新 tip 上重跑」的指针 ⇒ 指针所指脚本**必须在仓内**，否则判据只在某台机器的工作副本上成立（原住址 .codeartsdoer/temp 不是仓内路径——被根 `.gitignore` 的 `.*/` 规则整目录忽略，新克隆上不存在）。

| 路径 | 职责 | 是否访问网络 |
|------|------|--------------|
| `scripts/evidence/verify_main_tip.py` | 判据 6 七项 `[A]`–`[G]` 全 fail-closed 复验；门禁预期集按 `on.push.paths` × changed paths **派生**（不硬编码） | 是（`gh api`） |
| `scripts/evidence/normalize_dump.py` | PowerShell 重定向产物默认 UTF-16 LE ⇒ 按 BOM 嗅探转 UTF-8，防「肉眼正常而计数全 0」 | 否 |
| `scripts/evidence/README.md` | 收录判据、可直接复制的运行命令、三条实踩过坑 | — |
| `tests/governance/test_evidence_scripts.py` | 钉住派生式预期集的纯逻辑不变量（含 `jobs:` 位于文件末尾、YAML 1.1 `on:`→布尔 `True` 键、PyYAML 缺席必 exit 2） | 否（autouse 拦断子进程） |

口径三条：① 退出码 `2` = **前置不可用**（依赖缺失 / `gh` 调用失败），从不折算成通过；② 预期 check 名一律派生，硬编码两个方向都会错（该跑的没进集合 ⇒ 红了没人看；不该跑的写进集合 ⇒ 等不到而误判未达成）；③ 本目录受 `scripts/check_doc_sync.py` 的文件引用存在性校验覆盖（本节即登记位），引用失效即 CI 红。方案与验收：`docs/plans/plan-evidence-scripts-intake-2026-10-04.md`。

## 5. 当前已知技术债（登记，非本期处理）

- **【2026-09-27 新增】记忆层契约缺位：`agent-runtime` 自建执行记忆**：`memory` 的法定归属是 `agent-core`（§2.1 明列「含 MemoryStore 统一门面」），且内核已声明「各子包不得再各自为政重复实现」（`agent_core/memory/__init__.py:20-21`）。但内核现有契约**只覆盖语义记忆**（`store.py` 的 `MemoryStore` 五动词与 `CapabilityReport` 均无 episodic/procedural/working 能力位），对执行记忆零覆盖 → `agent-runtime` 只能在包内自建 8 个 `memory_*.py`（对 `agent_core` 的 import 数为 0）。
  - **定性**：不是重复实现，是**内核能力缺位导致的必然自建**。语义记忆那条线（`agent_federation` 与 `agent_server` 双侧均走 `agent_core.memory.typed`）已证明——内核一旦提供契约，两侧会自然收敛。
  - **附带**：`agent_server` 单进程内并行两套记忆（语义走 `longterm.py`→内核 `memories` 表；执行走 `main.py`→runtime `episodic_memories`/`procedural_memories` 表）；`UserSemanticStore`/`SharedSemanticStore` 无生产实现；`episodic` 在两层同名不同义。
  - **处置**：`docs/adr/0005-execution-memory-kernel-contract.md`（**已采纳**，2026-09-27 提案 / 2026-10-02 随 T0 入主干转正；T0 已落地：`agent_core/memory/execution.py` 下沉 `EpisodicStoreProtocol`/`ProceduralStoreProtocol`，纯 stdlib + `_tenant_gate` 零反向依赖；`CapabilityReport` 补 `supports_episodic`/`supports_procedural`/`supports_working`；runtime 实现零基类改动即满足协议）。执行细节见 `docs/plans/plan-memory-hardening-2026-09-27.md`（T0 已收口；T8/UserSemanticStore 待收口）。
- **【2026-09-27 新增】隔离维度无统一契约，且部分表缺 `tenant_id`**：七类表存在四种隔离组合（`chunks`/`sql_*` 仅 `workspace_id`；`memories` 为 `tenant_id`+`user_id`；`execution_queue`/`rate_limit_buckets`/`cost_records` 仅 `tenant_id`；`episodic_memories`/`procedural_memories` 无隔离列）。
  - **定性**：`workspace_id` 是**归属维度**（客户端传入、默认 `default`、无 `workspaces` 归属表可证明其租户归属），**不可单独承担隔离**；`tenant_id` 才是**安全边界**（服务端 ContextVar 断言）。
  - **定级（2026-09-27 已确认多租户部署）**：`chunks`（RAG 文档切片）与 `sql_ddl`/`sql_docs`/`sql_examples` 仅靠 workspace 隔离 → **跨租户可见为现实风险（活跃 P0）**；`workspace_id` 无归属校验（活跃 P0）；`memories.user_id` 位实装 `workspace_id`（TD-13）致用户维度缺失（用户已拍板画像层必须存在，P0）；knowledge-service `tenant_id` 默认空可选（P1）。
  - **处置**：`docs/adr/0006-isolation-dimension-contract.md`（**已采纳**：tenant 为边界、workspace/user/knowledge 为正交归属；`procedural_memories` 定级「租户内共享、跨租户隔离」）。执行见 `docs/plans/plan-isolation-hardening-2026-09-27.md`（T9–T13）。
- **【2026-10-01 新增】身份中间件未覆盖全部应用（§2.3 的「全局装配」层目前只覆盖 2/6 应用）**：`IdentityMiddleware` 仅在 `agent_server` 与 `agent_federation` 无条件挂载；knowledge-service 走自有的 `TenantHeaderMiddleware`（`applications/knowledge-service/knowledge_service/main.py`）；exhibition-agent / kefu-service / nl2sql-service **未接入**（入口 grep `IdentityMiddleware|add_middleware` 命中 0）。后果：observe 档下行为不变（安全），但 `TENANT_JWT_ENFORCE` 灰度末硬切换时，未接入的应用仍会接受客户端自报 tenant。处置：切换前须先把三个应用纳入同一装配，再加一条 `scripts/lint_architecture.py` 不变量防未来新增 app 漏接。装配上收点待定：`agent_core.guardrails.app_factory.build_api_app` 是其天然位置，但该文件 docstring 明写「不强推鉴权语义，避免改变各 app 行为」——收口需先修订该约定，不得默默反向。
- **`agent_federation` 自有 planner**：应用层 `agent_federation` 仍实现独立 planner/agent，需随 runtime 成形逐步收敛到红线 4。
- **dialogue-framework 已移除**（2026-09-23，孤儿框架，能力已被 agent_server 吸收）。
- **历史命名残留**：`docs/architecture/architecture-boundary-app-vs-agent-federation.md` 中仍出现的 `deepagents/` 旧名，已于 2026-08-19 清理为 `agent_federation/`；本文统一使用新名。

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
│   ├── exhibition-agent/
│   ├── kefu-service/
│   ├── nl2sql-service/
│   └── knowledge-service/
├── tests/                   # 根项目测试（测 agent_server）
├── docs/  scripts/  eval/   # 仓库级
└── pyproject.toml / Dockerfile / Makefile / docker-compose.yml
```

> 注：`agent_server`（原 `app`）是**根项目本体**，不是独立 workspace 成员（无自身 `pyproject.toml`），由根 `pyproject.toml` 的 `[tool.hatch.build.targets.wheel] packages=["applications/agent_server"]` 管理；其余 5 个 applications 是独立成员。
> 物理分层 + `app`→`agent_server` 改名已于 2026-08-19 完成，`uv sync --all-packages --extra dev` 通过、`uvicorn agent_server.main:app` 可导入。
