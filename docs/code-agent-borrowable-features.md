# 编码型 Agent 工程化特性可借鉴性调研（2026-08-12）

> 状态：专项调研，回答用户提问——"自建的项目，那些 code 项目（claude code、codex、opencode）里有哪些特性是可以借鉴的？"
> 所有源码结构均于 2026-08-12 通过 GitHub API 实证核实（仓库目录树 + 关键文件内容），非模型记忆。
> 承接 `spec.md`（本项目定位：工程化优先的多源证据问答 Agent 运行时）+ `research-proposal.md` + `competitive-landscape.md` + `low-code-feasibility-analysis.md`。

---

## 〇、调研边界与定位前提

**本项目定位**（spec.md 1.1）：工程化优先的多源证据问答 Agent 运行时——Supervisor + Search/RAG/Text-to-SQL 三能力路由，单进程多节点，**不是编码型 Agent**。

**spec.md 1.4 已显式排除**：代码库操作 / 编码型 Agent（不读写用户代码库、不执行 lint/test/build、不做 git 提交、不委派编码子代理）。

**借鉴分类原则**：
- ✅ **可借鉴**：工程化特性（流式协议、会话管理、工具授权、上下文压缩、检查点、可观测、配置模型、沙箱思想、HITL、subagent 委派机制、MCP 集成等）——与"问答"正交，是运行时基础设施。
- ❌ **不可借鉴**：编码能力本身（文件读写编辑、shell 执行、代码库映射、git 操作、repomap、apply-patch、ripgrep、LSP 等）——不在本项目职责边界。

---

## 一、三 code 项目基线（2026-08-12 GitHub API 实证）

| 项目 | 仓库 | Stars | License | 语言 | 架构形态 |
|------|------|-------|---------|------|---------|
| **Claude Code** | `anthropics/claude-code` | 141,102 | 闭源（npm 分发） | Node.js | CLI + IDE 插件 + GitHub 集成；仓库仅含 plugins/examples/scripts，主体闭源 |
| **OpenAI Codex CLI** | `openai/codex` | 105,381 | Apache-2.0 | Rust（codex-rs）+ Node.js（codex-cli） | CLI + app-server daemon + cloud-tasks；Rust monorepo 80+ crate |
| **OpenCode** | `anomalyco/opencode`（原 sst/opencode） | 196,270 | MIT | TypeScript（Bun） | TUI + Web + Desktop + server；monorepo packages/ 30+ 包，V2 Session Core |

> 三者均为**编码型 Agent**（理解代码库、读写文件、执行 shell、git 操作），定位与本项目不同。本调研只提取其**工程化运行时特性**。

---

## 二、Claude Code 工程化特性（实证来源：README + plugins/README.md + plugins/ 目录树 + .claude/ 目录）

### 2.1 实证特性清单

| # | 特性 | 实证来源 | 性质 |
|---|------|---------|------|
| C1 | **插件体系** | `plugins/README.md`：标准化结构 `plugin.json + commands/ + agents/ + skills/ + hooks/ + .mcp.json`，可跨项目/团队共享，社区 marketplace 分发 | 工程化（扩展机制） |
| C2 | **Slash 命令** | `plugins/*/commands/`：用户自定义命令（/commit、/code-review、/feature-dev、/ralph-loop 等） | 工程化（交互） |
| C3 | **Subagent / 专用 agent 委派** | `plugins/*/agents/`：code-explorer、code-architect、code-reviewer、agent-sdk-verifier-py/ts、conversation-analyzer 等 | 工程化（委派） |
| C4 | **多 agent 并行** | `plugins/code-review/`：5 个并行 Sonnet agent 做不同维度审查（CLAUDE.md 合规、bug、历史上下文、PR 历史、代码注释） | 工程化（并行编排） |
| C5 | **Skills 自动触发** | `plugins/frontend-design/`：skill auto-invoked for frontend work；`plugins/claude-opus-4-5-migration/` | 工程化（领域知识注入） |
| C6 | **生命周期 Hooks** | `plugins/*/hooks/`：SessionStart、PreToolUse、Stop 事件钩子（explanatory-output-style 用 SessionStart 注入教育上下文；security-guidance 用 PreToolUse 监控 9 种安全模式；ralph-wiggum 用 Stop 拦截退出） | 工程化（生命周期） |
| C7 | **MCP 集成** | 插件结构含 `.mcp.json`（外部工具配置） | 工程化（协议） |
| C8 | **CLAUDE.md 项目级指令** | 业界熟知规范 + 仓库 `.claude/` 目录 | 工程化（配置） |
| C9 | **上下文压缩 compact** | 业界熟知 `/compact` 命令 | 工程化（上下文管理） |
| C10 | **权限模型 / HITL** | 业界熟知工具级审批 + 人在回路 | 工程化（安全） |
| C11 | **检查点 / 会话恢复** | 业界熟知 `--resume` | 工程化（持久化） |
| C12 | **自引用循环** | `plugins/ralph-wiggum/`：/ralph-loop 自主迭代直到完成，Stop hook 拦截退出 | 工程化（循环编排） |
| C13 | **安全钩子** | `plugins/security-guidance/`：PreToolUse 监控命令注入、XSS、eval、危险 HTML、pickle 反序列化、os.system 等 9 种模式 | 工程化（安全） |

