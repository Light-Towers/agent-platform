# 完整可观测链路分析模型 · 目标态与差距方案（2026-10-14）

> 性质：**方案文档，不含任何代码改动**。触发原因：需求方问"一个完整的可观测链路分析模型应该长什么样"，
> 并要求"如有不足，不要改代码，记录下方案"。
> 本文的"现网事实"全部来自 2026-10-13/14 的实测读数（见 `docs/operations/evidence/2026-10-14-morning-state/readings.md`
> 与 `docs/operations/observability-pitfalls.md`），不是推测；"目标态"来自公开标准与产品文档，来源见文末。
> 关联：`docs/plans/plan-langfuse-wiring-2026-10-13.md`（已落地的接线）、手册 §10（现网怎么看链路）、
> 台账 ⑥⑬⑲⑳㉑㉒㉓。

## 1. 目标态：六层，缺一层就退化成一堆日志

### L1 采集与语义（一次运行被拆成什么）

行业正在收敛到 **OpenTelemetry GenAI 语义约定**（已从 OTel 主仓移到独立仓库维护）。要点：

- **span 树按"真实发生过的动作"建**，不许为"Agent 大概在思考/规划"虚构 span：
  ```
  POST /query                       (SERVER，请求根)
  └─ invoke_agent {agent.name}      (INTERNAL，一次 agent 调用，≠ 整个会话)
     ├─ {op} {model}  例 chat deepseek-ai/…   (CLIENT，一次模型推理)
     ├─ execute_tool {tool.name}     (INTERNAL，一次工具/能力执行)
     │   └─ 下游 HTTP/DB 子 span      (自动插桩继续挂)
     ├─ retrieve / embedding / rerank 级 span
     └─ event：retry / guardrail 命中 / 决策分支
  ```
- **命名与属性标准化**：`gen_ai.operation.name`、`gen_ai.provider.name`、`gen_ai.request.model`、
  `gen_ai.response.model`、`gen_ai.usage.input_tokens` / `output_tokens`、`gen_ai.response.finish_reasons`、
  `gen_ai.tool.name` / `gen_ai.tool.type` / **`gen_ai.tool.call.id`**（把"模型发出的工具调用"与"实际执行"对上，
  这是"它到底调没调、调了几次"的唯一硬锚）；错误用通用约定 `error.type` + span status，而不是只有一枚布尔。
- **长 span 是反模式**：不要让一个 span 跨过等待用户输入的数小时（活跃耗时被稀释、采样失真）。
- **插桩与后端解耦**：同一份 `gen_ai.*` 语义可以进 Langfuse / Phoenix / Datadog / Honeycomb，
  换后端不改埋点。

### L2 关联维度（能不能"一条查询问出是谁在烧 token、谁最慢"）

trace id 只是骨架。目标态必须同时具备：**`session_id`（多轮归组）· `user_id`/租户 · `request_id` ·
tags（环境/版本/特性开关）· prompt 名与版本 · `tool_call_id` · 跨服务 context propagation**。
Langfuse 把这些做成一等公民（Trace 带 `user_id`/`session_id`/`tags`/`metadata`，Observation 有语义类型
`span`/`generation`/`event`/`tool`/`agent`/`retriever`/`embedding`/`guardrail`/`evaluator`，
Score 直接挂在 trace/span/generation 上）。

⚠️ 接入时的一个真实陷阱（社区实测踩过）：**observation 类型由上报端指定，不是名字里有 `Tool:` 就自动变 tool**；
经 OTLP 上报时类型写在 `langfuse.observation.type`，读回 v2 API 显示为大写枚举（`GENERATION` 等）。
⇒ 验收时必须**同时核对"工具名"和"observation 类型"**，只看 UI 列表会得出假结论。

### L3 内容策略（原文进不进观测面，这是治理问题不是开关问题）

标准的默认值很明确：**GenAI 内容默认不捕获**。完整 prompt、tool schema、arguments、results 属 **opt-in**，
因为它们可能含口令、SQL、个人信息与大段文档；默认只留元数据（工具名、类型、call id、结果状态、大小）。
开启的前提是三条同时成立：**明确的调试环境 + 字段级脱敏 + 严格访问控制**，并且**短期保留**。
（OTel 侧对应 `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` 一类开关。）

