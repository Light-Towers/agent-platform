# 成本与效果的可实测基线：上下文压缩 / 语义缓存 / 模型退路

- 日期：2026-10-20
- 来源：简历侧「以 token 阈值触发压缩、摘要与模型降级」「以向量相似度阈值命中语义缓存、压缩响应时延与 token 开销」两句长期无数；外部同岗简历普遍以「节省 API 成本 N%」收尾，属可复制结构
- 类型：测量方案 + 可测性判定（新增实现仅限定价折算，不改运行时行为）
- 状态：**待拍板**——§2 表第 2 行涉及纸面表述是否需要改，需用户裁决

## 1. 取证结论（2026-10-20 只读审计，路径与行号可复跑）

| 取证项 | 结果 |
|---|---|
| token 计数是否已落库、可直接 SQL 聚合 | ✅ 是。提取点 `packages/agent-core/agent_core/llm/fallback.py:62-88`（`usage_metadata` 与 `response_metadata.usage/token_usage` 两路兼容）；累计 `.../trajectory/models.py:61 total_tokens`；落库列 `packages/agent-runtime/agent_runtime/migrations/001_baseline.up.sql:180-181` → `trajectories(total_tokens INTEGER, total_cost DOUBLE PRECISION)` |
| 钱（成本）是否已算 | ❌ 否。`fallback.py:51` 自注「cost 在本层无定价信息，恒为 0.0」；`applications/agent_server/planners/deterministic.py:252`「内核无模型定价表，`cost_used` 恒为 0」；定价表普查 `rg -ni "pricing\|price_per\|COST_PER\|单价" --include=*.py packages applications` 命中 **1** 处，且是 `applications/agent_federation/evaluation/expand-golden.py:84` 的业务指标词「客单价」，非定价 |
| 「token 阈值触发**模型降级**」是否有实现 | ❌ 无。`packages/agent-runtime/agent_runtime/context/compact.py:61 should_compact()` 只触发摘要；全仓无 token 阈值→模型路由。唯一模型切换是失败驱动 `llm/fallback.py:30 FallbackChatModel`（`CircuitBreaker` 开路才切，failure_threshold=3 / cooldown=60s） |
| 降级在现网配置下能否测出差异 | ❌ 不能。`.env.example:78` 自注：「LLM_FALLBACK_MODEL 若与 LLM_MODEL 同名 = 没有备（126 现状如此）；且结构化出参恒绑 primary，降级不走 fallback」。结构化路径见 `fallback.py:227-233` |
| 语义缓存阈值的语义 | ⚠️ 两套语义不同，禁止混用同一数值：`applications/agent_server/config.py:45 cache_threshold: float = 0.05  # 余弦距离阈值，小于该值视为同义命中`；另一条 `applications/agent_federation/agent/cache/config.py:23 l2_similarity_threshold`（env `CACHE_L2_THRESHOLD`）是**相似度**，且 `CACHE_ENABLED` 默认 False |
| 缓存命中时是否仍产生模型调用 | ❌ 不产生。命中即早退、图不跑（`applications/agent_server/api/query_router.py:163-179`）；`deploy/observability/langfuse_proof.py:28-31` 已把此点标为测量陷阱 |
| 现成 eval 能否测成本/时延 | ❌ 不能。`eval/run_eval.py`（122 行）读 `eval/golden.jsonl` **15 条**，判据是 `expected_capability` 字符串等值，无 token/时延指标；CI 实际阈值是 `--fail-below 0.8`（`Makefile:54`、`:57`），不是 1.0 |
| 可复用的时延/压测件 | ✅ `applications/knowledge-service/benchmark/locustfile.py`（Locust `RagUser`，`wait_time=between(0.5,2.0)`）+ 同目录 `CAPACITY.md`；`scripts/flashrag_eval/run_eval.py`（rerank on/off A-B，`make eval-rag`，需 pgvector） |
| 成本折算的口径对象（哪个模型、哪家供应商） | ⚠️ 现网非默认值。`docs/operations/env-126-inventory.md:218`：`LLM_BASE_URL=https://api-inference.modelscope.cn/v1`、`LLM_MODEL=LLM_FALLBACK_MODEL=deepseek-ai/DeepSeek-V4.1-Flash`；代码默认 `packages/shared-schemas/shared_schemas/settings.py:19 gpt-4o-mini`、`:25 bge-small-zh`。`qwen3-vl-flash` 在 agent_server 侧查无配置；BGE-M3 仅出现在 knowledge-service 本地评测模式（`env-126-inventory.md:222`）。**无本地 vLLM/Ollama 端点** |

