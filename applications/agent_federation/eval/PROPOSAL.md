# deepagents 多智能体评测提案

> 状态：v1.1（步骤 0-3+6 已落地，golden 10 题，待实跑标定）
> 来源：Issue #120 审核意见 + AUDIT.md 代码实况核对 + 主流方案联网验证（τ-bench / AgentBench / LLM-as-judge 论文）
> 定位：阶段四唯一悬而未决的核心增量；deepagents 相对 zhanggui-zhiku 的差异化面试亮点

## 1. 背景

deepagents 改造阶段一~三已完成（`CHANGELOG.md` 1.0.0 / 1.0.1，2026-08-09），阶段四文档已完成。评测是 README `待做/已知限制` 中唯一带 `⬜` 的功能性增量（`README.md:94`）：

> ⬜ 多智能体评测（golden set + 路由准确率 + 完成率）

zhanggui-zhiku 已落地单检索链路评测（`../zhanggui-zhiku/eval/`，Recall@K / MRR / nDCG + 56 条 golden + 消融）。deepagents 作为多智能体编排系统，任务级评测比检索指标更贴切，三层指标（路由 → 工具 → 任务）对应「决策质量 / 执行质量 / 结果质量」，出了问题可分层定位，可诊断性优于单一端到端 pass rate。

本提案在 Issue #120 基础上修正了 6 处与当前代码的偏差（见 §7），并经 AUDIT.md 二次审核修正 3 处漏审 + 砍掉 2 处过度设计（见 §9），固化到可落地精度。

## 2. 三层指标设计

### 2.1 路由准确率（集合匹配 + task 参数覆盖率）

**问题**：多子 Agent 协作非非此即彼。会展业务题常需「查资料 + 搜最新趋势」双路由，单标签准确率必然失真。

**设计**：

- golden 标注升级为**多标签集合**：每题标注期望路由集合 `expected_agents ⊆ {行业动态搜索, 业务数据查询, 知识库检索}`，允许 1~3 个。
- 主口径：集合匹配。报精确匹配率 + Jaccard/F1 两个口径（精确匹配严苛、Jaccard 容忍部分路由）。
- 第二口径 **task 参数必需信息覆盖率**：委派质量不止「委派了谁」，还含 task 参数（description 是否让子 Agent 能干活）。统计 description 中是否覆盖题目给定的 context 变量（主办方 / 时间 / 地点等）。

**ground truth 标注方案**（单人项目）：

- 每题由人工标注 `expected_agents` + `rationale`（标注理由）。
- **诚实边界**：单人标注存在主观性，通过多标签集合 + 双口径（严格匹配 / 宽松 Jaccard≥0.5）部分缓解，但不等于"标注正确性"。
- `rationale.source` 字段标注来源（`human`），确保可追溯。

**数据源（已就绪）**：

- 路由轨迹：`api/monitor.py:84-86` `report_assistant` 发射 `assistant_call` 事件，含 `assistant_name` + `args`（含 `description`）。
- 调用点：`agent/main_agent.py:123-126`（`monitor.report_assistant(subagent_type, {'description': tool_call['args']['description']})`）。
- 评测驱动器需给 `ToolMonitor` 加 `on/off` 订阅方法（见 §6），捕获 monitor 事件流即可拿到路由轨迹 + description。

> 修正 Issue #120：原文引用 `main_agent.py:122`，实际第 122 行是 `logger.info`，`report_assistant` 调用在第 123-126 行。

**多标签路由判定是业界尚未标准化的点**（AgentBench / τ-bench 均为单 agent + 工具，无路由准确率指标），把它做扎实本身就是面试讲点。

### 2.2 工具调用成功率（四分类统计）

**问题**：把「护栏正常生效」误报成「系统 bug」。SQL 子 Agent 的 sqlparse 防护拦截非 SELECT 是护栏工作正常，不是工具失败；zhiku_retrieve 不健康时降级返回是 SLA 事件，不是执行失败。

**设计**：拆四类分别统计，不合并为单一「失败率」。分类信号走**结构化事件**而非字符串匹配（工具返回值同时服务人类可读 + 机器可判两类消费者，字符串匹配必然打架）。