### L4 质量信号（可观测 ≠ 只有链路）

- **在线**：用户反馈/评分写回成 Score（赞踩、人工标注、业务结果回填）；
- **自动评**：LLM-as-judge / 规则评估器，作为 `evaluator` 类型的 observation 或 Score；
- **离线**：Dataset + Experiment（同一份输入集，跑不同 prompt/模型版本做回归对比），且**与在线 trace 同源**，
  能从一个坏 case 直接"加入数据集"。
- 缺这一层，观测面只能回答"发生了什么"，回答不了"变好了还是变坏了"。

### L5 聚合与告警

标准指标（`gen_ai.*` 家族）至少覆盖：**时延分布、token 消耗（可按 model / user / tenant 切）、
错误率（按 `error.type`）、工具成功率与耗时、每请求成本**。目标是那两句最常问的话各只需一条查询：
"谁在烧 token"、"谁最慢"。成本要**显式标注口径**（价格表算的是估计值，账单才是准数）。

### L6 数据面治理

后端可换（OTLP）· 持久存储与保留期 · 采样策略 · 访问控制与审计 · **观测面不得反噬业务**：
导出失败不阻塞主链路、进程退出 flush 必须有上界、存活探针与"深度健康"分离。

## 2. 现网对照：12 条差距（每条都带证据或台账号）

| # | 差距 | 现网事实（证据） | 目标态 |
|---|---|---|---|
| G1 | **没有工具/节点级 observation** | Langfuse 只有 `GENERATION`；callback 只挂在模型上（`applications/agent_server/agent/llm.py:30-36`），能力是普通函数调用 `_invoke("rag", …)` 不是 LangChain tool | `invoke_agent` + `execute_tool` + retrieve/embedding span，类型正确、带 `tool.call.id` |
| G2 | **属性非标准命名** | 我们写 `question_hash/thread_id/priority/request_id`，模型侧属性来自 Langfuse SDK 的 `langfuse.observation.*`；无 `gen_ai.*` | 统一 `gen_ai.*`，后端可移植、指标可自动聚合 |
| G3 | **双路埋点未收敛** | 同一请求两棵 trace（`otel.scope.name=fastapi` 与 `agent-platform`），浏览器不带 `traceparent` 时互不串联（台账 ⑲ / issue #23） | 一棵树、一个根；框架埋点与业务埋点由属性区分但同源 |
| G4 | **无 session/user 维度** | `identity_mode=single`，前端传的会话号被忽略，一律 `tenant-default` | `session_id` + 租户/用户维度进 trace 与 observation |
| G5 | **无质量信号闭环** | 没有 Score、没有反馈通道；`eval/`（15 条 golden + 双 Planner 基线）**与观测面断开**，分数不落 Langfuse | 在线 Score + 离线 Dataset/Experiment 同源互跳 |
| G6 | **prompt 无版本承载** | 无 prompt registry；generation 关联不到 prompt name/version（台账 ⑥ 的"提示词版本"那半条仍成立） | prompt 版本化，generation 可回链 ⇒ 才能做 A/B 与回滚归因 |
| G7 | **成本口径未定** | 平台无定价表、刻意不显示金额；Langfuse 会用它自带价格表算 cost | 二选一并写进界面与话术：要么显式声明"估计值/账单为准"，要么关掉该字段 |
| G8 | **内容捕获无治理** | 原文（实测 `langfuse.observation.input` 6339 字符、含检索到的资料片段）随 OTLP 进 Jaeger，而 Jaeger **无鉴权、办公网可达、内存存储**（台账 ㉓） | 默认只元数据；开内容需"环境+脱敏+权限"三件齐备 + 短期保留 |
| G9 | **保留与存储无策略** | Jaeger all-in-one 内存（进程重启即清零）；Langfuse 在 ClickHouse（持久但无保留期设定） | 明确保留期与采样；"能回溯"只由持久面承诺 |
| G10 | **跨服务链路未证** | D5.5 只证了单服务内一条请求链路（`e2e_traceparent.sh`，span 数 8）；联邦网关→子服务未测 | context propagation 端到端实测，多服务一棵树 |
| G11 | **错误语义只有布尔** | 事件面 `status.steps[].failed`，异常原文刻意不外发；span 侧无 `error.type` | `error.type` + span status，归因到类别而不丢脱敏要求 |
| G12 | **观测面反噬业务** | `/health` 同步探依赖 ⇒ 慢依赖拖垮 liveness，Pod 被当场杀（台账 ㉒，`exitCode=137`）；退出 flush 无上界（㉓之前的 ⑬） | 浅存活探针 + 深就绪/诊断分离；flush 有硬上界 |