### 2.2 编码能力（不借鉴）

文件读写编辑、shell 执行、代码库理解、git 操作（commit-commands/pr-review-toolkit/feature-dev 等插件的核心能力）——属于编码能力本身，不在本项目边界。

---

## 三、OpenAI Codex CLI 工程化特性（实证来源：codex-rs/ 80+ crate 目录树 + codex-rs/core/src/ 130+ 源文件 + docs/ 目录）

### 3.1 实证特性清单

| # | 特性 | 实证来源（crate / 源文件） | 性质 |
|---|------|--------------------------|------|
| D1 | **AGENTS.md 规范** | `core/src/agents_md.rs`、`agents_md_manager.rs`、`docs/agents_md.md` | 工程化（配置） |
| D2 | **执行策略 execpolicy** | `core/src/exec_policy.rs`、`exec_policy/`、`docs/execpolicy.md`：声明式执行策略规则 | 工程化（策略） |
| D3 | **多平台沙箱** | crate `linux-sandbox`、`windows-sandbox-rs`、`bwrap`、`process-hardening`、`sandboxing`；`core/src/sandbox_tags.rs`、`windows_sandbox_read_grants.rs`、`docs/sandbox.md` | 工程化（隔离） |
| D4 | **MCP（server + client + 工具暴露 + 审批）** | `core/src/mcp.rs`、`mcp_tool_call/`、`mcp_tool_exposure.rs`、`mcp_skill_dependencies.rs`、`mcp_tool_approval_templates.rs`；crate `mcp-server`、`rmcp-client`、`codex-mcp` | 工程化（协议） |
| D5 | **上下文压缩 compact（多策略）** | `core/src/compact.rs`、`compact_model_fallback.rs`、`compact_remote.rs`、`compact_remote_v2.rs`、`compact_token_budget.rs`：本地/远程/远程v2/token预算/模型降级五策略 | 工程化（上下文管理） |
| D6 | **OpenTelemetry 可观测** | `core/src/otel_init.rs`；crate `otel`、`rollout-trace` | 工程化（可观测） |
| D7 | **Rollout 追踪 + 预算** | `core/src/rollout.rs`、`rollout_budget.rs`、`thread_rollout_truncation.rs` | 工程化（可观测） |
| D8 | **密钥管理** | crate `secrets`、`keyring-store`、`aws-auth` | 工程化（安全） |
| D9 | **多模型管理 + 本地模型** | crate `model-provider`、`model-provider-info`、`models-manager`、`ollama`、`lmstudio` | 工程化（模型） |
| D10 | **会话线程管理** | `core/src/thread_manager.rs`、`codex_thread.rs`、`session/`、`session_startup_prewarm.rs`；crate `thread-store`、`thread-manager-sample` | 工程化（会话） |
| D11 | **工具系统 + 统一执行** | `core/src/tools/`、`function_tool.rs`、`unified_exec/` | 工程化（工具） |
| D12 | **钩子运行时** | `core/src/hook_runtime.rs` | 工程化（生命周期） |
| D13 | **Skills** | `core/src/skills.rs`、`docs/skills.md` | 工程化（领域知识） |
| D14 | **Slash 命令** | `docs/slash_commands.md` | 工程化（交互） |
| D15 | **Agent 委派 + 图存储 + 身份** | `core/src/codex_delegate.rs`、`agent/`；crate `agent-graph-store`、`agent-identity` | 工程化（委派） |
| D16 | **守卫 guardian** | `core/src/guardian/` | 工程化（安全） |
| D17 | **网络策略** | `core/src/network_policy_decision.rs`；crate `network-proxy` | 工程化（隔离） |
| D18 | **Elicitation（MCP 交互式信息请求）** | `core/src/elicitation.rs` | 工程化（协议） |
| D19 | **连接器** | `core/src/connectors.rs`；crate `connectors` | 工程化（集成） |
| D20 | **Turn 级追踪** | `core/src/turn_diff_tracker.rs`、`turn_metadata.rs`、`turn_timing.rs` | 工程化（可观测） |
| D21 | **实时上下文 / 对话** | `core/src/realtime_context.rs`、`realtime_conversation.rs`、`realtime_prompt.rs` | 工程化（上下文） |
| D22 | **响应重试** | `core/src/responses_retry.rs` | 工程化（健壮性） |
| D23 | **用户消息准入** | `core/src/user_message_admission.rs` | 工程化（持久化） |
| D24 | **Shell 快照 + 提权** | `core/src/shell_snapshot.rs`、`shell.rs`、`shell-escalation` | 工程化（shell） |
| D25 | **配置 + 环境选择** | `core/src/config/`、`environment_config.rs`、`environment_selection.rs`、`docs/config.md` | 工程化（配置） |
| D26 | **协作模式模板** | crate `collaboration-mode-templates` | 工程化（协作） |
| D27 | **云任务** | crate `cloud-tasks`、`cloud-tasks-client`、`cloud-tasks-mock-client` | 工程化（异步） |
| D28 | **App server 协议（daemon 架构）** | crate `app-server-protocol`、`app-server-daemon`、`app-server-client`、`app-server-transport` | 工程化（架构） |
| D29 | **诊断 / 反馈** | crate `diagnostics`、`feedback` | 工程化（可观测） |
| D30 | **会话预热** | `core/src/session_startup_prewarm.rs` | 工程化（启动） |
| D31 | **安装 ID / 内存用量** | `core/src/installation_id.rs`、`memory_usage.rs` | 工程化（运维） |

