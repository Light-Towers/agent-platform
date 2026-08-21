# 技术债清单：写死判定逻辑（Hardcoded Logic Debt）

> 登记日期：2026-08-18
> 关联：ADR-0004 类型化记忆阶段4、双轨架构分析 `TB-9`、双轨收敛 `plan-e` S-5
> 状态：全部已修复（TD-3~TD-10 全量闭环）

## 背景

ADR-0004 阶段4 的候选B（`eval/memory_reuse_llm.py`）评审中，发现 `_PREFERENCE_SIGNALS` 为写死关键词常量，
用于"跨轮记忆复用"的退化兜底判定。扩展排查后确认：项目内存在多处同类"写死判定逻辑"——即运行时业务判定依赖
硬编码常量元组 / 固定数值阈值 / 关键词硬映射，而非从配置、模型推理或运行时数据推导。

本文档统一登记，便于后续迭代排期。严重程度分级：
- 🔴 高：写死且无 LLM/配置兜底，换种表述即误判，具生产风险
- 🟠 中：有主路径兜底，但写死值仍不健壮（阈值跨场景不合理 / 含 typo）
- 🟡 低：有 LLM/配置兜底，仅词表或示例应外置，影响隐蔽

---

## 🔴 高风险

### TD-1 kefu 意图路由为纯关键词 if-else（与 docstring 脱节）
- 文件：`kefu-service/kefu_agent/graph.py:30-41`
- 现状：客服意图纯 `if kw in msg` 硬匹配，`else → knowledge`；"谢谢"独立消息覆盖其他意图。
- 矛盾：`graph.py:3` docstring 声称"LLM 驱动的意图路由（复用 Phase 3）"，实际未调 LLM、未接 classifier。
- 影响：换种说法即误路由；注释误导维护者以为已统一。
- 范围说明：双轨收敛 `plan-e` 的 **S-5 范围外声明**明确 kefu 符合性核验"本期不纳入"，故未被统一意图架构覆盖。
- 建议：① 修正 docstring 为真实状态；② 或令 kefu 意图节点复用 `agent_federation/agent/intent/classifier.py`（真正统一）。
- 修复（v2 任务二）：`intent_node` 改为复用统一意图架构 `agent_core.intent`
  （`is_chitchat` 短路闲聊 + `classify_intent` 取 `IntentLabel`）；仅保留
  CUSTOMER_SERVICE 大类下订单/物流/售后的**业务二级分流**关键词（职责属业务路由，非意图识别）。
  docstring 已澄清为"复用统一意图架构"，消除误导。
- 状态：✅ 已修复

### TD-2 kefu 售后类型纯关键词判定
- 文件：`kefu-service/kefu_agent/services.py:144-154`
- 现状：`if "退款" in msg → "退款"`，与 TD-1 词表重复且不一致（"退钱"等说法全漏）。
- 建议：与 TD-1 一并统一到 classifier。
- 修复（v2 任务二）：`extract_issue_type` 增加统一意图域校验
  （仅 `CUSTOMER_SERVICE` 域才细分退款/换货/维修/退货），并澄清其职责为
  **售后业务 slot 提取**（非意图分类），与 `agent_core.intent` 边界划清；
  函数改为 async，调用方 `postsale_flow.collect_issue_type` 已加 `await`。
- 状态：✅ 已修复

---

## 🟠 中风险

### TD-3 agent_federation 意图降级关键词含 typo
- 文件：原 `agent_federation/agent/intent/classifier.py:89-103`（已不存在）
- 现状：WS-6 统一意图架构已将分类器迁移到 `agent_core/intent/classifier.py`，关键词数据外置到 `data/prototypes.json`（数据驱动），原 typo "2么" 不再存在。
- 状态：✅ 已由 WS-6 数据外置隐式解决

### TD-4 意图置信度阈值多处写死且重复
- 文件：原 `agent_federation/agent/intent/llm_judge.py:17-18,87,97`、`classifier.py`（已不存在）
- 现状：WS-6 统一意图架构已将阈值收敛到 `agent_core/intent/models.py` 单一来源（`L1_THRESHOLD=0.8` / `CLARIFY_THRESHOLD=0.5`），`classifier.py` 和 `llm_judge.py` 均 import 自此处，不再重复。
- 状态：✅ 已由 WS-6 统一意图架构隐式解决

