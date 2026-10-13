# 方案（待拍板）：确定性路由的关键词闸门让已入库语料对自然提问不可见

日期：2026-10-12　状态：**待拍板，未改代码**
关联：`plan-intent-embedder-bypasses-provider-2026-10-10.md`（同一族的另一半）、手册 §4 底线 4/5、§5 基线 2

## 1. 现象（今天实跑出来的，不是读代码推的）

93 块语料已入库、检索层自己能查到（cosine top-5 相似度 0.54–0.57，正确文档排第一），
但同一句话换个问法就走不通：

| 提问 | 路由结果 | evidence |
|---|---|---|
| "**为什么**没有配置单租户声明时服务会拒绝启动？" | `direct`（reason: 无明确能力特征） | **count 0** —— 没人去问检索器 |
| "**根据文档**，服务在什么情况下会拒绝启动？" | `rag`（reason: 命中知识库特征词） | count 4，答案逐条引 ADR 章节 |

机制在 `applications/agent_server/agent/router.py:63-76`：`heuristic_route` 是**纯关键词包含**判断，
`rag` 的特征词表（`data/route_hints.json`，缺失时用 `_FALLBACK_HINTS`）= 知识库/文档/什么是/解释/原理/
怎么理解/wiki/笔记/介绍。表里没有"**为什么**""怎么办/为什么会这样"这类**因果问法**——
而因果问法恰恰是知识库问答最自然的说法。

## 2. 为什么这条必须单独记，而不是并进"意图路由旁路"

旁路那条讲的是"**语义 embedding 没被统一提供方管**"；这条讲的是"**要不要去检索由关键词决定**"。
两者叠加后的现场后果：

- 演示当天听众问"为什么 X"，页面显示依据为空 ⇒ 看起来像"知识库没生效"，实际是路由没开门；
- `direct` 路径仍会调模型，模型在**无依据**时如实回答"证据不足"（今天验过，没编答案），
  但**有答案也等于没查到** —— 这个失败是静默的，`/health` 上没有任何灯承载它。

## 3. 选项

| 选项 | 做法 | 代价 | 判定 |
|---|---|---|---|
| A | 只要启用了知识库（`chunks` 非空）就**默认先检索**，把 rag 从"命中关键词才走"改成"兜底也走"，`direct` 只留给闲聊/无库场景 | 改路由优先级，可能给无关问题多一次检索开销 | 行为改动最小、演示最稳；**但属改代码，须拍板** |
| B | 给路由加**语义兜底**：关键词没命中时用意图分类（走统一 `get_embedder()`）判 rag/direct | 依赖旁路那条先修好，否则语义层不可信 | 与旁路方案天然是一个包，建议一起拍 |
| C | 不改代码，**演示话术约束**：主持人只用带特征词的问法，并在手册里把这条写成已知限制 | 零风险零成本，但把缺陷藏进话术 | 本版临场可用，**不得**当长期方案 |

## 4. 验收（选 A/B 时必须过）

1. "为什么没有配置单租户声明时服务会拒绝启动？" ⇒ `capability=rag`、`evidence.count>0`、依据栏出现 ADR-0007 章节名；
2. 纯闲聊（"你好"）⇒ 仍 `direct`，**不得**为它付一次检索开销；
3. 空库时 ⇒ `evidence.count=0` 且回答如实说没有依据（不许因为"默认先检索"就编）；
4. 一条用例钉住"因果问法能命中 rag"，防止特征词表以后被修剪回缺陷态。

## 5. 我的建议

**A + 手册同时改**：A 的改动集中在一个函数、可由上面 4 条用例覆盖；C 只是话术，救得了当天救不了下次。
B 等旁路那条落地再说。

## 6. 待拍板

① 选 A / B / C；② 若选 A，`direct` 的边界怎么定（纯闲聊白名单？还是"库为空才 direct"）。

## 7. 2026-10-13 追加：闸门不是"兜底路径"，它就是主路径（现场证据，方案前提被推翻）

本方案 §1 的前提是"LLM 路由为主路径，词表只在模型不可用时兜底"——这条来自 `route_hints.json` 的注释。
126 现场把它推翻了：**LLM 结构化路由 100% 失败，每一次问答都走词表**。

上游返回（`router.py:87` 的 `with_structured_output(RouteDecision)`）：

```
<400> InternalError.Algo.InvalidParameter: This response_format type is unavailable now
```