### 3.2 编码能力（不借鉴）

`file-search`、`file-system`、`file-watcher`、`git-utils`、`apply-patch`、`core/src/apply_patch.rs`、`core/src/web_search.rs`（编码辅助搜索）——属于编码能力本身。

---

## 四、OpenCode 工程化特性（实证来源：packages/ 30+ 包目录树 + packages/core/src/ + packages/opencode/src/ + AGENTS.md V2 Session Core + specs/project.md）

### 4.1 实证特性清单

| # | 特性 | 实证来源 | 性质 |
|---|------|---------|------|
| O1 | **多 project + 多 worktree** | `specs/project.md` API：`GET /project`、`POST /project/init`、`GET /project/:id/session` | 工程化（多租户/工作区） |
| O2 | **V2 Session Core：durable prompt admission** | `AGENTS.md`：`SessionV2.prompt(...)` 持久化 `session_input` 行再 advisory `SessionExecution.wake`；`core/src/session/input.ts`、`prompt.ts` | 工程化（持久化） |
| O3 | **V2 Session Core：Session ID 复用 + exact retry** | `AGENTS.md`：复用 Session ID 采用既有 Session，复用 prompt message ID 协调 exact retry | 工程化（会话） |
| O4 | **V2 Session Core：SessionExecution process-global** | `AGENTS.md`：process-global + Session-ID based，`SessionStore` + `LocationServiceMap` 发现 placement | 工程化（架构） |
| O5 | **V2 Session Core：Location 作用域** | `AGENTS.md`：SessionRunner、model resolution、tool registry、permissions、filesystem 均 Location-scoped；`core/src/location.ts`、`location-service-map.ts`、`location-services.ts` | 工程化（隔离） |
| O6 | **V2 Session Core：delivery vocabulary** | `AGENTS.md`：steer（默认，下一安全边界提升）vs queue（待 idle 提升）vs promote | 工程化（消息语义） |
| O7 | **V2 Session Core：SessionRunCoordinator** | `AGENTS.md`：joins explicit same-Session resumes、coalesces prompt wakeups、允许不同 Session 并发；`core/src/session/run-coordinator.ts` | 工程化（并发协调） |
| O8 | **V2 Session Core：EventV2 replay owner claims** | `AGENTS.md`：replay owner claims 与 clustered execution ownership 分离；`opencode/src/event-v2-bridge.ts`、`event-manifest.ts` | 工程化（事件） |
| O9 | **V2 Session Core：System Context algebra** | `AGENTS.md` + `core/src/system-context/`：上下文代数、registry、built-ins | 工程化（上下文） |
| O10 | **上下文压缩 compaction** | `core/src/session/compaction.ts`；`specs/project.md` API：`POST .../compact` | 工程化（上下文管理） |
| O11 | **Context epoch（上下文版本化）** | `core/src/session/context-epoch.ts` | 工程化（版本） |
| O12 | **会话回退 revert / unrevert** | `core/src/session/revert.ts`；`specs/project.md` API：`POST .../revert`、`POST .../unrevert` | 工程化（会话） |
| O13 | **Session projector（事件溯源）** | `core/src/session/projector.ts` | 工程化（持久化） |
| O14 | **双 agent 模式（build + plan）** | `README.md`：build 全访问 vs plan 只读（拒绝文件编辑，bash 需许可） | 工程化（权限） |
| O15 | **general subagent** | `README.md`：`@general` 复杂搜索和多步任务子代理 | 工程化（委派） |
| O16 | **权限持久化** | `core/src/permission/saved.ts`、`sql.ts`；`opencode/src/permission/` | 工程化（安全） |
| O17 | **MCP 集成** | `opencode/src/mcp/` | 工程化（协议） |
| O18 | **ACP（Agent Communication Protocol）** | `opencode/src/acp/` | 工程化（协议） |
| O19 | **事件系统（manifest + V2 bridge）** | `opencode/src/event-manifest.ts`、`event-v2-bridge.ts`；`core/src/event.ts`、`event/`、`public-event-manifest.ts` | 工程化（事件） |
| O20 | **可观测性** | `core/src/observability.ts`、`observability/` | 工程化（可观测） |
| O21 | **HTTP 录制回放** | `packages/http-recorder` | 工程化（测试） |
| O22 | **控制平面** | `core/src/control-plane`、`opencode/src/control-plane/` | 工程化（架构） |
| O23 | **同步** | `opencode/src/sync/` | 工程化（同步） |
| O24 | **快照** | `core/src/snapshot.ts`、`opencode/src/snapshot/` | 工程化（持久化） |
| O25 | **会话分享** | `opencode/src/share/`、`core/src/share/`；API：`POST .../share` | 工程化（协作） |
| O26 | **后台任务** | `core/src/background-job.ts`、`opencode/src/background/` | 工程化（异步） |
| O27 | **凭证管理 + OAuth** | `core/src/credential.ts`、`credential/`、`oauth/` | 工程化（安全） |
| O28 | **数据库迁移** | `core/src/data-migration.sql.ts` | 工程化（演进） |
| O29 | **工具输出存储** | `core/src/tool-output-store.ts` | 工程化（工具） |
| O30 | **指令上下文（AGENTS.md 式）** | `core/src/instruction-context.ts` | 工程化（配置） |
| O31 | **特性开关 flag** | `core/src/flag/` | 工程化（配置） |
| O32 | **集成体系** | `core/src/integration/`、`integration.ts` | 工程化（集成） |
| O33 | **ripgrep / patch / git / filesystem / pty / lsp** | `core/src/ripgrep/`、`patch.ts`、`git.ts`、`filesystem/`、`pty.ts`、`opencode/src/lsp/` | **编码能力（不借鉴）** |

