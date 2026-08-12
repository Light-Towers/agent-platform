# 调研：按任务动态创建子 Agent

> 日期：2026-08-11
> 触发：确认当前项目"能规划但不能动态创建子 agent"后，记录待办并对照成熟开源项目
> 关联代码：`agent/main_agent.py:28,104-123`（全局单例 + 静态装配）、`agent/async_subagents.py`（固定 3 个 AsyncSubAgent）

---

## 现状结论

**当前项目子 agent 是启动时静态装配的固定 3 个角色，主管只能"选择"委派给谁，不能"造"新角色。**

证据：
- `_main_agent` 是全局单例（`main_agent.py:28`），`get_main_agent()` 懒加载一次后所有 session 共用同一张图
- `subagents=_build_subagents()` 在创建主管时就绑死为 `database_query_agent` / `network_search_agent` / `knowledge_base_agent`
- `create_deep_agent` 全仓库只调用一次，`run_deep_agent(task_query, session_id)` 内无任何按 `task_query` 动态构造子 agent 的路径
- planner（`TodoListMiddleware`）拆出的步骤 `tool` 字段指向**已注册**的工具/子服务，不产生新角色

---

## 待办目标

支持**运行时按任务规约动态创建子 agent**：主管先分析任务→输出本任务所需角色清单（含每个角色的能力声明 + 工具集）→工厂按规约现场构造 SubAgent 列表→装配进主管执行→会话级回收。

最小可行改造方向（不改框架，仅改装配时机）：
1. `get_main_agent()` → `get_main_agent(task_query)`，放弃全局单例
2. 引入 `SubAgentFactory.build(role_spec)` + 工具注册表（按任务从池里挑工具组装）
3. 每次请求重写 system_prompt 注入可用角色清单，或用 LangGraph 动态图
4. 按 `role_spec` 哈希做 LRU 缓存，避免每次重建图的成本
5. 子 agent 生命周期：会话级缓存 + 超时回收

---

## 成熟开源项目对照

> 调研日期 2026-08-11，均经 webfetch GitHub README 核实

| 项目 | Stars | License | 状态 | 动态创建 agent 能力 | 与本项目契合度 |
|------|------:|---------|------|---------------------|----------------|
| **CrewAI** | 56.9k | MIT | 活跃 | **Flows 里运行时现场构造 Crew**：`@listen`/`@router` 装饰的方法内 `Agent(...)`+`Task(...)`+`Crew(agents=[...]).kickoff()`，按中间结果条件路由到不同 crew | ★★★ 最高 |
| **MetaGPT** | 69.8k | MIT | 活跃 | `Code=SOP(Team)`，Role 一等公民可实例化；**AFlow**（ICLR 2025 oral, top 1.8%）自动生成 agentic workflow 拓扑 | ★★ 学术前沿 |
| **AutoGen** | 60.4k | MIT | **维护模式** | `AgentTool` 把子 agent 包成 tool 给主管调（与本项目 `task` 委派同思路，**静态**）；GroupChat 模式 | ★ 思路同构 |
| **Microsoft Agent Framework (MAF)** | — | — | 1.0 production-ready | AutoGen 官方继任者，企业级多 agent 编排，**原生支持 A2A + MCP**，跨 runtime 互操作 | ★★ 值得跟踪 |

### 1. CrewAI（最贴近本项目改造方向）

README 的 Flows 示例直接展示了"运行时动态造团队"：

```python
class AdvancedAnalysisFlow(Flow[MarketState]):
    @listen(fetch_market_data)
    def analyze_with_crew(self, market_data):
        # 运行时现场造 agent + task + crew
        analyst = Agent(role="Senior Market Analyst", ...)
        researcher = Agent(role="Data Researcher", ...)
        analysis_crew = Crew(agents=[analyst, researcher], tasks=[...])
        return analysis_crew.kickoff(inputs=market_data)

    @router(analyze_with_crew)
    def determine_next_steps(self):
        if self.state.confidence > 0.8: return "high_confidence"
        ...
```

- **Crews**（自治团队，role-based）≈ 本项目"主管+子agent"
- **Flows**（事件驱动 + `@router` 条件分支）≈ 本项目"按任务规约决定造哪些子 agent"
- hierarchical process 自动分配 manager agent 做规划与委派，与本项目主管模式一致
- 原生支持 MCP/A2A

**可借鉴点**：把本项目的 `get_main_agent()` 改成"每请求一个 Flow step"，在 step 内按 `task_query` 现场构造 `subagents=[...]`，用 `@router` 做意图路由（复用现有 `agent/intent/classifier.py`）。

### 2. MetaGPT / AFlow（学术前沿，自动搜拓扑）

- MetaGPT 的 Role/Env 机制：Role 是一等公民，`metagpt.roles` 下可按需实例化
- **AFlow**（`arxiv.org/pdf/2502.12018` 相关，ICLR 2025 oral #2 in LLM-agent category）：**自动生成 agentic workflow**——不只是动态造 agent，而是自动搜 agent 编排拓扑
- `DataInterpreter` 是单 agent 动态规划执行的代表

**可借鉴点**：长期方向可参考 AFlow 的"workflow 自动搜索"，但短期过重；Role/Env 的"角色即类型"思想可借。

### 3. AutoGen / MAF（思路同构 + A2A 演进方向）

- AutoGen 的 `AgentTool` 把子 agent 包成 tool 给主管调——与本项目 deepagents 的 `task` 委派**思路完全一致**，但都是静态注册
- ⚠️ AutoGen 已进入维护模式，官方明确建议迁移到 **Microsoft Agent Framework (MAF)**
- **MAF 1.0** production-ready，原生支持 **A2A + MCP**，跨 runtime 互操作

**可借鉴点**：MAF 是 A2A 协议的官方落地参考（呼应 `refactor-plan.md` W1-1 的"shared-schemas 对照 A2A 长期演进"）；若本项目未来要从 Agent Protocol 演进到 A2A，MAF 是首选对照。

---

## 推荐路径

| 阶段 | 动作 | 参考 |
|------|------|------|
| 短期 | 把 `get_main_agent()` 改为按 session 构造，`subagents=` 由 `SubAgentFactory.build(task_query)` 产出，按 role_spec 哈希 LRU 缓存 | CrewAI Flows 的"step 内现场造 crew" |
| 中期 | 引入 `@router` 式意图路由，复用现有 `agent/intent/classifier.py`，按意图选不同子 agent 组合 | CrewAI `@router` + 本项目 intent |
| 长期 | 评估 AFlow 式 workflow 自动搜索；评估从 Agent Protocol 演进到 A2A（对照 MAF） | MetaGPT AFlow / MAF |

---

## 待进一步核实

- [ ] CrewAI Flows 的 `Crew(agents=[...])` 是否支持 deepagents 的 `AsyncSubAgent`（远程子服务）形态——决定能否复用本项目 wenda/zhiku/kefu adapter
- [ ] MetaGPT AFlow 的代码可用性（`examples/` 下是否有可跑的 workflow 自动搜索样例）
- [ ] MAF 的 A2A server 适配成本——wenda-adapter/kefu-adapter 是否能低成本升级为 A2A server
- [ ] LangGraph 原生动态图（conditional edges + 运行时 add_node）是否比引入 CrewAI 更轻量——本项目已依赖 langgraph 1.2.10
