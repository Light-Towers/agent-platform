# PROPOSAL.md 审核报告

> 审核日期：2026-08-09
> 审核方式：代码实况核对 + 可行性推演
> 审核范围：`deepagents/eval/PROPOSAL.md` 全文

---

## 一、审核结论

**总体评价**：提案方向正确（三层指标、多标签路由、rubric-based judge），但存在 **5 处代码实况偏差**、**5 处可行性缺口**、**2 处逻辑依赖断裂**。需在修正后采纳，不能直接按原文落地。其中偏差 4/5 + 缺口 5 为二次审核补录（见 §八）。

**修正后采纳** —— 核心设计（三层指标 + 多标签路由 + rubric judge）成立，但实现路径需调整。

---

## 二、代码实况偏差（必须修，否则落地即报错）

### 偏差 1：§4 驱动器伪代码调用不存在的方法

**问题**：`monitor.on("assistant_call", events.append)` —— `ToolMonitor` 没有 `on()` 方法。

**代码实况**（[`api/monitor.py:23-99`](deepagents/api/monitor.py)）：
- `ToolMonitor` 只有发射端：`report_assistant()` → `_emit()` → WebSocket / `builtins.runtime.stream_writer`
- 没有内存中的事件订阅/回调机制
- `_emit` 是私有方法，外部无法直接拦截

**影响**：评测驱动器按提案写法会直接 `AttributeError`。

**建议方案**：给 `ToolMonitor` 新增轻量订阅机制（约 15 行，零破坏）：

```python
# api/monitor.py 新增
_callbacks: Dict[str, List[Callable]] = {}

def on(self, event_type: str, callback: Callable):
    self._callbacks.setdefault(event_type, []).append(callback)

def off(self, event_type: str, callback: Callable):
    if event_type in self._callbacks:
        self._callbacks[event_type].remove(callback)

# _emit 方法末尾追加
for cb in self._callbacks.get(event_type, []):
    try:
        cb(payload)
    except Exception:
        pass
```

**替代方案**（若不愿改 monitor）：评测 runner 直接消费 `run_deep_agent` 的 async generator，在 chunk 中检测 `node_name == 'model' + tool_calls['name'] == 'task'` 来推断路由。但此方案会重复 `main_agent.py:117-126` 的逻辑，耦合度高，不推荐。

---

### 偏差 2：§6 映射表声称"无需改代码"，实际必须改

**问题**：映射表第 1 行"路由轨迹采集 → 已就绪 → 无需改代码"与偏差 1 矛盾。

**代码实况**：`ToolMonitor` 没有订阅接口，评测 runner 无法拿到事件。

**影响**：§6 给读者错误信心，可能导致评测开发时低估工作量。

**建议方案**：§6 映射表第 1 行改为：

| 提案项 | 代码现状 | 动作 |
|--------|----------|------|
| 路由轨迹采集 | `monitor` 只有发射无订阅 | **需给 ToolMonitor 加 `on/off` 方法**（~15 行） |

---

### 偏差 3：§2.2 工具四分类的"识别"规则未定义

**问题**：提案说 runner "需识别护栏拒绝信号""需识别降级返回 vs 正常空结果"，但没有给出判定规则。

**代码实况分析**：

| 分类 | 实际信号 | 判定规则（建议） |
|------|----------|----------------|
| 护栏拦截 | `db_tools.py` 中 `ValueError` 被 `except Error` 捕获后返回字符串 `"查询出现异常：..."` | 返回值含 `"非法标识符"` / `"仅允许 SELECT"` / `"表名 'xxx' 不存在"` |
| 降级返回 | `zhiku_tools.py:97-99` 不健康时返回 `"知识库服务暂不可用..."` | 返回值含 `"暂不可用"` / `"已探测到不健康"` |
| 超时 | `tools/_timeout.py` | 装饰器返回 `"工具 xxx 执行超时..."` |
| 空结果 | 工具正常返回但内容为空 | 返回 `"没有可用的表"` / `"未检索到相关内容"` |

**问题**：这些判定规则依赖**字符串匹配**，工具返回值文案一变，分类就错。没有版本契约。

**根本矛盾（grilling 确认）**：工具返回值同时服务两类消费者——①人类可读（主管 LLM 转述给用户的自然语言）②机器可判（runner 四分类）。靠字符串匹配硬拆，必然打架。更糟的是，若给返回值加 `[GUARDED]`/`[DEGRADED]` 前缀标记，主管 LLM 会把这些内部符号原样转述给用户，语义体验变差。