### 4.2 V2 Session Core 深度解读（AGENTS.md 实证）

OpenCode 的 `AGENTS.md` 末尾 "V2 Session Core" 部分揭示了**生产级会话运行时**的顶级工程设计，值得逐条理解：

1. **durable prompt admission 与 model execution 分离**：`SessionV2.prompt(...)` 先持久化一条 `session_input` 行，再调度 advisory `SessionExecution.wake(sessionID)`。除非 `resume: false` 请求 admit-only 行为。**意义**：用户消息先落盘再执行，崩溃不丢输入，可重放。
2. **Session ID 复用语义**：复用 Session ID = 采用既有 Session；复用 prompt message ID = 仅当 Session + prompt + delivery mode 匹配时协调 exact retry，冲突则失败。历史 projected prompts 在 exact retry 时惰性合成 promoted inbox 记录。**意义**：精确的重试语义，避免重复执行副作用。
3. **SessionExecution process-global**：本地实现持有 process-local Session coordinator，通过 `SessionStore` + `LocationServiceMap.get(session.location)` 发现 placement（仅 drain 开始时）。**意义**：为多实例集群预留，单进程时不引入跨进程开销。
4. **Location 作用域**：SessionRunner、model resolution、tool registry、permissions、filesystem 均 Location-scoped。**意义**：多工作区隔离，不同 project/worktree 有独立工具与权限集。
5. **delivery vocabulary**：steer（默认，在下一安全 provider-turn 边界提升）vs queue（待 Session idle 时提升）vs promote。新 user input 重置 agent 的 provider-turn allowance。**意义**：区分"引导当前对话"与"排队等待"与"提升为正式输入"，精确控制多消息并发语义。
6. **SessionRunCoordinator**：joins explicit same-Session resumes（合并同会话恢复）、coalesces prompt wakeups（合并唤醒）、允许不同 Sessions 并发。**意义**：同会话串行、跨会话并发，避免竞态。
7. **drain 语义**：advisory wakes drain eligible durable inbox rows；post-crash continuation recovery 需独立设计后才可重试 provider work；drain 无 durable identity 或 transcript boundary。**意义**：崩溃恢复的精确边界。
8. **EventV2 replay owner claims 与 clustered execution ownership 分离**。**意义**：事件重放与执行所有权解耦，支持集群。
9. **System Context algebra**：registry + built-ins 在 `src/system-context`；Context Source producers 与 observed domains 同置；Session History selection + Context Epoch persistence Session-owned。**意义**：上下文组合的形式化代数。