**已经达标的部分**（别妄自菲薄）：trace id 在 Jaeger 与 Langfuse 之间可对齐（实测同 id 两边都在）；
请求根 span 与模型调用 span 的时延分解可用；用量（token）有真实承载；观测装配顺序已是硬约束并有钉用例
（`tests/observability/test_provider_reuse_otlp.py`）；对外推送面刻意不含 args/result（基线 4，
`planners/deterministic.py:246-257` 四条理由写明）。

## 3. 迁移策略（分四期，每期都能独立验收；**演示前一律不动**）

- **P0 治理先行（不改埋点语义，成本最低）**：G8/G9/G12 —— 给 Jaeger 收口（绑 `127.0.0.1` 或加认证）、
  定保留期、把 `/health` 拆成浅存活 + 深诊断。这三条是"少踩雷"，不是"加能力"。
- **P1 结构对齐（一次发布通道）**：G1/G3 —— CallbackHandler 从"只挂模型"提到"挂在这次 run 上"，
  让 LangGraph 每个节点成为带 in/out 的 observation；同时收敛双路埋点（执行 issue #23 默认方案）。
  验收必须按 L2 末尾那条陷阱：**核对 observation 类型枚举，不看 UI 名字**。
- **P2 语义标准化**：G2/G4/G11 —— 引入 `gen_ai.*` 属性层（自建映射即可，不引新框架），补 session/租户维度与
  `error.type`。这一步做完，"谁烧 token / 谁最慢"才是一条聚合查询。
- **P3 质量闭环**：G5/G6/G7 —— prompt registry + 版本回链、Score 通道（先把控制台的赞踩/人工判定落进去）、
  Dataset/Experiment 与 `eval/` 打通。
- **P4 跨服务**：G10 —— 联邦网关→子服务的 propagation 实测（这本就是方案 D5.5 欠的那一半）。

## 4. 验收标准（每期都要能被否掉）

1. **P0**：`docker ps` 显示 Jaeger 发布口不再是 `0.0.0.0`（或认证生效）；`/health` 人为拖慢依赖 5s 时
   **Pod 不被 liveness 杀**（事件面无 `Killing`）；保留期写在清单里并有读数证明。
2. **P1**：一次 `/query` 在 Langfuse 里出现 **≥3 种 observation 类型**（含 `tool` 或 `span` 级检索/能力节点），
   且每个节点有 input/output；Jaeger 里同一请求**只有一棵 trace**；`langfuse_proof.py` 的 A3 判据不退化。
3. **P2**：同一份 OTLP 数据在 Jaeger 与 Langfuse 都不需要改后端配置即可按 `gen_ai.usage.*` 聚合；
   按租户/会话各一条查询能出数。
4. **P3**：改一版 prompt ⇒ 新 trace 能回链到 prompt 版本；一条线上坏 case 一键进 dataset；
   `eval/` 的 golden 跑分与 Langfuse experiment 对得上同一批输入。
5. **P4**：跨两个服务的端到端一次请求，**两服务的 span 落在同一 trace**（拿 traceparent 做锚）。
6. **全程红线**：任何"开启内容捕获"的改动，必须同时交付字段级脱敏与访问控制说明，否则不予上线；
   测试红时**禁止删用例/收窄断言凑绿**。

## 5. 明确不做（非目标）

- 不自研观测后端，不换掉 OTLP；不为"UI 好看"去改上游 Jaeger/Langfuse 前端。
- 不在演示前动 P1 及之后任何一期（发布通道一轮 ≈25 分钟，且会新增演示残留）。
- 不把"工具调用可观测"写进任何完成标志——**现网做不到**（G1），当前只能说"步骤级可观测"。
- 不为了指标齐全而默认捕获全文（L3 的三件前提不齐就不开）。