**已定方案（用户确认）**：runner 走**内存事件采集而非解析字符串**。工具侧额外发射一个**结构化的"工具结果"事件**（含 `tool_name` + `outcome` + `error_class` 等），runner 订阅该事件拿结构化分类信号；**工具返回值保持人类可读**，两组消费者不再打架。

**发射点设计（B+C 混合，待用户最终确认）**：

| 发射点 | 覆盖的分类 | 改动 | 理由 |
|--------|-----------|------|------|
| `tools/_timeout.py` 装饰器（B） | 超时 / 执行异常 | 1 处 | 装饰器统一包裹所有被装饰工具，最省事；但它只能判"超时/异常/正常"三类，看不到工具内部语义 |
| `tools/db_tools.py` + `tools/zhiku_tools.py` 分支（C） | 护栏拦截 / 降级 / 空结果 | 2 文件 | 这三类只有工具内部知道语义（sqlparse 返回"仅允许 SELECT"、zhiku 不健康返回"暂不可用"、空表返回"没有可用的表"），装饰器层面拿不到 |

即 `_timeout.py` 管超时/异常（统一），`db_tools.py` + `zhiku_tools.py` 在各自的护栏/降级/空结果分支用 `monitor.report_tool_outcome()` 补发。覆盖四分类完整，改动集中在 3 个文件。

**替代方案**（若不愿改 `_timeout.py`）：所有四类都在工具内部发射——覆盖完整但 6 个工具都要改，侵入大，不推荐。

**事件载荷建议**：

```python
monitor.report_tool_outcome(
    tool_name="...",
    outcome="timeout" | "exception" | "guarded" | "degraded" | "empty" | "success",
    error_class="ValueError" | "asyncio.TimeoutError" | None,
    detail="可选人类可读说明，仅供日志，不进返回值",
)
```

> **状态**：方案 A（结构化事件 + 返回值可读）已定；发射点 B+C 混合已定（`_timeout.py` 管超时/异常，`db_tools.py`+`zhiku_tools.py` 管护栏/降级/空结果）。
>
> ⚠️ **发射点表已被漏审 7 修正**：护栏拦截（ValueError）实际逃逸到 `_timeout.py` 的 `except Exception`，需在装饰器按 `error_class` 区分（ValueError→guarded），不能归到 `db_tools.py` 护栏分支。见 §八 漏审 7 + PROPOSAL §2.2。

---

## 三、可行性缺口（可能导致落地后无法跑通）

### 缺口 1：评测成本失控（§4）

**问题**：20 题 × pass^k(k=8) = 160 次完整 agent run + 160 次 judge 调用。SiliconFlow 免费 tier 日限额和并发上限未验证。

**算术**（基于已实测数据）：
- 单次 agent run ≈ 主管 1 次 LLM + 子 Agent 1-3 次 LLM + 工具调用
- ~~Qwen3.5-4B 单次 ~0.5s~~（注：模型名过时，实际主模型为 qwen-max 按 token 计费，见漏审 10；以下算术仅作量级参考）
- 若并发跑，需验证 SiliconFlow 免费 tier 的 RPM/TPM 限制

**建议方案**：
1. **首轮只做 5 题 × 单次 run（不跑 pass^k）**，验证成本基线后再扩
2. pass^k 作为 P2 后置，等基础指标稳定后加
3. judge 首轮用**人工标注**而非 LLM-as-judge，降低依赖
4. 在 `eval/README.md` 中明确标注"首轮成本基线：5 题 × 1 轮 ≈ X 元 / Y 秒"

---

### 缺口 2：acceptance_points 的判定模糊（§2.3 / §3）

**问题**：schema 中的 `{"type": "numeric", "value": ">=100000", "desc": "规模阈值"}` 如何被 judge 精确判定？

**代码实况**：LLM judge 读自然语言回答，要从中提取数值并做 `>=` 比较，存在以下风险：
- 回答写"约 10 万人"——"约"是否算命中？
- 回答写"超过十万人"——无具体数字，语义满足但无法数值比较
- 回答写"100,000"——带逗号格式需预处理