---

## 五、逐特性可借鉴性筛选

> 筛选维度：① 该特性是什么 + 源自哪个 code 项目；② 本项目是否已有等价能力（spec.md 实证）；③ 借鉴价值（高/中/低）；④ 借鉴方式（直接采用 / 思想吸收 / 不适用）；⑤ 借鉴后是否改变定位。

### 5.1 进 MVP（高价值 + 多轮会话刚需）

| # | 特性 | 源自 | 本项目现状 | 价值 | 方式 | 改变定位？ |
|---|------|------|-----------|------|------|-----------|
| **B1** | **上下文压缩 compact** | Codex D5（五策略）、OpenCode O10、Claude Code C9 | spec.md 无显式主上下文压缩。长期记忆有 token 预算截断（5.5.1 第 7 条），但**多轮对话主上下文无压缩机制**——多轮累积会 token 爆炸 | **高** | 思想吸收 + 简化：取"token 预算阈值触发 + 摘要压缩 + 模型降级"三策略，不引入 Codex 的远程/远程v2 五策略 | 否，仍是问答运行时 |

### 5.2 Phase 2 早期（中高价值 + 生产健壮性增强）

| # | 特性 | 源自 | 本项目现状 | 价值 | 方式 | 改变定位？ |
|---|------|------|-----------|------|------|-----------|
| **B2** | **Session 运行协调器（并发安全）** | OpenCode O7（SessionRunCoordinator） | spec.md 未定义同一会话并发请求行为。单进程多节点下同会话并发需显式协调 | **中高** | 思想吸收：session 级 mutex，同会话串行、跨会话并发 | 否 |
| **B3** | **会话回退 revert** | OpenCode O12 | 有 checkpoint 恢复（5.1.1 第 6 条），但无 revert/undo。checkpoint 是"恢复继续"，revert 是"撤销回退" | **中** | 直接采用（基于已有 checkpoint）：提供 revert API 回退到指定 checkpoint | 否 |
| **B4** | **durable prompt admission** | OpenCode O2、Codex D23 | 有"未持久化检查点时拒绝执行不可逆能力调用"（5.1.1 第 7 条），但非"消息先持久化再执行" | **中高** | 思想吸收：用户消息到达先持久化再执行，崩溃可重放未处理消息 | 否 |
| **B5** | **OpenTelemetry exporter** | Codex D6 | 有 Langfuse trace（4.4 第 2 条，三态降级）+ 结构化日志，但无 OTel | **中** | 思想吸收：可观测层增加 OTel exporter，与 Langfuse 并列可选 | 否 |
| **B6** | **MCP client 集成** | Codex D4、OpenCode O17、Claude Code C7 | 无 MCP。能力内置 | **中** | 思想吸收：作为 MCP client 调用外部 server 扩展能力（如外部知识库 MCP） | 否（MCP 是集成协议） |
| **B7** | **数据迁移机制** | OpenCode O28 | 无显式 schema 迁移策略 | **中** | 思想吸收：引入 alembic 或简化版迁移 | 否 |
| **B8** | **AGENTS.md 项目级指令** | Codex D1、Claude Code C8、OpenCode O30 | 无。配置是 env/.env | **中** | 思想吸收：支持项目级指令文件注入路由提示词（领域口径/路由偏好） | 否 |