| 读数 | 值 |
|---|---|
| 我今天发起的 `/query` | 16 次 |
| 其中留下"回退启发式路由" WARNING | **16 次（全部）** |
| 因果核对 | 单发一问（带唯一标记防缓存）⇒ 告警计数 16→17，**增量恰为 1** |
| 全仓在跑的结构化调用点 | 仅 `router.py:87` 一处；`graph_compose.py:153-156` 有真降级且 `planner=deterministic` 未启用 |
| `/health` 的 `llm` | 仍为 `true`（探的是普通补全）⇒ **它不构成"路由可用"的证据** |

对方案本身的影响（三点，都要改口径）：

1. **A/B/C 三个选项的评估基准变了**。原先担心"A（库非空默认先检索）会让无关问题多付一次检索开销"，
   现在知道每问还额外付了一次**必然失败的结构化往返**（Q1 墙钟 11.14s 含它）。
   ⇒ 修 router 顺带把这次失败往返省掉，A 的相对代价比原先估的更小。
2. **闸门的可复现性从"一次观察"变成"3/3 稳定复现"**：业务语料消融那一轮，我误用了一个不含特征词的问法，
   结果消融前/后/还原后三次全部 `route=direct`、`evidence count=0`（`evidence/2026-10-13-business-corpus/readings.md` §6）。
   同一问法加上"根据文档"四字即 `route=rag`、`count=4`。
3. **新增一条独立待拍板项（原方案没覆盖）**：结构化输出与当前模型提供方的能力不匹配，怎么处理——
   - **R1** 换用法：`json_object` + 把 schema 写进 prompt + 自己解析（多数兼容 OpenAI 协议的国内提供方可用）；
   - **R2** 认能力：启动时探一次结构化能力，探不过就把 LLM 路由**显式关掉**（`planner`/`/health` 出一盏 `structured_output=false`），
     让词表成为**声明出来的**主路由而不是"悄悄生效的兜底"；
   - **R3** 不动代码：只把 `route_hints.json` 与文档里"LLM 为主路径"那句改成现状。
   
   我的建议：**R2 + 本方案 A 一起落**。理由是 R1 的收益依赖提供方行为、需要现场再验一轮，而 R2 先把
   "看起来有 LLM 路由、实际没有"这个认知陷阱关掉；A 决定的是关掉之后检索还开不开门。
   R3 是任何选择下都要做的文档修正（不做就是留着一条会让下一个人误判的假陈述）。

## 8. 根因已定位（2026-10-13，四路探针实跑，不是读码推的）

线上配置（值面只到"哪个端点/哪个模型"，密钥只报长度口径）：`LLM_BASE_URL=https://api-inference.modelscope.cn/v1`、
`LLM_MODEL=LLM_FALLBACK_MODEL=deepseek-ai/DeepSeek-V4.1-Flash`。对同一端点发四种形态：

| # | 请求形态 | 结果 |
|---|---|---|
| 1 | 纯补全（`/health` 的 `llm=true` 探的就是这个） | **200** |
| 2 | `response_format={"type":"json_object"}`，messages 里**不含** "json" | 400：`'messages' must contain the word 'json' in some form, to use 'response_format' of type 'json_object'` |
| 3 | `response_format={"type":"json_schema", strict:true}` | **400：`This response_format type is unavailable now`** |
| 4 | 同上但不带 strict | **400：同一句**（⇒ 与 strict 无关，是该类型整体不支持） |
| 5 | `tools` + `tool_choice:"required"` | **200**，`finish_reason=tool_calls`，且 arguments **逐字符合** `RouteDecision` schema：`{"capability":"rag","reason":"…","sub_query":"展台搭建的安全要求有哪些"}` |
| A | `json_object` + prompt 里含"以 JSON 返回" | 200，但模型自己造字段名（`{"判断结果":{"应走链路":…}}`）⇒ **不保证贴 schema**，还要自己解析 |

版本侧（Pod 内实测）：`langchain-openai==1.7.0`，其签名为

```
ChatOpenAI.with_structured_output(schema, *, method: Literal['function_calling','json_mode','json_schema'] = 'json_schema', ...)
```

**因果链闭合**：`router.py:87` 写的是 `llm.with_structured_output(RouteDecision)` ⇒ `method` 取默认 `json_schema`
⇒ ModelScope 兼容层没有实现这个 `response_format` 类型 ⇒ 每问必 400 ⇒ 被 `except Exception → heuristic_route`
吞成"正常"。而 `/health` 的 `llm` 只探纯补全（第 1 路 200）⇒ 灯一直是绿的。

## 9. 最小修法（两行，跨两个包；已验证目标形态可用，但**未拍板不动手**）