**建议方案**：
1. **简化 acceptance_points 类型**：只保留 `entity`（字符串包含）和 `conclusion`（语义判断），去掉 `numeric`
2. 或给 `numeric` 类型增加 `tolerance` 字段（如 `"tolerance": "approximate"` 允许"约"）
3. judge prompt 中显式给出判定规则示例

---

### 缺口 3：多标签路由的 ground truth 主观性（§2.1 / §3）

**问题**：同一道题，不同人标注的 `expected_agents` 可能不同。

**示例**："查询 2026 年上海国际会展中心 8 月有哪些展会？"
- 标注者 A：只需要网络搜索 → `["行业动态搜索"]`
- 标注者 B：需要搜索 + 查内部数据库确认主办方 → `["行业动态搜索", "业务数据查询"]`
- 标注者 C：需要搜索 + 查知识库确认场馆信息 → `["行业动态搜索", "知识库检索"]`

**影响**：ground truth 不唯一，路由准确率的"准确率"本身存疑。

**已定方案（单人项目，原"2 人独立标注"降级为 LLM-as-annotator）**：

> ⚠️ **本方案后被 §八 过度设计判定砍掉**（无学术背书 / 面试讲不清 / 单人项目人工标即够），见 PROPOSAL §9。以下内容保留作为审核历史记录，不作为落地依据。

用 LLM 扮演"另一个标注者"，跑不同视角的标注，跟人类标注做一致性比对 + 仲裁。本质是把第二意见外包给模型，比单次人工标注强，但比真人双标注弱。

**关键设计**：

1. **视角必须真正对立，否则降级为"LLM 跟自己达成一致"**，分歧检测失灵。两个标注视角用对立偏向的 prompt：
   - **视角 A「最小路由」**：能用单一子 Agent 解决就别多标（偏向 under-routing）
   - **视角 B「完整信息」**：只要某子 Agent 能补充有效信息就标上（偏向 over-routing）
   - 两个偏向天然对立，分歧才有信号
2. **人类标注是"锚"**：你(人) vs LLM-A vs LLM-B 三方，多数投票不一致时由你最终拍板。不让 LLM 两视图把你盖过去。
3. **一致性度量必须报**：标注后报三个 pairwise Jaccard（你 vs A、你 vs B、A vs B）的均值与分布。
   - 一致性低（如 <0.6）→ 题目本身歧义大，ground truth 不可靠，**剔除或重写该题**
   - 一致性高 → 标注稳定，可入 golden
4. **来源留档**：每条 ground truth 在 `rationale` 字段标注 `source`（`human` / `llm-minimal` / `llm-complete` / `arbitrated`），确保可追溯。

**golden schema `rationale` 字段扩展示意**：

```jsonc
"rationale": {
  "source": "arbitrated",        // human / llm-minimal / llm-complete / arbitrated
  "human": ["行业动态搜索", "业务数据查询"],
  "llm_minimal": ["行业动态搜索"],
  "llm_complete": ["行业动态搜索", "业务数据查询", "知识库检索"],
  "pairwise_jaccard": 0.83,
  "note": "A/B 在是否需知识库上分歧，仲裁采纳 human"
}
```

**诚实边界声明新增**：
> ground truth 含 LLM-as-annotator 成分（非纯人工标注）；一致性 <0.6 的题目已剔除。该指标衡量的是"标注稳定性"，不等于"标注正确性"。

**指标口径（沿用缺口 3 原方案）**：报告同时报"严格匹配率"（必须完全一致）和"宽松匹配率"（Jaccard ≥ 0.5 即算对）。

---

### 缺口 4：会展 query 来料的实际可行性（§3）

**问题**："人工产出，或从 zhiku 语料反推"——zhiku 目前只有 50 条烫金机数据，与会展领域无关。

**代码实况**：
- `zhanggui-zhiku/eval/golden_queries.jsonl` 全部是烫金机/万用表/电磁炉（家电领域）
- 会展领域语料尚未导入 zhiku（Issue #120 决策记录要求导入，但未执行）

**影响**：如果会展语料未就绪，评测跑的 query 无法验证知识库子 Agent 的实际能力，只能测路由决策（不验证检索质量）。

**建议方案**：
1. **短期**：先用"纯路由决策"类 query（不依赖知识库内容，只测"该调哪个子 Agent"）
2. **中期**：等会展语料导入 zhiku 后，再补充需要知识库检索的 query
3. 在 `eval/README.md` 诚实边界声明："当前评测聚焦路由决策质量，知识库检索质量依赖 zhiku 侧语料就绪"