### 5.3 Phase 2 后期 / 低优先级

| # | 特性 | 源自 | 本项目现状 | 价值 | 方式 |
|---|------|------|-----------|------|------|
| **B9** | Slash 命令（CLI 客户端） | Claude Code C2、Codex D14 | 无（MVP 仅 HTTP API） | 中 | 思想吸收：CLI 客户端提供 /health、/eval、/compact、/reset 运维命令 |
| **B10** | 生命周期 Hooks | Claude Code C6、Codex D12 | 有 lifespan 预热，无显式 hooks | 中 | 思想吸收：能力调用前后提供可注册回调点（pre/post） |
| **B11** | Turn 级追踪增强 | Codex D20 | 有 step_index + trace | 低中 | 思想吸收：trace 增加 turn 级 metadata（耗时/token/证据数） |
| **B12** | HTTP 录制回放 | OpenCode O21 | 有运行时 mock + golden set | 中 | 思想吸收：录制真实响应做离线回放基线 |
| **B13** | 用户反馈收集 | Codex D29 | 无 | 低中 | 思想吸收：收集点赞/点踩进 golden set |
| **B14** | Context epoch（缓存失效） | OpenCode O11 | 有语义缓存（5.5.1 第 3 条），无版本化失效 | 低中 | 思想吸收：知识库更新时使受影响缓存失效 |
| **B15** | 本地模型（ollama）支持 | Codex D9 | 有统一 ChatModel 抽象 + 主备降级 | 低中 | 思想吸收：ollama 作为降级备选 |
| **B16** | delivery vocabulary（steer/queue/promote） | OpenCode O6 | 无 | 低中 | 思想吸收：多消息并发语义（Phase 2 并发增强时） |

### 5.4 不采用（与定位冲突 / 已有等价 / 过设计 / 编码能力）