## 2. 三条 claim 的可测性判定（先说哪条测不了）

| 纸面表述 | 可测性 | 处置 |
|---|---|---|
| 以 token 阈值触发压缩、摘要 | ✅ 可测 | 档位 A/B：`COMPACTION_ENABLED` off/on |
| ……与模型降级（同一句） | ❌ **无可测实现** | 二选一：(a) 实现 cost-driven 路由后再测——需新代码，且要替换 `applications/exhibition-agent/exhibition_agent/model_router.py:57-62` 的占位 ID（`"small-local-qwen"`，注「待 F2 决策后替换」）；(b) **改纸面**：把"降级"归回它真实的触发条件（失败驱动的可复位降级 + 三态熔断），该表述平台段已有。**建议 (b)：零新代码，且与代码一致** |
| 语义缓存复用历史问答、压时延与 token 开销 | ✅ 可测（但必须分轨） | 报命中率/误命中率，并对 hit 与 miss 两侧分别出数；禁给单一均值（见 §4-1） |

## 3. 实验设计

### 3.1 档位矩阵

| 档 | 压缩 | 语义缓存 | 模型 | 目的 |
|---|---|---|---|---|
| A 基线 | off | off | primary 单模型 | 出"不做任何优化"的分母 |
| B1 | on | off | primary | 隔离压缩的 token/时延效应 |
| B2 | off | on | primary | 隔离缓存效应（含 embedding 开销） |
| C | on | on | primary | 组合收益是否可加 |
| D | on | on | primary+backup（显式配两个**不同**模型） | 仅在 D 档能谈"降级"，并注明与 126 现网配置不同 |

### 3.2 变量与统计

- 阈值扫描：压缩 `COMPACTION_THRESHOLD_RATIO` ∈ {0.6, 0.8, 0.9}（乘 `MODEL_CONTEXT_WINDOW=128000`）；缓存距离 ∈ {0.03, 0.05, 0.08} → 出一条**命中率–误命中率**曲线（误命中＝返回了语义相近但口径不同的历史答案，这才是成本数字的可信度关键）。
- 样本量：golden 从 15 条扩到 **≥40 条**，必含 ① 12 轮以上长会话 8 条（压缩主场）② 同义改写问题对 12 组（缓存主场，成对才能测命中）③ 需结构化/SQL 输出的 10 条（专门暴露"结构化恒绑 primary"）。
- 重复：每 case × 3 次，温度 0；报 **P50 / P95**，不报均值（15 条以下 P95 不稳，这是扩容的理由而非偏好）。
- 指标：`input_tokens`、`output_tokens`、折算成本、TTFT、端到端时延、cache_hit、确定性判据通过、LLM 判据通过。

### 3.3 质量护栏（缺了它，省钱数字无意义）

- 每档跑同一集；**确定性判据为主判**（SQL 可执行且结果集等值 / 引用文档 ID 存在 / 能力路由等值），**LLM-as-judge 单列不合分**。理由与本仓评测纪律同源：拿确定性判据去判 LLM，测出来的是噪声不是质量——反之亦成立。
- 预先声明"净省"条件：**准确率下降 ≤ 1pt 且 P95 时延不上升**，否则该档不记为收益。写死在脚本里，不事后调。

### 3.4 需要新增的代码（只两处）