1. `applications/agent_server/agent/router.py:87`：`with_structured_output(RouteDecision, method="function_calling")`
   —— 走第 5 路，实测 200 且严格出参。
2. `packages/agent-core/agent_core/llm/fallback.py:227`：`def with_structured_output(self, schema, **kwargs)`
   并 `return self.primary.with_structured_output(schema, **kwargs)`。
   **这一处是必需的第二步**：`agent/llm.py:39` 把模型包成 `FallbackChatModel`，而它现在的签名不收 `method`，
   只改 router.py 会被这层静默丢掉（又一个"消费不存在的契约"形状）。

不选 `json_mode`：第 A 路证明它能返 200 但不保证字段贴合 schema，省不掉解析代码，收益不如 function_calling。
不选 `json_schema`：端点整体不支持（第 3/4 路）。

### 验收（改完必须过）

1. 线上单发一问 ⇒ pod 日志**不再**出现 `This response_format type is unavailable`（计数增量 0）；
2. `route.reason` 变成模型写的话（不再是"命中知识库特征词"这类固定话术），且不带特征词的因果问法能拿到 `capability=rag`；
3. `make eval` 的 15 条 golden 不掉基线（`decide_route` 是 eval 基线，`intent_bridge` 注释明确要求保持稳定）；
4. 用例钉住"`FallbackChatModel` 把 `method` 透传给 primary"——否则第 2 步会被下一个人重构掉而无人察觉。

### 顺带抓到的一条配置事实

`LLM_MODEL` 与 `LLM_FALLBACK_MODEL` **是同一个模型**（`deepseek-ai/DeepSeek-V4.1-Flash`），且
`FallbackChatModel.with_structured_output` 恒绑 primary ⇒ 当前"主备"在结构化路径上等于**没有备**。
端点整体不可用时（10-12 已实测过那种形态）路由会全部落到词表，这没问题；但**没有任何一个模型能替另一个**这件事要写进运维口径，
别把 `LLM_FALLBACK_MODEL` 当成"配了备用模型"。

## 10. 两个提供方对照（2026-10-13，需求方要求实测硅基流动后补）

先回答"是不是魔搭不兼容"：**是端点能力面的问题，不是模型选错**。魔搭 API-Inference 官方文档承诺的调用面是
Chat Completions、Responses API（**且明说"只支持 Qwen3.5 系列模型"**）、Anthropic 兼容（beta）——
**通篇没有 `response_format` 结构化输出这一项**。我们收到的 `<400> InternalError.Algo.InvalidParameter` 前缀
与 `chatcmpl-*` 响应 id 是 DashScope 系兼容层的签名，那句 `This response_format type is unavailable now`
就是该层对"没实现的 response_format 类型"的固定回绝。⇒ 换 `deepseek-ai/…` 为别的魔搭模型不会改变结论。

对**同一套五种形态**打了第二个提供方（硅基流动 `https://api.siliconflow.cn/v1`，从 Pod 内直连可达，
DNS 47.117.173.229 / TCP443 通），并把判据从"HTTP 200"收紧成"**能否解析成 `RouteDecision`**"
（三必填字段齐 + `capability` 在枚举内）：

| 提供方 / 模型 | 纯补全 | `json_schema`+strict | `json_object` | `tools`+`tool_choice=required` |
|---|---|---|---|---|
| 魔搭 `deepseek-ai/DeepSeek-V4.1-Flash`（现网在用） | 200 | **400，稳定拒绝**（带/不带 strict 都一样） | 400 要求 prompt 含 json；含了能用但不贴 schema | **200，5/5 合规**，2.2–3.7s，`capability=rag`（判断也对） |
| 硅基流动 `Qwen/Qwen3-8B`（免费小模型） | 200 | 200 **但 5 次里 3 次 75s 读超时**，成功那 2 次字段合规、判断却错（`code_execution`/`search`） | 200 但**缺全部三个字段**（合规=False），耗时 56.6s | **200，5/5 合规**，8.6–14.4s，但 5/5 判成 `search`——"根据文档"的问题被判去联网 |

三条要一起读的结论：

1. **两个提供方的最大公约数是 `tools`/function_calling**，而不是 `json_schema`。⇒ 这直接否掉了"换提供方就不改代码"这条路：
   换到硅基流动照样要动 `router.py`（它现在传的是默认 `json_schema`），换了也白换。