| 分类 | 定义 | 归因 | 代码证据 |
|------|------|------|----------|
| 执行异常率 | 工具抛异常 | 系统 bug / 依赖故障 | 工具函数异常捕获 |
| 护栏拦截率 | 输入被护栏拒绝 | LLM 生成非法输入（护栏正常） | `tools/sql_validation.py:22` `_validate_sql_select_only`；`db_tools.py:158-164` 动态表名白名单 |
| 空结果率 | 执行成功但返回空 | LLM 检索策略差 / 语料不足 | 工具返回空列表/空字符串 |
| 超时率 | `with_timeout` 超时 | 下游慢，可重试 | `tools/_timeout.py:21` `with_timeout` 装饰器（asyncio.wait_for，默认 30s，工具覆盖 15-20s） |

**事件采集方案**（B+C 混合发射）：

| 发射点 | 覆盖分类 | 改动 |
|--------|----------|------|
| `tools/_timeout.py` 装饰器 | 超时 / 执行异常 / **护栏拦截** | 1 处（需新增 `from api.monitor import monitor`）；按 `error_class` 区分：`asyncio.TimeoutError`→timeout，`ValueError`（来自 sql_validation）→guarded，其余→exception |
| `tools/zhiku_tools.py` 降级分支 | 降级 / 空结果 | 1 处 |
| `tools/db_tools.py` except Error + 空结果分支 | 执行异常（DB 内部错） / 空结果 | 2 处（:192 except Error 补发 exception；:174/231 空表发 empty） |

> **护栏逃逸修正（三次审核发现）**：`_validate_sql_select_only` 抛 `ValueError` → `db_tools.py` 的 `except Error`（mysql.connector.Error）不捕获 → 逃逸到 `_timeout.py` 的 `except Exception`。若 `_timeout.py` 无差别归为 `exception`，护栏拦截会被误报为系统 bug——正好与 §2.2 设计目标矛盾。修正：`_timeout.py` 按 `error_class` 区分（`ValueError`→guarded），`db_tools.py` 的 `except Error` 分支补发 `exception`（DB 内部错误不能被装饰器视为成功）。

事件载荷：

```python
monitor.report_tool_outcome(
    tool_name="...",
    outcome="timeout" | "exception" | "guarded" | "degraded" | "empty" | "success",
    error_class="ValueError" | "asyncio.TimeoutError" | None,
    detail="可选人类可读说明，仅供日志，不进返回值",
)
```

工具返回值保持人类可读，两组消费者不再打架。

> 修正 Issue #120：原文把超时隔离归给 `guarded_invoke`。实际 `guarded_invoke` 定义在 `agent-core/agent_core/tools/guarded.py:30`（默认 3s，失败返回 `{}`），由 zhanggui-zhiku 桥接；**deepagents 自身用的是 `tools/_timeout.py` 的 `with_timeout` 装饰器**，两套机制不同。
>
> 修正 Issue #120：原文说 sqlparse 三层「拦截非 SELECT/无表名」。实际三层是 ①标识符白名单正则(`sql_validation.py:16` `_validate_identifier`) ②SELECT-only(`sql_validation.py:22`) ③LIMIT 注入(`sql_validation.py:33` `_ensure_limit`)；**「无表名」校验在 `db_tools.py:158-164` 的 get_table_data 动态表名白名单里**，不在 sqlparse 三层内。

### 2.3 任务完成率（rubric + judge 去偏）

**问题**：Issue #120 提的「LLM-as-judge / 人工标注待定」需定成可复现方案。整体满意度打分不可复现、不可解释。

**设计**：

- **rubric-based 验收点清单**：每道 golden 增加 `acceptance_points`（要求答案必须包含的关键实体 / 结论）。judge 按清单逐项打 0/1，输出 `命中点数 / 总点数`。比整体满意度可复现、可解释。
  - 验收点类型只保留 `entity`（字符串包含）和 `conclusion`（语义判断），**去掉 `numeric`**（"约10万人""超过十万"等模糊数值无法精确比较，判定不可靠）。