1. `packages/agent-core/agent_core/llm/pricing.py`：`PRICING: dict[str, tuple[float, float]]`（每 1K token 入/出价），文件头写死**定价抓取日期与来源 URL**；接入点是已有的 `fallback.py:90-92 on_usage(tokens, 0.0)`，把第二个参数换成折算值；落到 `trajectories.total_cost`——**列已存在，无需迁移**。
2. `scripts/cost_baseline.py`：复用 `eval/run_eval.py` 的 golden 装载形状（不改它），跑 A–D，逐条输出 JSONL，汇总写 `docs/analysis/<日期>/cost-baseline.md`。
- `cost_governance_enabled` 保持 False（`config.py:172`）。若改为 True，须同时说明它与 `query_router.py:371-372` 的 `total_cost > 0` 门禁的关系，否则 COST 记录仍不会触发。

## 4. 已知测量陷阱（写进报告，别事后找补）

1. **缓存命中即零模型调用** → 混合均值会把"命中率提升"错报成"单请求成本下降"。必须 hit/miss 分轨。
2. **结构化出参恒绑 primary**（`fallback.py:227-233`）→ 该路径不受任何降级影响，需单列。
3. **距离 vs 相似度两套阈值语义**→ 报告里必须带单位与"越小越严/越大越严"。
4. **现网 `LLM_FALLBACK_MODEL == LLM_MODEL`** → 不显式配双模型就测不出降级；测出来的也只能标"实验室配置"。
5. **embedding 自身是成本**：每次查询要算一条向量（bge-small-zh），B2/C 档的净省可能被 embedding 开销吃掉一部分，需同口径计入。
6. **定价是快照**：ModelScope 与 OpenAI 单价会变，任何 ¥ 数字必须带抓取日期，且注明"不含自建 GPU 折旧/带宽/存储"。
7. **现网模型非默认值**：以 126 实配（DeepSeek-V4.1-Flash）为准出数，代码默认的 gpt-4o-mini 另列一组，两者不可混报。

## 5. 产出与登记

- 结论回写 `CHANGELOG.md`；相关待办在 `docs/TODO.md` 销项。
- **简历侧引用规则**：只允许引用实测值，且限定词与数字同批上纸面（n、内部实验、实验室双模型配置、定价快照日期）。若 §2 走 (b)，则"降级"无需新数字，只改表述。
- 禁止把外部模板里的「节省 API 成本 30%+」当作目标值去凑——无锚不写是本仓与简历侧共同的纪律。

## 6. 工作量与依赖

| 步 | 内容 | 估时 |
|---|---|---|
| P0-1 | 定价表 + `on_usage` 折算接入 | 0.5d |
| P0-2 | `scripts/cost_baseline.py` 采集与汇总 | 1d |
| P1 | golden 扩容至 ≥40（含三类必含集） | 1d |
| P2 | 跑 A–D + 阈值扫描（含模型配额等待） | 0.5d |
| P3 | 出报告 + CHANGELOG 回写 | 0.5d |

依赖：`LLM_API_KEY`、`DATABASE_URL`（需 pgvector 扩展，`semantic_cache` 表见 `001_baseline.up.sql:30`）、126 环境或本地 `docker-compose.yml`。

## 7. 本仓约束提醒

- `scripts/check_doc_sync.py` 作为独立 CI 步骤（`.github/workflows/agent-platform-ci.yml:65-66`）会校验 AGENTS.md / ARCHITECTURE.md / README.md 中反引号路径是否已入库（`AGENTS.md:95`）。本文件未被那三者引用，故单独新增不触发失败；若后续要加引用，须同 PR 提交。
- 本次**只新增本文件**，未改代码、未 commit、未 push。`origin`＝GitHub（`Light-Towers/agent-platform`）、`company`＝内网 git（`<internal-gitlab>`），两侧均不应自动推送。
- 工作区在本文件写入前已有一处未提交改动（` M AGENTS.md`），非本次造成，未动它。
- 存在陈旧 worktree 副本 `.codeartsdoer/temp/wt-meta-review/`（内含同名 migrations SQL），勿在其中编辑。