2. **R1（`method="function_calling"`）的证据强度因此更高**：现网这把魔搭 key 上 5/5 合规、2–4s、判断正确。
3. **演示期不要把 LLM 切到硅基流动**：小模型延迟 8.6–14.4s（魔搭 2.2–3.7s）、`json_schema` 有 60% 超时率，
   而且路由质量更差。这和本仓库既有的教训一致（`knowledge-service` 早把"SiliconFlow API 偶发无响应挂起、
   排队导致 P95 243s"记进 benchmark 与 eval harness 的 `--llm-timeout`）。
   硅基流动在本项目的既定角色是 **embedding/rerank 的可选提供方**（`SILICONFLOW_API_KEY`），不是 LLM 主链路。

### 由此定的建议（等拍板）

**R1 落两行**（`router.py:87` 传 `method="function_calling"` + `fallback.py:227` 透传 `**kwargs`），
提供方**继续用魔搭**；R2 作为第二步（启动期探一次结构化能力并出灯），避免下次换提供方再静默一次。
不换提供方、不引入新密钥、`SILICONFLOW_API_KEY` 保持在它原有的 embedding/rerank 位置上。

## 11. 第三家对照：OpenRouter（2026-10-13，需求方提供 key 后实测）

同一套判据（**能否解析成 `RouteDecision`**，不是"HTTP 200"），打 `https://openrouter.ai/api/v1`（Pod 内可达，
DNS 104.18.3.115 / TCP443 通；共 459 个模型，其中 `:free` 15 个，**无免费 deepseek**）。

失败按三类分开记，混在一起就会把"配额问题"误读成"能力问题"：

| 模型 | `json_schema`+strict | `tools`+`tool_choice=required` |
|---|---|---|
| `nvidia/nemotron-3.5-lightning:free` | **2/2 合规**（9.4s、12.8s）判成 `code_execution`/`mcp` | **2/2 合规**（2.3–2.9s）判成 `search` |
| `liquid/lfm-2.5-2.6b:free` | **2/2 合规**（11.1–17.7s）判成 `search` | **2/2 合规**（4.1–4.2s）判成 **`rag`（判对）** |
| `apodex/apodex-1.1-mini:free` | **400**（该模型侧 `INVALID_REQUEST`） | **2/2 合规**（2.2–2.5s） |
| `google/gemma-4-26b-a4b-it:free` | 8/8 全失败：`Provider returned error … "API key not valid"` ⇒ **OpenRouter 自己的上游 Google 凭据失效**，与我们的代码无关 | 同左 |
| `poolside/laguna-xs-2.1:free` | 6/8 `429 temporarily rate-limited upstream` | 唯一没被限流的那次 200 且合规（2.4s） |

### 三家合起来看（这是本轮真正的结论）

| 提供方 | `json_schema` | `tools` / function_calling |
|---|---|---|
| 魔搭 API-Inference（现网） | **端点整体不支持**，稳定 400 | **5/5 合规，2.2–3.7s，判对 `rag`** |
| 硅基流动 | 名义支持，**5 次里 3 次 75s 超时** | 5/5 合规，8.6–14.4s，判成 `search` |
| OpenRouter | **按模型**：两个 2/2 合规、一个 400、两个免费池被上游凭据/限流打死 | **3/3 可用模型全部 2/2 合规**，2.2–4.2s |

⇒ **`tools` 是三家唯一全绿的形态（本轮 11/11 次模型-提供方组合都合规），`json_schema` 三家行为各不相同。**
⇒ R1（`method="function_calling"`）因此不只是"修当前这个 bug"，它同时让路由层**跨提供方可移植**：
   以后换魔搭/硅基流动/OpenRouter 任何一个，都不需要再动 `router.py`。
⇒ 但**演示期仍不换提供方**：OpenRouter 免费池的可用性不由我们控制（`gemma:free` 8/8 死于它自己的上游 Google key，
   `poolside` 6/8 限流），而现网魔搭的 tools 路线实测 5/5、2–4s、判断正确。
   若将来要出公网演示，OpenRouter 的 **付费** 路由（非 `:free`）比免费池合适，`liquid/lfm-2.5-2.6b` 这类小模型
   做路由这种"三分类"任务已经够（tools 路径 4s 内、判对 `rag`）。

### 一个附带的产品观察（不改本轮结论）

同一个问题、同一个 schema，三家的小模型判成 `search` 的偏多（硅基流动 5/5 search、OpenRouter 两个模型 search、
魔搭判 `rag`），说明**路由质量本身依赖模型能力，不依赖 `response_format` 形态**。⇒ 落在本方案 §4 的验收第 4 条：
"因果问法能命中 rag"要有用例钉住，而不是改了 method 就默认路由变准。