- **judge 去偏**：用与生成不同源的 provider 做 judge（生成走 qwen，judge 走 deepseek / openai），防 self-bias 虚浮。此为业界主流做法（Zheng et al. NeurIPS'23，MT-Bench / Chatbot Arena）。
- **人工标定**：截取 10~20 题人工标注做 judge 标定，定期校准 judge 分数是否漂移。
- **参照叙事**：引用 τ-bench / τ³-bench 类任务级基准（`wiki/agi/agent/agent-evaluation-benchmarks.md:11`，airline/retail/banking 多域 + pass^k 一致性）。**pass^k 为可选增强指标，非首轮必做**——首轮不实跑，仅作面试叙事引用；基础指标稳定后可后置加。题目集即会展叙事相关，与决策记录定的「会展业务叙事」打通；zhiku 现有 50 条烫金机测试数据可留作回归测试集。

> 注：`LLM-as-judge` 概念在仓库中无先例（全仓库 grep 零命中），本提案为首次引入。

## 3. 评测集 schema

**来料**：会展 query 人工产出，或从 zhiku 语料反推。

**覆盖矩阵**（首轮只填部分格，全格后置）：

| 维度 | 取值 |
|------|------|
| 路由基数 | 单路由 / 双路由 / 三路由 |
| 子 Agent 组合 | {搜索} / {DB} / {zhiku} / {搜索+DB} / {搜索+zhiku} / {DB+zhiku} / {搜索+DB+zhiku} |
| 难度 | 简单（单步）/ 中等（多步同 Agent）/ 困难（跨 Agent 协作） |

> 首轮目标：5~15 题纯路由决策类 query（不依赖知识库内容，只测"该调哪个子 Agent"）。覆盖矩阵全格（3×7×3=63 格）为后置目标，非首轮必做。

**golden 三元组 schema**（`eval/golden.jsonl`，每行一题）：

```jsonc
{
  "id": "expo-001",
  "query": "2026 上海国际会展中心 8 月有哪些 10 万人以上规模的展会？主办方是谁？",
  "expected_agents": ["行业动态搜索助手", "业务数据查询助手"],   // 多标签集合，§2.1，必须与 prompts.yml subagent name 完全一致（见 §6 标签对齐）
  "required_context_in_description": ["上海国际会展中心", "2026年8月"],  // §2.1 第二口径
  "acceptance_points": [                                  // §2.3 rubric，只留 entity/conclusion
    {"type": "entity", "value": "上海国际会展中心", "must_contain": true},
    {"type": "conclusion", "value": "列出主办方名称", "must_contain": true}
  ],
  "rationale": {                                          // §2.1 标注可追溯
    "source": "human",
    "note": "需查最新展会动态 + 主办方数据库"
  },
  "difficulty": "中等",
  "routing_cardinality": 2
}
```

**诚实边界声明**：当前评测聚焦路由决策质量，知识库检索质量依赖 zhiku 侧会展语料就绪（Issue #120 决策要求导入，未执行）。ground truth 为单人人工标注，主观性通过多标签集合 + 双口径部分缓解。

## 4. 评测驱动器

**不走 WebSocket 全链路**（难自动化），直接脚本调 `run_deep_agent()`（`agent/main_agent.py:65`）。

**关键约束**：`run_deep_agent` 内部 `async for chunk in main_agent.astream(...)` 消费流后**不返回值**（函数无 return 语句）。最终答案通过 `monitor.report_task_result(last_msg.content)`（`main_agent.py:128`）发射。因此 runner 必须订阅 `task_result` 事件拿答案，不能依赖 `run_deep_agent` 的返回值。

**路由轨迹 + 答案采集**：需先给 `ToolMonitor` 加 `on/off` 订阅方法（见 §6），runner 订阅 `assistant_call`（路由）+ `task_result`（答案）两类事件。

**驱动器骨架**（`eval/run-eval.py`，kebab-case 命名）：