| # | 特性 | 源自 | 不采用理由 |
|---|------|------|-----------|
| N1 | 插件体系 | Claude Code C1、Codex plugin、OpenCode plugin | **与专用运行时定位冲突**：spec.md 1.4 已排除低代码平台/通用平台，插件体系是通用平台扩展机制 |
| N2 | 多平台沙箱 | Codex D3 | **已有领域级等价**：SQL 只读连接（5.4.1 第 4 条）已是沙箱；本项目不执行任意 shell/代码，无需进程级沙箱 |
| N3 | 执行策略 execpolicy | Codex D2 | **策略空间小**：能力固定（search/rag/sql/direct），能力开关 + 路由配置已是简化版策略 |
| N4 | 多 agent 并行 | Claude Code C4 | **与路由模型冲突**：Supervisor 路由选单能力（5.1.1 第 2 条），多 agent 并行适用于多维度证据汇总但非 MVP |
| N5 | Skill 自动触发 | Claude Code C5、Codex D13 | **RAG 已覆盖**：领域知识注入由知识库（RAG）承担，非 skill |
| N6 | App server daemon 架构 | Codex D28 | **形态不匹配**：本项目是 HTTP 服务（FastAPI），非 CLI daemon |
| N7 | 凭证 keyring / OAuth | Codex D8、OpenCode O27 | **单租户服务端**：env/secret manager 已够；OAuth 留 Phase 3 多租户 |
| N8 | 会话分享 | OpenCode O25 | **后端运行时**：协作 UX 由调用方自理 |
| N9 | 自引用循环 | Claude Code C12 | **问答一次完成**：反思重试（5.1.1 第 4 条）已够，非"迭代直到测试过" |
| N10 | 安全钩子（9 模式监控） | Claude Code C13 | **已有领域级安全**：SQL 白名单 + 只读 + 密钥脱敏（4.3） |
| N11 | Elicitation | Codex D18 | **非工具提供方**：本项目是问答消费者，非 MCP server 向用户要信息 |
| N12 | 协作模式模板 | Codex D26 | **非多人共编** |
| N13 | 云任务 | Codex D27 | **同步 SSE**：本项目流式回答，非异步任务队列 |
| N14 | Turn diff tracker | Codex D20 | **无代码 diff**：问答无文件变更 |
| N15 | Mention syntax（@ 提及） | Codex（mention_syntax.rs） | **API 非 CLI**：@ 提及是 CLI 交互引用 |
| N16 | Shell 快照 / 提权 | Codex D24 | **不执行 shell** |
| N17 | 诊断 | Codex D29 | **已有等价**：健康自描述（5.6.1 第 6 条） |
| N18 | Location 作用域 | OpenCode O5 | **单租户单工作区**：过设计 |
| N19 | 网络策略 | Codex D17 | **外部调用固定**：Tavily/LLM/PG，无任意 shell 网络访问 |
| N20 | Projector 事件溯源 | OpenCode O13 | **checkpoint 已够**：状态快照恢复，无需事件重放 |
| N21 | System context algebra | OpenCode O9 | **过设计**：本项目上下文简单（问题+证据+记忆） |
| N22 | ACP | OpenCode O18 | **单 Supervisor**：无 agent 间通信 |
| N23 | Tool output store | OpenCode O29 | **证据是片段**：无需大输出存储 |
| N24 | 多 project + 多 worktree | OpenCode O1 | **单租户**：Phase 3 多租户时再考虑 |
| N25 | 双 agent 模式（build/plan） | OpenCode O14 | **无编码操作**：plan 的"拒绝文件编辑"无对应物 |
| N26 | 编码能力（file/git/patch/ripgrep/lsp/apply-patch） | 三者均有 | **spec.md 1.4 显式排除**：代码库操作 / 编码型 Agent |

---

## 六、借鉴建议清单（按优先级排序）

### 6.1 进 MVP

| 优先级 | 特性 | 借鉴方式 | 理由 |
|--------|------|---------|------|
| **P0** | **B1 上下文压缩 compact** | 思想吸收：token 预算阈值触发 → 摘要压缩 → 模型降级 | 多轮会话 token 累积必需，spec.md 当前是明确缺口 |

### 6.2 Phase 2 早期

| 优先级 | 特性 | 借鉴方式 | 理由 |
|--------|------|---------|------|
| **P1** | **B2 Session 运行协调器** | 思想吸收：session 级 mutex | 同会话并发安全是生产刚需 |
| **P1** | **B4 durable prompt admission** | 思想吸收：消息先落盘再执行 | 崩溃不丢输入，可重放 |
| **P2** | **B3 会话回退 revert** | 直接采用（基于 checkpoint） | UX 增强，低成本 |
| **P2** | **B5 OpenTelemetry exporter** | 思想吸收：与 Langfuse 并列 | 降低用户可观测集成成本 |
| **P2** | **B6 MCP client 集成** | 思想吸收：调用外部 MCP server | 能力扩展通道 |
| **P2** | **B7 数据迁移机制** | 思想吸收：alembic | schema 演进保障 |
| **P2** | **B8 AGENTS.md 项目级指令** | 思想吸收：注入路由提示 | 领域口径/路由偏好配置化 |