### TD-5 商品名确认阈值写死
- 文件：`zhanggui-zhiku/.../node_item_name_confirm.py:170-171`
- 现状：`score>0.85` / `>=0.6` 固定阈值；跨类目相似度分布不同，易误确认。
- 修复（2026-08-21）：阈值改为环境变量 `ITEM_CONFIRM_HIGH_THRESHOLD` / `ITEM_CONFIRM_MID_THRESHOLD`（默认 0.85 / 0.6，与原硬编码一致），可按部署环境调整。
- 状态：✅ 已修复（参数化，智能阈值待采集基线后评估）

### TD-6 typed 记忆遗忘阈值 + 老化天数写死
- 文件：`agent-core/agent_core/memory/typed.py:225-238`
- 现状：`forget_threshold=0.1` + SQL 内 `"30 days"` 写死。记忆生命周期不可配，跨业务不合理。
- 关联：即 ADR-0004 候选A（智能阈值）驳回提到的固定阈值；待采集基线后参数化。
- 建议：从 settings 读取；采集重要性/老化基线数据后再调参。
- 修复（v2 TD-6 最小修复）：阈值/老化天数改为从环境变量读取
  （`MEMORY_FORGET_THRESHOLD` / `MEMORY_FORGET_AGE_DAYS`，默认 0.1 / 30）；
  新增 `memory_forget_threshold()` / `memory_forget_age_days()` helper；
  `consolidate` 签名加 `age_days: int | None = None`（SQL 用 `interval '%s days'` 参数化），
  下游 `agent_federation/agent/memory/semantic_memory.py` 与 `app/memory/memory_backend.py`
  的 `consolidate` / `consolidate_memories` 同步透传 `age_days`，向后兼容
  （旧调用仅传 `forget_threshold` 仍可用）。`consolidate` 新增诊断日志输出实际阈值/天数/删除条数。
- 状态：✅ 已修复（参数化基线；智能阈值"候选A"仍待基线采集后评估，非本次范围）

---

## 🟡 低风险

### TD-7 app 路由特征词硬映射
- 文件：`applications/agent_server/agent/router.py`
- 现状：`SQL_HINTS` / `RAG_HINTS` 等特征词硬映射。有 LLM 路由主路径兜底。
- 修复（2026-08-21）：特征词外置到 `data/route_hints.json`（数据驱动，`@lru_cache` 读盘），代码仅保留数据缺失兜底；新增词不再改代码。
- 状态：✅ 已修复

### TD-8 longterm 抽取 prompt 内嵌具体偏好示例
- 文件：`applications/agent_server/memory/longterm.py:30-41`
- 现状：抽取 prompt 内嵌"财务/简洁报表"具体 few-shot 示例，引导模型偏向特定偏好。
- 修复（2026-08-21）：示例泛化为中性模板 `<用户偏好或事实的中性描述>`，不再内嵌具体职业/偏好。
- 状态：✅ 已修复

### TD-9 zhanggui eval 超参写死
- 文件：`zhanggui-zhiku/eval/run_eval.py:63-64`
- 现状：评测超参 `0.8/0.2/0.25` 写死，与线上 `retrieval.yaml` 可能不一致。
- 修复（2026-08-21）：`_RUNTIME_BASELINE` 改为从 `retrieval_cfg` / `rerank_cfg` 读取，不再硬编码超参，与线上配置保持同步。
- 状态：✅ 已修复

### TD-10 admission 状态枚举写死进 SQL
- 文件：`packages/agent-runtime/agent_runtime/admission.py`、`applications/agent_server/api/routes.py`
- 现状：状态枚举 `'admitted','queued','rejected'` 写死进 SQL 字符串和比较逻辑。
- 修复（2026-08-21）：`schemas.py` 新增 `ADMISSION_ADMITTED/QUEUED/REJECTED` 常量；`admission.py` 全量替换为常量引用；`routes.py` 同步 import 常量替代硬编码字符串。
- 状态：✅ 已修复

### TD-11 隔离键命名语义噪音（session_id 残留变量/字段名）
- 关联：PR#10 审核（2026-08-18）非阻塞残留项
- 现状：PR#10 已将隔离主键统一为 `workspace_id`，但仍有两处命名未同步：
  - `agent_federation/agent/main_agent.py` 局部变量（已修 B）→ 原 `session_id_token` 已重命名为 `thread_token`（2026-08-18 修复）。
  - `agent_federation/eval/run_eval.py:51` 评测报告输出字段（已修 C）→ 原 `"session_id"` 已改为 `"workspace_id"`（2026-08-18 修复）。
  - `async_subagents.py:104` 跨服务 HTTP payload `session_id` 字段：属独立远程契约（kefu/wenda 接口），**保持不变**，不登记修复。
- 结论：代码侧语义噪音已清零；仅保留远程契约字段。
- 状态：✅ 代码侧已修复，远程契约维持

