# 理念相近的开源 Agent 运行时内核 / 可靠性原语库

> 续《runtime-self-build-analysis.md》之"业界是否存在已经这样实现的开源库"。
> 结论：已有多个开源项目独立收敛到同一套哲学（框架无关、可独立复用的运行时内核 / 可靠性原语层）。

## 0. 结论先行

"已经有开源库这样实现"不仅成立——下面三个项目各自**独立**收敛到了与本项目内核相同的分层哲学，只是深度与形态不同。

按与本项目的相似度分三档：

1. **LightAgent**（wanxingai/wxai-space，Apache 2.0）—— 完整轻量框架，架构与"agent-core + agent-runtime（Planner/Skill）"几乎平行。
2. **agent-os**（manu-7，研究项目）—— 安全治理内核，POSIX 启发的确定性拦截式策略。
3. **agent-stack**（MukundaKatta，MIT）—— à la carte 零依赖可靠性零件库，与 `agent-core` 的 `dependencies=[]` 铁律同宗。

## 1. 架构最相似：LightAgent（wanxingai / wxai-space，Apache 2.0）

不是蓝图，但结构上与"agent-core + agent-runtime（含 Planner/Skill）"几乎平行。

- **定位**：超轻量、模块化、Skill-ready 的"生产级开源 Agentic 框架"，明确 **"No LangChain, No LlamaIndex"**；Apache 2.0，有论文 arXiv:2509.09292（2025）。
- **增量生产控制理念**：默认调用路径简单，追踪/护栏/钩子可逐步叠加——与本项目"核心握手里、商品化能力借力"一致。

概念映射（LightAgent 模块 → 本项目概念）：

| LightAgent 概念 | 本项目对应 | 相似度 |
|---|---|---|
| CapabilityRegistry + PolicyEngine（作用域化 Provider/权限快照/审计） | `agent_core.llm.registry` + `agent-runtime` skill_guard/PolicyHook | 高 |
| Session / AgentRuntime（可重放事件、Checkpoint、Budgets、Jobs） | `agent_runtime.planner.durability_pg`（PG 持久化）/ MongoCheckpointer + PlannerRuntime（max_steps/depth/tokens/成本预算） | 高 |
| input/tool/output guardrails（隐私拦截/敏感工具确认/输出脱敏） | `agent_core.guardrails` + `agent-runtime` admission 脱敏约束 | 高 |
| Runtime Hooks（before_run/after_model_response/before_memory_write…`HookDecision`） | `agent-runtime` skills 中间件洋葱链 | 高 |
| MemoryPolicy / MemoryScope（租户隔离、来源、写准入） | `agent_core.memory`（租户维度、写入准入） | 高 |
| LightFlow（DAG 工作流 + Checkpoint + 审批 + 回退） | `agent-runtime` planner（plan/execute 分离）+ workflow 执行器 | 中高 |
| LightSwarm（基于角色的多 Agent 委托路由） | 联邦网关 / 多 planner 路由 | 中 |
| LightEvaluator（确定性回归用例） | `eval/run_eval.py` + `run_planner_eval.py` | 中 |
| Trace（opt-in 结构化事件） | `agent_core.tracing` / events EventBus | 高 |

**差异**：LightAgent 是**完整 Agent 框架**（含编排与多 Agent）；本项目 Plan-F 是"统一 Runtime、降级 LangGraph/DeepAgents 为执行实现"，不追求成为框架。且本地额外有 PG 持久化准入队列、准入不存问题全文等受监管约束（2026-10-15 订正：原写在此处的"跨用户回退禁止"**尚未实现**，`revert.py` 只有 docstring 声明，详见 `docs/project-introduction-2026-10-12.md` §6 第 13 行）。

**可借鉴**：`HookDecision`（观察/替换/阻止载荷）的显式枚举比我们 middleware 的隐式返回值更清晰，可作 skill 中间件协议升级参考；`HumanApprovalHook` 失败封闭模式可对照审批节点。

## 2. 安全治理内核：agent-os（manu-7，研究项目）

- **定位**："A Safety-First Kernel for Autonomous AI Agents"——把 OS（POSIX 启发）概念用于 Agent 治理。区别于提示式安全，提供**应用级中间件**，在动作执行前由策略引擎（而非 LLM）拦截决定。
- **注意**：应用级强制（非 OS 内核隔离），研究项目；核心模块（Policy Engine/Flight Recorder/SDK 适配器）生产就绪，扩展模块实验性。

POSIX 启发的原语：

| POSIX 概念 | agent-os 对应 | 说明 |
|---|---|---|
| 进程信号 `SIGKILL`/`SIGSTOP` | `AgentSignal` + SignalDispatcher | 暂停/恢复/终止智能体 |
| 文件系统 `/proc`,`/tmp` | AgentVFS（`/policy/rules.yaml` 等） | 策略与状态虚拟文件系统 |
| IPC 管道 | Agent Message Bus（AMB） | 解耦通信，Redis/Kafka/NATS 适配器 |
| 系统调用 `open()`/`read()` | `kernel.execute()` | 内核空间执行入口 |
| — | Policy Engine（控制面第 3 层） | 确定性规则执行，生产就绪 |
| — | Flight Recorder（SQLite 审计） | 内核空间审计日志，已知可被篡改需外写 |
| — | Tool Registry / ATR（`atr.tools.safe`） | 运行时发现安全工具 |
| — | Observability | Prometheus + OTel |

可包装现有框架：`LangChainKernel` / `OpenAIKernel` / `SemanticKernelWrapper` / `CrewAIKernel`，`@kernel.govern` 装饰器在框架边界拦截工具调用。