---

## 四、逻辑依赖断裂

### 断裂 1：§8"前三步可并行"的依赖关系

**问题**：schema（第 1 步）需要定义 `acceptance_points`，这依赖对输出格式的预判；runner（第 2 步）需要 schema 定义才能解析 golden。

**实际依赖链**：
```
schema 定 acceptance_points 类型 → runner 才能解析 golden → judge 才能打分
```

**建议方案**：调整落地顺序为串行：
1. 先固化 schema（含 acceptance_points 类型定义和判定规则）
2. 再写 runner（依赖 schema 解析）
3. 再写 judge（依赖 runner 输出格式）

或把 schema 和 runner 骨架并行（schema 只定字段名和类型，不填具体值），但 judge 必须等 runner 输出格式确定后才能写。

---

### 断裂 2：pass^k 在提案中的位置模糊

**问题**：§2.3 引用了 tau-bench 的 pass^k 作为"参照叙事"，但 §8 落地顺序中完全没有提到 pass^k。

**影响**：读者不知道 pass^k 是"已经决定要做"还是"仅供参考"。

**建议方案**：在 §8 落地顺序中明确：
- 第 5 步（或新增一步）："pass^k 一致性压测（k=5），在基础指标稳定后执行"
- 或在 §2.3 开头加标注："pass^k 为可选增强指标，非首轮必做"

---

## 五、已定的修正方案（全部按推荐收口）

### 5.1 对 PROPOSAL.md 的修订清单

| 章节 | 修订内容（已定） |
|------|----------|
| §2.1 | 增加 `rationale`（含 `source` 子字段）到 golden schema；ground truth 改为**单人人工标注**（原 LLM 对立双视角+三方仲裁已砍，见 §八）；报"严格匹配率"+"宽松匹配率（Jaccard≥0.5）"双口径 |
| §2.3 | pass^k 明确为可选增强指标（非首轮必做）；**简化 acceptance_points 类型——去掉 numeric，只留 entity/conclusion** |
| §3 | golden schema 增加 `rationale`；诚实边界声明"当前评测聚焦路由决策，知识库检索质量依赖 zhiku 语料就绪"；去掉 schema 示例里的 numeric 验收点 |
| §4 | 修正伪代码：`monitor.on()` → 需给 ToolMonitor 加订阅方法；工具四分类改用**结构化 `report_tool_outcome` 事件**（不解析字符串），发射点 B+C 混合 |
| §6 | 映射表第 1 行改为"需给 ToolMonitor 加 on/off 方法"；第 2 行起工具四分类改为"需工具侧发结构化 outcome 事件（非字符串匹配）" |
| §8 | 调整落地顺序为**串行** schema→runner→judge；pass^k 为第 5 步可选；首轮规模 5 题 × 1 轮（不跑 pass^k） |

### 5.2 首轮最小可行集（MVP）

| 项 | 范围 | 工作量 |
|-----|------|--------|
| ToolMonitor 加订阅 | `api/monitor.py` +15 行 | 低 |
| golden 首批 5 题 | 纯路由决策类（不依赖知识库内容） | 低 |
| runner MVP | 调 `run_deep_agent` + 收集路由 + 精确匹配打分 | 中（~100 行） |
| 人工标定 | 5 题输出人工判 pass/fail | 低 |

**首轮不做的**：pass^k、LLM-as-judge、工具四分类自动判定、覆盖矩阵全格。

### 5.3 成本基线

首轮 5 题 × 1 轮 ≈ 5 次 agent run ≈ 预计 2-5 分钟（串行）/ 30 秒（并发，需验证 RPM 限制）。

---

## 六、落地前置决策（非 PROPOSAL.md 硬伤，落地前需先定）

以下不属提案文本缺陷，但落地时会卡住，先定方案。

### 前置 1：eval/ 是否独立 `.env`，还是复用项目根 LLM 配置

**问题**：runner / judge / LLM-as-annotator 都要 LLM API key。当前 deepagents 根目录有 `.env.example`（被 `.gitignore` 忽略真实 `.env`），无独立 eval 配置。三个 LLM 消费方诉求不同：
- runner 驱动 `run_deep_agent` → 用项目主模型配置
- judge（若启用）→ 需**不同 provider** 去偏（缺口/§2.3 已定）
- LLM-as-annotator → 独立调用，不影响被评测的 agent