### TD-12 docs 旧 `run_deep_agent(session_id=)` 签名文本残留
- 关联：PR#10 审核（2026-08-18）非阻塞残留项
- 文件：`agent_federation/eval/PROPOSAL.md:157`（已修 F）→ 示例代码 `session_id=sid` 已改为 `workspace_id=sid`。
- 其余文档（`docs/architecture-improvement-plan.md` 等）中的 `session_id` 属 `app/` 平台真实 API 参数名（如 `GET /history?session_id=`），与 agent_federation 隔离键无关，**不改动**。
- 结论：agent_federation 侧 docs 已同步；app 侧真实参数名保持。
- 状态：✅ 已修复（仅 agent_federation 侧）

### TD-13 内核 `user_id` 形参语义与全局 `workspace_id` 隔离键不一致
- 关联：PR#10 审核（2026-08-18）独立补充项
- 现状：`agent_core.memory.{recall_typed,remember_fact}` 形参与 PG/Milvus 列名均为 `user_id`，
  而 agent_federation 调用处（`agent_federation/agent/memory/main_agent_memory.py`）传的是 `workspace_id`。
  隔离主键**正确传递**（`workspace_id` 即落于内核 `user_id` 形参位），无功能缺陷。
- 风险：跨层命名错位易误导维护者误判"双重隔离/错位落库"。
- 建议：**仅 docstring 澄清，不重命名内核形参/列**（内核为跨包共享契约，重命名破坏 schema 与多包兼容）。
  `main_agent_memory.py` 模块 docstring 已补充 TD-E 澄清段（2026-08-18）。
- 状态：✅ docstring 已澄清，内核命名维持

---

## 已修复

### TD-0 eval 跨轮记忆雷达写死信号（已完成）
- 原：`eval/memory_reuse_llm.py` 的 `_PREFERENCE_SIGNALS` / `strong` 写死关键词。
- 修复（commit `248f0e9`，已 push PR#10）：退化兜底改为直接 SKIP、删除写死常量；信号集不再含题面自带词。
- 状态：✅ 已修复

---

## 交叉引用
- `docs/dual-track-architecture-analysis.md:24-28`：意图分类双份未对齐单一真相源 → 待办 `TB-9`（未排期）
- `docs/plan-e-dual-track-convergence.md` S-5：kefu 符合性核验范围外，本期不纳入
- 说明：本文档 TD-1/TD-2 即 `TB-9` 在 kefu 侧的具体落点；统一意图架构（agent_federation embedding 主路径）已完成，
  但 kefu 为漏网之鱼。

## 排期建议
1. ~~高优先：TD-1/TD-2（生产链路，且注释误导）—— 已修复（v2 任务二）~~
2. ~~中优先：TD-6（参数化阈值/老化天数）—— 已修复（v2 TD-6 最小修复；智能阈值候选A 仍待基线采集）~~
3. ~~中优先：TD-4/TD-3 —— 已由 WS-6 统一意图架构隐式解决~~
4. ~~低优先：TD-5/TD-7~TD-10 —— 全部已修复（2026-08-21）~~

---

## 新增（v2 任务二）

### TD-14 子 Agent 委派可观测性缺失（熔断/降级无统一指标）
- 关联：P3 熔断保护已实现（`circuit_breaker.py` + `async_subagents.py` 健康短路 + 重试 + 兜底），
  但状态变化仅 `logger.warning/info`，无统一指标/事件上报，运维不可见。
- 修复（v2 任务二）：
  - `agent_core.monitor.ToolMonitor` 新增 `report_circuit(state, message, data)` 公共方法，
    复用既有监控通道（WebSocket + 回调 + 日志）。
  - 新增 `agent_federation/agent/metrics.py`：进程内计数器
    （`circuit_open_total` / `circuit_half_open_total` / `circuit_closed_total` /
    `delegation_success_total` / `delegation_failure_total` / `degrade_total` + 熔断状态快照），
    零外部依赖（遵循内核零依赖铁律）。
  - `circuit_breaker.py` 状态转换统一经 `_transition()` 触发 `record_circuit_state`（计数 + monitor 上报）。
  - `async_subagents.py` 委派主路径加 langfuse `@observe` 埋点、`monitor.report_assistant` 上报、
    `record_delegation` 计数（健康短路 / 熔断短路 / 远程成功 / 降级兜底）。
  - `api/server.py` 暴露 `GET /metrics` JSON 端点（标准 scraping 可后续桥接 OpenTelemetry exporter）。
- 状态：✅ 已修复（指标暴露 + tracing 埋点）