### 6.3 Phase 2 后期

| 优先级 | 特性 | 借鉴方式 |
|--------|------|---------|
| P3 | B9 Slash 命令（CLI） | CLI 客户端运维命令 |
| P3 | B10 生命周期 Hooks | 能力调用前后回调点 |
| P3 | B12 HTTP 录制回放 | 离线回归测试 |
| P3 | B11 Turn 级追踪增强 | trace 增加 turn metadata |
| P3 | B14 Context epoch 缓存失效 | 知识库更新失效缓存 |
| P3 | B15 本地模型 ollama | 降级备选 |
| P4 | B13 用户反馈收集 | 评测数据 |
| P4 | B16 delivery vocabulary | 多消息并发语义 |

### 6.4 不采用（26 项，见 5.4 表）

---

## 七、对 spec.md 的修订建议

### 7.1 必须补入（MVP 缺口）

**B1 上下文压缩**：spec.md 当前无主上下文压缩能力，多轮会话 token 累积无上限保护。建议补入：
- **4.1 性能**：增加上下文压缩触发阈值与压缩后延迟约束
- **5.1 会话编排**：增加"上下文压缩"业务规则
- **5.1.3 异常场景**：增加压缩失败降级场景

### 7.2 建议补入（Phase 2 早期，标注 Phase 2）

**B2 Session 运行协调器**：spec.md 未定义同会话并发行为。建议补入：
- **5.1 会话编排**：增加"会话并发协调"业务规则（同会话串行、跨会话并发）
- **4.2 可靠性**：增加并发协调保证

### 7.3 不修改 spec.md 的部分

- B3-B16（Phase 2 特性）：spec.md 4.6 第 4 条已声明"Phase 2 演进必须不破坏 Phase 1 接口"，这些特性以增量方式纳入，无需现在写入核心能力。
- N1-N26（不采用）：spec.md 1.4 职责边界已覆盖大部分排除理由，无需逐条补入。

### 7.4 定位不变性确认

本次借鉴**不改变本项目定位**：
- 借鉴的均为**工程化运行时特性**（上下文压缩、并发协调、可观测、MCP、迁移），非编码能力。
- spec.md 1.4 "不负责代码库操作 / 编码型 Agent"边界不变。
- spec.md 1.1 "工程化优先的多源证据问答 Agent 运行时"定位不变，新增特性强化"工程化优先"而非转向"编码型"。

---

## 八、多源交叉验证总结

| 特性 | Claude Code | Codex | OpenCode | 三源一致？ |
|------|------------|-------|----------|-----------|
| 上下文压缩 compact | C9（/compact） | D5（五策略源码） | O10（compaction.ts + API） | ✅ 三源均有 |
| MCP 集成 | C7（.mcp.json） | D4（mcp-server + client） | O17（mcp/） | ✅ 三源均有 |
| AGENTS.md 项目级指令 | C8（CLAUDE.md） | D1（agents_md.rs） | O30（instruction-context.ts） | ✅ 三源均有 |
| 会话检查点/恢复 | C11（--resume） | D10（thread-store） | O13（projector.ts） | ✅ 三源均有 |
| 钩子运行时 | C6（hooks/） | D12（hook_runtime.rs） | — | 两源 |
| Slash 命令 | C2（commands/） | D14（slash_commands.md） | — | 两源 |
| Skills | C5（skills/） | D13（skills.rs） | — | 两源 |
| Session 运行协调器 | — | — | O7（run-coordinator.ts） | OpenCode 独有 |
| durable prompt admission | — | D23（user_message_admission.rs） | O2（AGENTS.md V2） | 两源 |
| 会话回退 revert | — | — | O12（revert.ts + API） | OpenCode 独有 |
| 多平台沙箱 | — | D3（linux/windows/bwrap） | — | Codex 独有（编码必需） |
| OpenTelemetry | — | D6（otel_init.rs） | O20（observability.ts） | 两源 |

> **结论**：上下文压缩、MCP、项目级指令、检查点/恢复是三源一致的工程化标配；Session 运行协调器、durable prompt admission、会话回退是 OpenCode V2 的进阶设计，代表了会话运行时的前沿工程实践。