直接复用根 `.env` 会让"judge 用不同 supplier"这条无法落地（根 `.env` 只有 qwen 一套）。

**已定方案**：
- **不新建独立 `.env`**，复用根 `.env` 拿主模型配置（runner 用）。
- judge / annotator 的"不同 provider"通过**环境变量覆盖**实现：`EVAL_JUDGE_API_KEY` / `EVAL_JUDGE_BASE_URL` / `EVAL_JUDGE_MODEL`（annotator 同理 `EVAL_ANNOTATOR_*`）。缺省时 judge/annotator 退化为同主模型并告警（不阻断，但诚实边界声明"本轮 judge 未去偏"）。
- `.env.example` 补占位行，明确哪些 key 是评测专用、缺省降级行为。

**理由**：避免多 `.env` 文件散落与加载顺序歧义；用显式环境变量名隔离评测 LLM，符合 §2.3 去偏诉求又不强制依赖外部 provider。

### 前置 2：评测批量跑会不会污染工作目录 `output/`

**问题**：`run_deep_agent` 每次调用会 `output/session_{session_id}/` 建目录、写生成文件（[`main_agent.py:69-72`](deepagents/agent/main_agent.py#L69)）。评测批量跑 5+ 题会生成一堆 `session_xxx/` 目录混进正常工作区，且 `output/` 已被 `.gitignore` 忽略——评测产物与真实会话产物无法区分。

**已定方案**：
- runner 用**专用的 `session_id` 前缀** `eval_<timestamp>_<tid>`（如 `eval_20260809180000_expo-001`），与线上会话 `session_{uuid}` 区分。
- 评测跑完统一清理由评测前缀产生的 `output/session_eval_*` 目录（runner 加 `--cleanup` 旗标，默认清理）。
- 评测结果（路由/judge/rubric）不放 `output/`，放 `eval/results/<timestamp>/`（提案 §4/§5 已规定，此处确认路径与 `output/` 隔离）。

**理由**：前缀隔离比"评测跑完整体清空 output"安全——不会误删真实会话产物；`--cleanup` 默认开避免残留堆积。

---

## 七、与 Issue #120 的关系

本审核报告应作为 Issue #120 的新评论追加，与 PROPOSAL.md 形成"提案 → 审核 → 修正 → 落地"的闭环。

---

## 八、二次审核补录（漏审 3 处 + 过度设计判定 + 主流性联网验证）

> 补录日期：2026-08-09
> 补录方式：代码实况二次核对 + 联网验证主流方案（τ-bench / AgentBench / LLM-as-judge 论文）

### 偏差 4（阻断级）：`run_deep_agent` 不返回值，runner 拿不到 answer

**问题**：PROPOSAL §4 伪代码 `result = await run_deep_agent(...)` 假设函数有返回值。

**代码实况**（[`main_agent.py:65-133`](deepagents/agent/main_agent.py)）：
- `run_deep_agent` 函数**无任何 `return` 语句**（grep `return` 仅命中 `:38`/`:41`/`:59`，均在其他函数内）
- 内部 `async for chunk in main_agent.astream(...)` 消费流，最终答案通过 `monitor.report_task_result(last_msg.content)`（`:128`）发射
- 函数返回 `None`

**影响**：`result = None`，`"answer": result` 为 None，rubric judge 拿不到答案——**任务完成率整层指标失效**。严重度超过偏差 1/2/3，是阻断级。

**已定方案**：runner 订阅 `task_result` 事件拿答案（与偏差 1 的 `on/off` 修正同源，零额外成本）：
```python
monitor.on("task_result", lambda e: answer.append(e))
await run_deep_agent(...)   # 不依赖返回值
answer_text = answer[-1]["data"]["result"] if answer else None
```

### 偏差 5：`.gitignore` 未配置 `eval/results/`

**问题**：PROPOSAL §5 声称"`.gitignore` 忽略 `eval/results/`"。

**代码实况**（[`deepagents/.gitignore`](deepagents/.gitignore)）：18 行，仅有 `.env` / `__pycache__/` / `output/` / `updated/` / `tools/test_session_*/` / `.idea/` / `venv/`，**无 `eval/results/`**。

**影响**：按原 PROPOSAL 落地，评测结果 JSONL 会误入仓库，违反"结果不进仓库"设计意图。

**已定方案**：`.gitignore` 追加 `eval/results/` 一行。

### 缺口 5：并发评测时 `ToolMonitor` 单例事件串题

**代码实况**（[`monitor.py:31`](deepagents/api/monitor.py)）：`ToolMonitor` 是单例（`__new__`），`on("assistant_call", callback)` 注册的 callback 全局共享。

**场景**：并发跑 expo-001 + expo-002，两个 runner 的 collector 都会收到对方事件——expo-001 的 `routed_agents` 混入 expo-002 的路由。

**影响**：MVP 串行不触发；§8 第 7 步"扩 golden"和 pass^k 并发时出错。

**已定方案**：首轮强制串行（`Semaphore(1)`）；扩量并发时 callback 内按 session_id 过滤（事件 data 需带 session_id）。

### 过度设计判定（已砍，见 PROPOSAL §9）

经联网验证主流方案后，判定以下设计为过度设计并砍掉：

| 砍掉项 | 判定依据 |
|--------|----------|
| LLM-as-annotator 对立双视角 + 三方仲裁 | 无学术背书（联网确认 AgentBench/τ-bench 无此范式）；单人项目 5-15 题人工标即够；面试 30 秒讲不清 |
| 覆盖矩阵全格 63 题 | 子项目投入产出比低 |
| pass^k 实跑 | 首轮成本失控；τ-bench 引用即够面试叙事 |
| numeric acceptance_points | 模糊数值判定不可靠 |

### 主流性联网验证结论

| PROPOSAL 设计 | 主流？ | 证据 |
|---------------|--------|------|
| pass^k | ✅ | τ-bench（1.4k★）核心指标，已迭代到 τ³-bench |
| LLM-as-judge 不同 provider 去偏 | ✅ | Zheng et al. NeurIPS'23，明确提 self-enhancement bias |
| rubric-based judge | ✅ | MT-Bench / AlpacaEval 同思路 |
| 多标签路由准确率 | ⚠️ 无先例 | AgentBench（3.7k★）/ τ-bench 均单 agent，真创新也是真风险 |
| 工具四分类 | ⚠️ 部分主流 | τ-bench `auto_error_identification` 分 4 类，但维度为任务级，PROPOSAL 为工具级 SLO |
| LLM-as-annotator 对立双视角 | ❌ 非主流 | 无公认范式 |

### 补录后修正方案更新

§5.1 修订清单追加：

| 章节 | 修订内容 |
|------|----------|
| §4 | 伪代码加 `monitor.on("task_result", ...)` 拿答案；`run_deep_agent` 返回值不依赖 |
| §5 | 明确"需在 .gitignore 追加 eval/results/（当前未配）" |
| §4 | 加"并发隔离：首轮强制串行 Semaphore(1)" |
| §9（新增） | 已砍项透明声明 |

§5.2 MVP 追加：runner 订阅 `task_result` 事件（偏差 4 修正，与偏差 1 同源）。

---

### 三次审核补录（独立 agent 验证，2026-08-09）

> 两个独立 agent 按"独立审核提示词"执行，本节记录经原审核者逐条验证后确认成立的新发现。前三次审核（含本报告 §一~§八）均漏审。

**漏审 6（阻断级）：golden 标签与事件 assistant_name 恒不相等 → 路由指标静默全 0**

- **代码实况链**：`prompts.yml:41/54/68` subagent name 带"助手"后缀（"行业动态搜索助手"等）→ `subagents/*.py` 透传 → `main_agent.py:121` `subagent_type = tool_call['args']['subagent_type']` = subagent["name"] → `:123` `monitor.report_assistant(subagent_type, ...)` → 事件 `assistant_name` = "行业动态搜索助手"
- **PROPOSAL §3** golden `expected_agents: ["行业动态搜索"]`（无后缀）→ `pred_set != gold_set` 永真，`exact=False`，`jaccard=0`
- **影响**：不报错，首轮 5-15 题路由准确率全 0%，且看不出 bug
- **已定方案**：golden 直接用 subagent 全名（"行业动态搜索助手"等），PROPOSAL §3/§6 已修正

**漏审 7（高）：护栏拦截逃逸到 _timeout.py，工具四分类误判**

- **代码实况**：`_validate_sql_select_only` 抛 `ValueError` → `db_tools.py:192` `except Error`（mysql.connector.Error）不捕获 → 逃逸到 `_timeout.py:41` `except Exception`
- **影响**：按 §2.2 B 方案在装饰器发事件，护栏违规被判为 `exception`（系统 bug），正好与 §2.2 设计目标矛盾
- **已定方案**：`_timeout.py` 按 `error_class` 区分（`ValueError`→guarded）；`db_tools.py` `except Error` 分支补发 `exception`。PROPOSAL §2.2/§6 已修正

**漏审 8（中）：report_tool_outcome 方法不在 §6 映射表**

- **代码实况**：`monitor.py:81-96` 无 `report_tool_outcome` 方法
- **影响**：§2.2 定义了调用签名，但 §6 映射表漏列"需在 monitor.py 新增"前置动作
- **已定方案**：§6 补"需在 monitor.py 新增 report_tool_outcome（~10 行）"，§8 步骤 0 纳入

**漏审 9（中）：task_result 事件覆盖不完备**

- **代码实况**：`main_agent.py:127` `elif last_msg.content` → 仅当 `node_name=='model'` 且无 tool_calls 且有 content 才发射
- **影响**：run 终止于 tool_calls（recursion limit/异常）时 answer=None；多次文本轮时 `answer[-1]` 可能拿错
- **已定方案**：runner 处理 answer=None 判 incomplete（PROPOSAL §4/§6 已修正）

**漏审 10（低-中）：成本估算模型错位**

- **代码实况**：`llm.py:15` 主模型默认 `qwen-max`（DashScope 按 token 计费），非 AUDIT 缺口 1:124 所写"Qwen3.5-4B ~0.5s"
- **已定方案**：PROPOSAL §4 成本控制改为 qwen-max token 计费

**漏审 11（低）：pass^k k 值不一致**

- §8 写 k=5，§9 写 k=8 → 已统一为 k=3 起步

**假阳性（独立 agent 报但经验证不成立）**：

| 报告项 | 来源 | 不成立理由 |
|--------|------|------------|
| score_routing 除零 | Agent 2 ⑧ | expected_agents 允许 1~3 个，gold_set 不会空，pred\|gold 不会空集 |
| 多标签路由 2026 有先例 arXiv:2606.28925 | Agent 2 主流性 | arxiv 编号 28925 超单月编号范围（通常<15000），疑似幻觉；方向可能对但证据不可信 |

**修正后 AUDIT 总计**：5 偏差 + 5 缺口 + 2 断裂 + 6 漏审 = **18 处问题**，其中阻断级 2 处（偏差 4 + 漏审 6）。

---

*审核完成（含三次补录）。PROPOSAL.md 已按本报告 §5.1 + §八 + 三次审核补录回改为 v1.1。*

---

## 九、落地记录（2026-08-09）

PROPOSAL §8 步骤 0-3+6 已落地，代码侧评测框架完整。

### 已落地文件

| 文件 | 动作 | 内容 |
|------|------|------|
| `.gitignore` | 改 | 追加 `eval/results/` |
| `api/monitor.py` | 改 | 新增 `on/off` 订阅机制 + `report_tool_outcome` 方法 + `_callbacks` 初始化 + `_emit` 末尾 callback 调用 |
| `tools/_timeout.py` | 改 | 装饰器按 error_class 区分发事件：TimeoutError→timeout，ValueError→guarded，其余→exception |
| `tools/zhiku_tools.py` | 改 | 6 处补发：降级+429→degraded，空结果→empty，httpx超时→timeout，HTTP/其他异常→exception |
| `tools/db_tools.py` | 改 | 7 处补发：表名白名单拒绝→guarded，空表/空结果→empty，except Error→exception |
| `eval/golden.jsonl` | 新建 | 10 题（3 单路由 + 3 双路由 + 2 三路由 + 2 中等单路由） |
| `eval/run-eval.py` | 新建 | runner：订阅 assistant_call/task_result/tool_outcome 事件 + 路由集合匹配 + rubric 集成 + 工具四分类统计 + finally off + 串行 + cleanup |
| `eval/judge.py` | 新建 | rubric 逐项打分：entity 字符串包含 + conclusion LLM 语义判断；judge 用不同 provider（EVAL_JUDGE_* 环境变量，缺省降级同主模型并告警） |

### 设计决策

- **`_timeout.py` 正常返回不发 success 事件**：避免与工具函数内部 catch 分支的 double event。工具函数内部 catch 自己发事件，异常逃逸到装饰器的由装饰器发。runner 按 outcome 分类计数，未收到事件的工具调用算 success。
- **ValueError → guarded 分类**：`_validate_sql_select_only` / `_validate_identifier` 抛 ValueError 逃逸到装饰器，归为护栏拦截。`get_table_data` 表名白名单拒绝是正常 return，单独发 guarded。
- **golden expected_agents 用全名**：与 `prompts.yml` subagent name 完全一致（带"助手"后缀），避免标签不匹配导致路由准确率静默全 0。

### 验证

- 语法检查：5 个改动文件 `py_compile` 全通过
- `run-eval.py --help`：正常输出，lazy import 不触发完整依赖链
- `score_entity` 纯函数：4 个 case 全通过
- golden JSONL：10 行均为合法 JSON

### 待做

| 步骤 | 内容 | 阻塞条件 |
|------|------|----------|
| 4-5 | 实跑评测 + 人工标定 judge 分数 | 需 `.env`（OPENAI_API_KEY/BASE_URL）+ `pip install tavily` + 可选 EVAL_JUDGE_* |
| 7 | 扩 golden 到覆盖矩阵更多格 | 后置，当前 10 题够面试讲点 |
| 8 | pass^k 一致性压测（k=3） | 后置，基础指标稳定后 |

---

## 十、真实 R1 基线阻塞记录（2026-08-19）

> 状态：**BLOCKED**（等待用户拍板，非代码未提交）
> 定位：评测框架（PROPOSAL §8 步骤 0-3+6）代码侧已完整，但端到端真实 agent 路径跑不通，无法产出真实 R1 基线数据。

### 10.1 现象

- 真实基线 runner 通过本地 `opencode-gateway`（`:8799`）走真实 LLM 通道，路由/工具/任务三类指标**全 0**。
- 子进程以 `rc=1` 崩溃（非超时、非限流），说明真实 agent 路径在 gateway 侧直接失败，而非评测指标逻辑问题。

### 10.2 根因

`scripts/opencode_gateway.py` 是 opencode 网关的**极简转发层**，存在两处能力缺口，导致真实 agent 路径无法跑通：

1. **不支持 tool-calling / function calling**
   - 真实 agent 绑定 `task` 工具（委派子 Agent 的核心工具），请求体中必须携带 `tools=[{type:function, function:{...}}]`。
   - gateway 当前转发链未处理 `tools` 字段，且未把模型返回的 `tool_calls` 解析回 opencode 协议 → `task` 工具根本不生效，路由无从发生。
2. **不支持长 system prompt**
   - 真实 agent 的 system prompt 为长文本（含角色定义 + 子 Agent 描述 + 委派规则）。
   - gateway 对 system prompt 的处理在长文本下异常，子进程崩溃（`rc=1`）。

> 注：run_eval.py 的通道判定已修复（commit 79ff66e，双通道：`LLM_BASE_URL`+`LLM_API_KEY` 走 gateway，或 `OPENAI_API_KEY` 直连），但**通道放行 ≠ 通道可用**——gateway 能力缺口仍阻断真实路径。

### 10.3 待决策项（请用户拍板二选一）

| 方案 | 内容 | 工作量 | 风险 |
|------|------|--------|------|
| **方案 A：扩展 gateway 支持 tools** | 在 `opencode_gateway.py` 转发 `tools` 字段 + 解析 `tool_calls` 回填 opencode 协议 | 中（需理解 opencode 协议双向结构） | gateway 维护成本上升 |
| **方案 B：换兼容端点** | 直接配置支持 tool-calling 的真实 `OPENAI_BASE_URL`（绕过 gateway），真实 R1 基线走直连通道 | 低（仅配置） | 失去 gateway 统一层，但评测场景可接受 |

### 10.4 当前环境残留（用户处理前）

- 后台仍运行：`opencode-gateway`（`:8799`）+ `pgvector`（`:5433`）。
- 若用户选择方案 B，需确认目标端点的 tool-calling 可用性（当前 `.env` 的 gateway 端点不满足）。