```python
# 伪代码，落地时补全
async def run_one(item):
    routed = []
    answer = []
    sid = f"eval_{timestamp}_{item['id']}"
    cb_route = lambda e: routed.append(e)
    cb_answer = lambda e: answer.append(e)
    monitor.on("assistant_call", cb_route)
    monitor.on("task_result", cb_answer)   # run_deep_agent 不返回值，靠事件拿答案
    try:
        await run_deep_agent(item["query"], workspace_id=sid)
    finally:
        monitor.off("assistant_call", cb_route)   # 防止 callback 累积串题
        monitor.off("task_result", cb_answer)
    return {
        "id": item["id"],
        "routed_agents": [e["data"]["assistant_name"] for e in routed],  # 与 golden expected_agents 全名对齐
        "descriptions": [e["data"]["args"]["description"] for e in routed],
        "answer": answer[-1]["data"]["result"] if answer else None,  # None 时 judge 判 incomplete
    }

def score_routing(pred, gold):
    pred_set, gold_set = set(pred), set(gold)
    exact = pred_set == gold_set
    jaccard = len(pred_set & gold_set) / len(pred_set | gold_set)
    return {"exact": exact, "jaccard": jaccard}

def score_rubric(answer, acceptance_points):
    # judge 用不同 provider，逐项打 0/1
    ...
```

**session_id 隔离**：runner 用专用前缀 `eval_<timestamp>_<id>`，与线上会话 `session_{uuid}` 区分；评测跑完由 `--cleanup` 清理 `output/session_eval_*` 目录（默认开，仅清理本前缀目录，不误删真实会话）。

**并发隔离**：`ToolMonitor` 是单例，并发跑多题时事件会串题。**首轮强制串行**（`Semaphore(1)`）；扩量并发时需在 callback 内按 session_id 过滤。

**成本控制**：每题一次完整 agent run token 成本不小（主模型 qwen-max 按 token 计费，见 `agent/llm.py:15`）。runner 为独立脚本进程，**不继承 API server 的 `MAX_CONCURRENT_TASKS` 信号量**，需在 runner 内自建 `asyncio.Semaphore` 限并发。

**输出**：结果 JSONL 落盘（`eval/results/<timestamp>.jsonl`），含每题路由判定 / 工具四分类 / rubric 命中。

## 5. CI 边界与回归闭环

**不进 CI**。评测费 token 且要 API key，与 `.wiki/scripts` 只跑确定性脚本的 Gate 原则一致（见根 `AGENTS.md` CI Gate 段）。

**闭环设计**：

- 本地 / 定时手动跑（`python eval/run-eval.py --limit 20`）。
- golden 增量进仓库（`eval/golden.jsonl` 受版本控制）。
- 结果 JSONL 落盘但不进仓库——**需在 `agent_federation/.gitignore` 追加 `eval/results/`**（当前 `.gitignore` 未配此条，仅有 `output/` / `updated/` 等）。
- 路由错误样本回流到 prompt 修改（`prompt/prompts.yml`），形成「评测 → 发现路由偏差 → 改 prompt → 再评测」闭环。

## 6. 与代码现状的映射

| 提案项 | 代码现状 | 动作 |
|--------|----------|------|
| 路由轨迹采集 | `monitor.py:84-86` 有发射无订阅 | **需给 ToolMonitor 加 `on/off` 方法**（~15 行） |
| 答案采集 | `main_agent.py:128` 发射 `task_result`，但 `run_deep_agent` 无 return | runner 订阅 `task_result` 事件拿答案；answer=None 时 judge 判 incomplete |
| 标签对齐 | golden expected_agents 必须与 `prompts.yml` subagent name 完全一致（"行业动态搜索助手"等，带"助手"后缀） | golden 直接用全名（推荐），或 runner 归一化 |
| task 参数覆盖率 | `main_agent.py:125` description 已传入事件 | 依赖 on/off 修正后可用 |
| report_tool_outcome 方法 | `monitor.py:81-96` 无此方法 | **需在 monitor.py 新增**（~10 行，§2.2 事件载荷） |
| 工具四分类 - 超时/异常/护栏 | `tools/_timeout.py:21` `with_timeout` | 需在装饰器内按 error_class 区分发 `report_tool_outcome`（+ import monitor） |
| 工具四分类 - DB 内部错 | `db_tools.py:192` `except Error` | 需在 except Error 分支补发 outcome=exception（否则被装饰器视为成功） |
| 工具四分类 - 空结果 | `db_tools.py:174/231` + `zhiku_tools.py` 空结果 | 需在空结果分支发 outcome=empty |
| 工具四分类 - 降级 | `zhiku_tools.py:97-99` 降级 + `:113-115` 429 限流 | 需在降级分支 + 429 分支发 outcome=degraded |
| run_deep_agent 入口 | 已就绪：`main_agent.py:65` | runner 直接调，但不依赖返回值 |
| golden 集 | 未建 | 新建 `eval/golden.jsonl` |
| 评测驱动器 | 未建 | 新建 `eval/run-eval.py` |
| rubric judge | 未建 | 新建 `eval/judge.py`（用不同 provider） |
| 评测集 schema | 未建 | 本提案 §3 即 schema，落地时固化为 `eval/SCHEMA.md` |
| .gitignore | 未配 `eval/results/` | 追加一行 |
| LLM-as-judge | 仓库无先例 | 本提案首次引入 |