| agent-os 概念 | 本项目对应 | 启示 |
|---|---|---|
| Policy Engine 确定性拦截 | `agent-runtime` skill_guard + admission 策略 | 我们偏"治理+预算"，agent-os 偏"确定性拦截"，可借鉴其信号模型（SIGKILL/SIGSTOP）做 planner 中止/暂停 |
| Flight Recorder 审计 | `agent_core.events` EventBus + 自建链路属性仅记长度+哈希 | 我们已做脱敏审计（**范围要说准**：LangChain 埋点的模型节点 span 仍带完整输入输出，属已拍板接受的暴露面）；agent-os 的"审计可被篡改需外写"是该类的已知局限 |
| StatelessKernel（零依赖、可审计小边界） | `agent_core` 零依赖内核 | 哲学一致 |

**风险**：确定性策略对未知攻击可能穿透（已知架构限制），生产需配容器隔离/纵深防御；偏"治理基础设施"而非"运行时内核"，与 agent-core 互补而非替代。

## 3. à la carte 可靠性原语：agent-stack（MukundaKatta，MIT）

- **定位**："Six small, single-concern reliability libraries for production LLM agents — Zero runtime dependencies. Adopt one or all." 每个原语零运行时依赖、<500 行、独立发布（**npm + PyPI + MCP server** 三形态）。
- **论文**：Zenodo DOI 10.5281/zenodo.20074702《Six Reliability Primitives for LLM Agents: An Artifact Pattern for Stackable, Single-Concern Libraries》。

六个原语与可借鉴点：

| 原语 | 关注点 | 本项目对应 / 可借鉴 |
|---|---|---|
| AgentFit | Token 感知的上下文窗口装配 | PlannerRuntime token 预算的"装配"环节可参考 |
| AgentGuard | 工具调用的网络出口白名单 | guardrails web / skill_guard 工具白名单 |
| **AgentBudget** | **每次运行的 token + 美元双上限** | **直接对应 PlannerRuntime 的 tokens/cost 预算，最值得对齐** |
| AgentVet | 工具参数校验 + 重试提示 | SkillRegistry 契约校验 + retry |
| AgentCast | 结构化输出 validate-and-retry（LLM JSON） | —（本地缺口） |
| AgentSnap | 工具调用 trace 的快照测试 | `eval/` 启发式回归可参考 |

**可借鉴**：其"单关注点、零依赖、可单独 adopt"的零件化理念与 `agent-core` 的 `dependencies=[]` 铁律完全一致；`AgentBudget` 的"token + dollar 双 cap"是比我们仅记账更前置的**硬上限**原语，可评估引入为 PlannerRuntime 的硬预算层。

## 4. 综合对比矩阵

| 库 | 类型 | 形态 | 依赖哲学 | 相似度 | 最强对应点 | 最值得借鉴 |
|---|---|---|---|---|---|---|
| LightAgent | 完整轻量框架 | Py（Apache2） | No LangChain/LlamaIndex | ⭐⭐⭐⭐ | CapabilityRegistry/Hooks/Budgets/Guardrails | `HookDecision` 显式协议、`HumanApproval` 模式 |
| agent-os | 安全治理内核 | Py（研究） | 低依赖、StatelessKernel 零依赖 | ⭐⭐⭐ | Policy Engine 拦截 / Flight Recorder | SIGKILL/SIGSTOP 中止模型、确定性策略 |
| agent-stack | 原语零件库 | TS+Py+MCP | 零运行时依赖、à la carte | ⭐⭐⭐ | resilience/budget/guardrails | AgentBudget 硬双上限、单关注点零件化 |

> 前文《runtime-self-build-analysis.md》已覆盖的 LangGraph/CrewAI/AutoGen/OpenAI Agents SDK/Google ADK/MS Agent Framework/Claude Agent SDK 及云原生三强（Bedrock AgentCore/Azure AI Foundry/Vertex AI Agent Builder）属"编排/平台"层而非"内核/原语"层，此处不重复。

## 5. 对本项目的可借鉴建议（落地视角）

1. **AgentBudget 硬双上限**：评估把 token + dollar 硬 cap 作为 PlannerRuntime 预算的**前置闸门**，而非仅记账（当前仅 `record_usage` 累计、无硬阻断）。
2. **HookDecision 显式化**：LightAgent 的 `HookDecision`（observe/replace/block）枚举比 middleware 隐式返回更清晰，可作 skill 中间件协议升级参考。
3. **策略信号模型**：agent-os 的 SIGKILL/SIGSTOP 可映射为 planner 的 abort/pause 原语，强化治理可控性。
4. **保持零依赖铁律**：以上均建议"借鉴设计、自研落地"，而非 `pip install`——否则破坏 `agent-core` 的 `dependencies=[]` 铁律与框架无关性（见 `packages/agent-core/README.md` §设计铁律）。

## 6. 反模式 / 风险

- **agent-os 的研究性**：确定性策略对未知攻击无效，仅作治理思路参考，勿套用其"0% 违规"承诺。
- **LightAgent 是框架**：若引入易与 Plan-F"统一 Runtime 不统一 Agent"理念冲突；应取其零件（Hooks/Guardrails）而非整体框架。
- **agent-stack 三形态冗余**：其 TS+PyPI+MCP 三发的维护成本对我们无意义，仅需借鉴"单关注点零件"思想。

## 7. 证据索引

- `wanxingai/LightAgent` 仓库 README + `docs/`（架构表、v0.10 事件源运行时）
- `manu-7/agent-os` 仓库 README（POSIX 原语、wrappers）
- `MukundaKatta/agent-stack` 仓库 README + Zenodo 论文（DOI 10.5281/zenodo.20074702）
- 关联：`docs/runtime-self-build-analysis.md`（自研动机 + 业界框架/平台层对比）