## 7. 对 Issue #120 的修正清单

| Issue 原文 | 代码实况 | 修正 |
|------------|----------|------|
| `main_agent.py:122 的 report_assistant` | 第 122 行是 `logger.info`，`report_assistant` 在 123-126 | 行号修正 |
| 提案停留在「初步设计，需实践迭代」 | 全仓库该字样零命中，无专门提案文档 | 本提案即首次落盘 |
| `eval/` 目录未建 | `zhanggui-zhiku/eval/` 已落地，仅 deepagents 下未建 | 限定为 deepagents eval/ 未建 |
| `guarded_invoke` 超时隔离 | deepagents 用 `tools/_timeout.py` 的 `with_timeout`，`guarded_invoke` 在 agent-core 内核 | 归属修正 |
| sqlparse 三层「拦截非 SELECT/无表名」 | 三层是标识符白名单 + SELECT-only + LIMIT 注入；无表名校验在 db_tools.py | 防护层归并修正 |
| LLM-as-judge 作为建议 | 仓库无先例 | 标注为首次引入 |

## 8. 落地顺序

0. ✅ `.gitignore` 追加 `eval/results/`；在 `monitor.py` 新增 `report_tool_outcome` 方法（~10 行）。
1. ✅ 固化 §3 schema → 建 `eval/golden.jsonl` 首批 10 题（含多标签路由 + acceptance_points，纯路由决策类；expected_agents 用 `prompts.yml` subagent 全名）。
2. ✅ 写 `eval/run-eval.py`：给 ToolMonitor 加 `on/off` + 调 `run_deep_agent` + 订阅 `assistant_call`/`task_result` 事件 + 路由集合匹配 + finally off。
3. ✅ 写 `eval/judge.py`：rubric 逐项打分，judge 用不同 provider（环境变量 `EVAL_JUDGE_*` 覆盖，缺省降级同主模型并告警）。
4. 跑首批，人工标定 10 题 judge 分数。
5. 路由错误样本回流 `prompt/prompts.yml`，迭代。
6. ✅ 工具四分类：`_timeout.py` + `zhiku_tools.py` + `db_tools.py` 发 `report_tool_outcome` 事件。
7. （后置）扩 golden 到覆盖矩阵更多格。
8. （可选）pass^k 一致性压测（k=3 起步），基础指标稳定后执行。

**依赖链为串行**：schema 定 acceptance_points → runner 才能解析 golden → judge 才能打分。§6 映射表的所有"需改代码"项在步骤 2/6 完成。

## 9. 已砍项（过度设计，透明声明）

经 AUDIT.md 二次审核 + 主流方案联网验证（τ-bench 1.4k★ / AgentBench 3.7k★ / LLM-as-judge Zheng et al. NeurIPS'23），以下设计因"面试讲不清 / 投入产出比低 / 无学术背书"砍掉：

| 砍掉项 | 砍掉理由 |
|--------|----------|
| LLM-as-annotator 对立双视角 + 三方仲裁 + Jaccard 一致性度量 | 单人项目 5-15 题人工标即够；方案论文味重，面试 30 秒讲不清，追问"ground truth 是人还是模型"反暴露弱点；无学术/工业背书（LLM 数据增强标注有论文，但"对立双视角+仲裁"无公认范式） |
| 覆盖矩阵全格 63 题 | 子项目 golden 5-15 题够面试讲；63 题标注 + 跑评投入产出比低 |
| pass^k 实跑（k=3 起步，非首轮） | 首轮成本失控；保留为可选后置，面试叙事引用 τ-bench 即够 |
| numeric acceptance_points | "约10万人""超过十万"等模糊数值无法精确比较，判定不可靠 |
