# Plan · 多专家仲裁参考标准（Judge Calibration 分层后续，Generation 层独立参照）

- **日期**：2026-09-30 · **v3**（纳入第二轮 review：faithfulness/correctness 证据域分离、Likert 改 quality、抽样去循环、κ 三段制、3/3 blind audit、仲裁两段式去 anchoring、bootstrap CI、reference 语义收口、措辞从"金标准/真理"降为"专家仲裁参考标准"）
- **范围**：`applications/knowledge-service/eval/`（标注 UI 扩展 + 新增合并/仲裁脚本 + 单测），**不进生产链路**、不改 `run_e2e_eval.py` 主门禁。
- **状态**：Proposed（未启动，待用户勾选设计决策 + 确认专家可得）
- **承接**：`docs/plans/plan-c2-cross-agreement-pivot-2026-09-29.md`「Stage 3 处置与后续分层」中的**多专家仲裁**条；本文件是那条的展开方案。
- **相关 commit**：`1aea73e` 离线标注页 UI（本方案扩展基座）· `4278e23` c2 Stage 2 RAGAS adapter 接线 · `dd76835` c2 结论严谨化 + 自举偏差声明。
- **入库时间**：2026-10-02。成文后始终**只在本地保存、无任何 git 历史**（全仓唯一副本在本机，丢了就不可恢复），随台账 `plan-branch-disposition-2026-10-01.md` §8 的收尾取证一并入库。三个基座提交已随 **PR #50**（`test/rag-route-ablation-eval` 整支并入，主干 tip `617cbf2`）进主干，但**本方案本身仍未启动**，状态保持 Proposed。文中 `gold.jsonl` 与 `docs/eval/gold-rubric-v1.md` 是本方案的**待产出物**（且 D12 明确 `eval/gold.jsonl` 要进 `.gitignore`），今日不存在属预期、非悬空引用。

## 定位先行：这是"参考标准"，不是"客观真理"（v3 认知重框）

多专家 gold **不是** Ground Truth 意义上的"真理"，而是 **expert-adjudicated reference standard（专家仲裁参考标准）**。它天然独立于 self/ragas 两个 judge，能回答"哪个 judge 更接近受过校准的人类判断"，但**不等于**"更接近客观正确"——因为专家可能同向错（见「风险」，已加 blind audit 缓解）。全文与最终报告均用"参考标准"措辞，不使用"金标准/真能定谁更准"的表述。

## 为什么要做

c2 关闭选型议题后，Generation 层遗留**结构性缺口**：self judge 与 RAGAS judge 都以 `gen_golden.py` 自举的 reference 为锚，任何 agent 链路改动（prompt 微调 / context 组装变 / rerank 权重动 / planner 路径切）引起的**细粒度语义退化**，会被 judge 内部方差 + 参考锚自身漂移的双层噪声吞掉。当前架构只能报"大退化"，报不出"措辞略糊 / 少引一个 chunk"。

要覆盖细粒度退化，必须引入**独立于 judge、且独立于当前被测系统产物**的第三参照。四种候选源里（程序/DB/人工/仲裁），语义类问答唯一可行的是**多专家仲裁**。

## 两个维度，两个证据域（v3 核心，回应 P0-1 + P1-6）

v2 用单一 `context_mode`（标注 raw / 仲裁 expanded）在**同一维度**上切信息集，会造成**构念漂移**：expanded 下判出的 faithfulness 已不再评价"当前 RAG→Answer"，而是评价"扩大检索后 Answer 是否合理"——这把 retrieval failure 与 generation failure 混在一起，破坏了架构的 Retrieval/Generation 分层。

v3 的修法不是"选 raw 还是 expanded"，而是**按维度固定证据域**：

| 维度 | 参照名 | 专家看什么 | 回答的问题 | 为什么这样定 |
|---|---|---|---|---|
| **faithfulness** | Gold-G（Generation gold） | `query + 实际送给 LLM 的 context + answer` | 在系统**实际提供**的信息下，answer 是否被 context 支持？ | 忠实性只关心"答案 vs 它拿到的上下文"；context 缺 chunk 导致答案无据 → **合法地低 faithfulness**，正是被测的 generation 层信号，不该被 expanded 抹平 |
| **correctness** | Gold-K（Knowledge gold） | `query + 权威证据（expanded TopK=20 + 允许外部：DB/官方文档/web）+ answer` | answer **本身客观是否正确**？ | 正确性需要独立于当前 context 的证据；只看 context 专家无法判断"context 自身错没错" |

关键：**一个维度只绑一个证据域，不让同一 context 承担两个概念**。这样 gold 既斩断对 `gen_golden.py` reference 的依赖（`--hide-reference`），又斩断对 judge 逻辑的依赖，且 faithfulness 不越界去评检索。D3 三层次独立性中，①斩 reference ③斩 judge 保持；②斩 context 组装改为"faithfulness 用 actual、correctness 用 authoritative"，不再用统一 toggle。

## 前置约束（deal-breaker，先自评这三问）

1. **能召集 ≥ 3 位专家吗？** 且专家能力需**按维度对齐**（v3，回应 P1-7）——不假设"3 人 = 3 维"：
   - **Evaluation expertise**（方法学）：把关 rubric 一致性、仲裁流程；
   - **Domain expertise**（领域）：**correctness/Gold-K 只有他能判**（通用 RAG 覆盖法律/医学/技术/产品，产品经理不天然具备事实正确性判断力）；
   - **User-relevance expertise**（资深用户/业务方）：贴近真实用户视角。
   若缺 domain expertise → correctness gold 不可信，只能出 faithfulness gold。凑不齐 → 整个方案空转。
2. **愿意投入 5–7 人时 + calibration 会 + 仲裁会吗？** 三人共标 5 条 calibration ~45min + 各标 30 条 ~1h/人 + 第 4 人仲裁/audit + 你写代码 ~1 天。
3. **能接受"rubric 定标可能一轮不收敛"吗？** 首次 κ < 0.4 属正常，需重新过边界案例再标。

**任一答案为否** → 先做**程序化 scorer**（Stage 3 中期，~100 行，覆盖 10–20% 可抽 slot 子集，零外部人力），把简单参照先建起来。

## 目标与非目标

**目标（Stage A）**
- 30 条（representative + diagnostic 双轨，见「抽样」）真实 e2e 样本 → 3 位专家共标 5 条 calibration（**不并入 30 条**）→ 独立并行标 30 条 → 非全票项第 4 人两段式仲裁 + 全票项 10% blind audit → 产出 `gold.jsonl`
- 用 `gold.jsonl` 跑 `meta_eval_judge.py --adjudication`，得 **self vs gold / ragas vs gold** 各自的 **κ + quality Spearman + bootstrap 95% CI**
- 建立可复用流程 + 工具，后续扩样本或换主题不重造轮子

**非目标（v3 明确边界）**
- **不 calibrate relevance**（v3，回应 P1-8）：架构三维 faithfulness/relevance/correctness，Stage A gold **只覆盖 faithfulness + correctness 两维**，relevance 无 human 标注、不参与本轮 calibration 比较——最终报告须显式写"未校准 relevance"，避免"三维都被 gold 校准"的错觉。
- 不覆盖检索层（`make_baseline.py` 已程序化评）
- 不改 `run_e2e_eval.py` 主门禁；gold 做**校准参照**，非日常回归
- 不追求样本量放大（30 条起步，100+ 归 Stage C）；**30 条不足以做统计显著性总判定**（见「最终报告措辞」）
- 不做跨项目通用 gold 平台

## 架构定位

```
┌── Retrieval Eval（已有，程序化，不依 LLM）
│      recall@K · mrr · ndcg · hit_rate
│
├── Generation Eval（现状：仅 self judge，噪声大）
│      faithfulness · relevance · correctness
│      └─ Stage A gold 只校准 faithfulness + correctness（relevance 不校准）
│
├── E2E 回归门禁（已有：compare_runs + paired bootstrap）
│      降噪器，不是锚
│
└── Judge Calibration（本方案新增，独立参照，非真理）
       ├── 程序化 scorer（Stage 3 中期，可抽 slot 子集，零噪声）
       └── 多专家 reference standard（本方案，覆盖语义判断）
              ↓
       self vs gold κ + quality Spearman + bootstrap CI
       ragas vs gold κ + quality Spearman + bootstrap CI
              ↓
       回答"哪个 judge 更接近受校准的人类判断"（c2 无法答的问题；≠"谁客观更准"）
```

## 代码改动清单

### M1 · 标注 UI 扩展（改 `make_adjudication_ui.py`）

- **`--expert <name>`**：导出 jsonl 加 `expert_id`；localStorage key 按 `<expert>` 命名空间隔离
- **`--hide-reference`**（默认关闭以兼容路径 2；gold 版启用）：卡片不渲染 reference，防锚偏差延伸
- **按维度分栏 + 证据域固定**（v3 取代 `--context-mode` toggle）：同一卡片内
  - faithfulness 栏：只显示 `answer + actual context`（实际送 LLM 的那份）；
  - correctness 栏：显示 `answer + authoritative evidence`（TopK=20 expanded，并可附外部查证入口）；
  - 两栏各自独立 0/1/2 单选，互不污染。
- **quality 连续分**（v3 取代 v2 的 Likert "把握度"，回应 P0-2）：每维在 0/1/2 之外加 **quality 1–5**（1=完全错误 … 5=完全正确），这是**质量**不是**信心**，用于与 judge 连续分做 Spearman。
  - 说明文字写死语义，避免被读成 confidence。可选再留一个 `confidence 1–5` 作**标注质量诊断**（不参与 calibration）。
- 改动量：**~50 行 Python**
- 影响现有单测：`test_make_adjudication_ui.py` 加 3 条（expert_id 字段 / hide-reference 分支 / 双栏证据域 + quality 字段）

### M2 · 合并 + 一致性计算（新 `collect_adjudications.py`）

- 输入：N 份 `adjudication.<expert>.jsonl`（N ≥ 3）
- **完整性硬约束**（v3，回应 P2-4）：正式 30 条要求**每专家每维全部标完**，否则该批次不进 κ 计算（Stage A 用强完整性，不做 pairwise/item deletion）；duplicate qid 校验。
- **分组规则**（v3，回应 P1-5）：
  - **全票一致（3/3）**→ `provisional gold`，**并随机抽 ~10%（30 里约 2–3 条）交第 4 人 blind audit**，验证"3/3 = 可靠"假设；若 audit 揭出系统性同向错 → 扩大 audit。
  - **多数票（2/3）/ 无多数（各异）**→ 进仲裁队列，走第 4 人两段式仲裁。
- **一致性算法**：Stage A **只用 Fleiss' κ**（≥3 标注者、三档，实现直接不易错）；Krippendorff's α（ordinal，处理缺值+加权）延到 Stage B，均手写不引第三方库。`agent_core.metrics.compare` 已有 `cohens_kappa`，新增 `fleiss_kappa`。
- **连续信号**：quality 1–5 维间算 **Spearman ρ**（`agent_core.metrics.compare` 已有）作 κ 的第二把尺。
- 输出 `inter_annotator_agreement.md`（κ + Spearman 双指标 + audit 命中）。
- 改动量：**~150 行** + ~15 单测（分组、票决、完整性、Fleiss 边界、quality Spearman、audit 抽样）。

### M3 · 仲裁 UI（新 `make_arbitration_ui.py`，复用 M1 模板）

- 只渲染分歧项（含多数票），按 priority 排序；faithfulness 用 actual context、correctness 用 authoritative evidence（与 M1 一致）。
- **两段式去 anchoring**（v3，回应 P2-2）：第 4 人**先独立 blind 判**（只看 `query + evidence + answer`，看不到专家标签）→ 落初始判 → **再展示各专家 0/1/2 + quality + 理由** → 允许改判并写"是否因专家理由改判"。**不采用"三人+第4人全体讨论"**（v3，回应 P2-3：那是另一套 consensus 协议，产出的 gold 性质不同，Stage A 固定为第 4 人 blind→review 一种）。
- 导出 `arbitration_result.jsonl`（含第 4 人 blind 初判 + 最终判 + 改判标记 + 理由）。
- 改动量：**~180 行**（复用 M1 组件，主要加两段式状态 + 并列布局）。

### M4 · gold 合成（新 `finalize_gold.py`）

- 合并「3/3 自动项 + audit 通过项」+「第 4 人仲裁裁定项」 → `gold.jsonl`。
- Schema 与现有 mode 2 输入兼容：`{qid, query, context_actual, context_authoritative, answer, human:{faithfulness, correctness}, human_quality:{faithfulness, correctness}}`。
- **reference 语义收口**（v3，回应 P1-9）：若保留 reference，必须标 `reference_role: "legacy_self_generated_anchor"` + `not_used_for_human_label: true`，明确它是 **metadata 不是 gold 证据**，防后续分析把 human gold 与自举 reference 混为一套。
- `human` 语义 = "仲裁后参照"，字段名保留以**避免下游破坏**；`gold_meta.json` 加 `label_origin: "multi_expert_adjudication"`（v3，回应 P1-10），并注明未来宜演进到 `gold:{...}` 字段。
- 理由旁挂（v3，回应 P2-5）：专家/仲裁理由存 `adjudication_record.jsonl`（qid→labels/reason/改判），**不入 gold 主 schema**，便于将来回答"这条为何是 1 不是 2"。
- 元信息 `gold_meta.json`：`{sample_n, experts:[...], expert_roles, fleiss_kappa:{faithfulness,correctness}, quality_spearman:{faithfulness,correctness}, audit:{n_audited, n_overturned}, sampling_strategy:{representative:15, diagnostic:15}, calibration_set_size:5, disjoint_from_eval:true, label_origin:"multi_expert_adjudication", rubric_version:"v1", generated_at:"..."}`。

### M5 · Judge Calibration 端（`meta_eval_judge.py` 最小改动）

- 现有 mode 2 `--adjudication gold.jsonl --candidates self,ragas` 读 `human` 算 κ（**0 行改动**）。
- **v3 增强**（~25 行）：
  - 若含 `human_quality` → 额外算 judge 连续分 vs quality 的 **Spearman ρ**（30 条下比 κ 稳）。
  - **映射契约固定**（v3，回应 P1-11）：明确记录 candidate 连续分 → canonical 0/1/2 的分箱规则（`to_bucket`），**self 与 ragas 用同一映射**，否则 κ 不可比；把映射阈值写进报告。
  - **bootstrap CI**（v3，回应 P1-12）：对 κ 与 Spearman 各给 **95% bootstrap CI**（已有 paired bootstrap 底座可复用）；CI 高度重叠即判"两者无可信差异"。
- 出 `self/ragas 各自 vs gold 的 κ + quality Spearman + CI` → 本轮 calibration 结果（非"谁绝对更准"的定论）。

## 抽样策略（v3 重构，回应 P0-3 + P1-13）

v2 用 **self judge 分数**切 easy/borderline/hard 存在**循环**：让 self 参与了"给自己出考题"（selection bias），且把 self 打分当"难度"命名失真（self=2 只是"self 认为容易"）。

v3 改**双轨 15 + 15**：
- **representative 15 条**：在 60 条 run 上**随机/按自然分布抽**，不经 self 分数筛选 → 用于 **Overall calibration**（这是能弱外推的部分）。
- **diagnostic 15 条**：刻意过采 self-borderline + self-hard + recall@5=0 的样本（judge 易分歧区）→ 用于 **Diagnostic calibration**（压力测试，不外推）。

**报告必须分开**：`Overall（15 自然）` vs `Diagnostic（15 困难）` 两组 κ/Spearman/CI 各报。命名上把 v2 的"difficulty strata"改称 **"self-judge score strata"**（承认是按 self 分数分层，非客观难度）。抽样比例落 `gold_meta.json.sampling_strategy` 可追溯。

## 流程（八步，v3 加 audit + 两段式仲裁 + calibration 隔离）

| 步 | 内容 | 时长 |
|---|---|---|
| 1 | **定 rubric**（faithfulness=actual context / correctness=authoritative 的定义 + quality 1–5 语义 + 边界案例）→ `docs/eval/gold-rubric-v1.md`（只入方法学，不入语料） | 1h |
| 1.5 | **三人共标 5 条 calibration**：现场各选、当场对分歧、把边界规则**回填进 rubric**；**这 5 条 ∉ 最终 30 条**（v3，回应 P2-1，写死 disjoint） | ~45min |
| 2 | 3 位专家**独立并行**标 30 条（互不可见，`--hide-reference`，faithfulness 用 actual / correctness 用 authoritative） | 各 ~1h |
| 3 | `collect_adjudications.py`：完整性校验 → 3/3 入 provisional + 抽 10% audit；其余进仲裁队列；出 Fleiss κ + quality Spearman（**分 Overall/Diagnostic**） | 脚本 |
| 4 | **κ 三段制**（v3，回应 P1-4，取代"κ<0.67→rubric 错"硬门禁）：<0.4 → 复核 rubric/流程；0.4–0.67 → inspect disagreement+边界，**不自动判 rubric 错**；≥0.67 → 进正式仲裁。κ 是**诊断指标非硬门禁**，目标是拿到 gold 不是最大化专家间 κ | — |
| 5 | **第 4 人两段式仲裁**全部非全票项（blind 初判 → 看专家标签理由 → 必要时改判）+ 完成 3/3 的 blind audit | ~2h |
| 6 | `finalize_gold.py` → `gold.jsonl`（+ `adjudication_record.jsonl` + `gold_meta.json`） | 脚本 |
| 7 | `meta_eval_judge --adjudication gold.jsonl --candidates self,ragas` → calibration 报告（κ + Spearman + bootstrap CI，分 Overall/Diagnostic） | 脚本 |

## 关键设计决策（待用户勾选）

| # | 决策 | 推荐值（v3） | 备选 |
|---|---|---|---|
| D1 | 专家数 N | **3**（最小可用）+ 第 4 人仲裁/audit | 4–5 |
| D2 | 专家能力 | **按维度对齐**：evaluation / domain / user-relevance（domain 缺失则 correctness 不可信） | 三视角混用 |
| D3 | reference 遮不遮 | **遮**（gold 版强制） | 不遮 |
| **D4** | **证据域**（v3 取代 context_mode） | **faithfulness=actual context / correctness=authoritative evidence**，分栏固定 | 单 toggle raw↔expanded（v2，会构念漂移） |
| **D5** | **连续分语义**（v3） | **quality 1–5（质量）**，Spearman 用之；confidence 仅可选诊断 | Likert=把握度（v2，会与 judge 错配） |
| **D6** | **κ 阈值**（v3） | **三段制诊断（<0.4 / 0.4–0.67 / ≥0.67），非硬门禁** | 单 0.67 门槛（v2，过强） |
| **D7** | **分歧处理**（v3） | **3/3 自动 gold + 10% blind audit；其余全过仲裁** | 无 audit（v2，吞 3/3 同向错） |
| **D8** | **抽样**（v3） | **representative 15（自然）+ diagnostic 15（困难）双轨分报** | 纯 self-score 分层（v2，循环偏差） |
| D9 | 一致性算法 | **Stage A 只 Fleiss κ**，α 延 Stage B | 直接上 α（易错） |
| **D10** | **仲裁协议**（v3） | **第 4 人 blind→review 两段式**（去 anchoring） | 全体讨论 / 直接并列（污染） |
| D11 | relevance | **Stage A 不 calibrate**，报告显式声明 | 强行加第三维 |
| D12 | gold 落盘 + 数据治理 | `eval/gold.jsonl` **进 .gitignore**；轻定义 storage/retention/access/cleanup（v3，回应 P2-6：.gitignore≠数据安全） | 仅 .gitignore |
| D13 | 输出指标 | **κ + quality Spearman + bootstrap 95% CI，分 Overall/Diagnostic** | 单点 κ |

## 数据契约（三张表 + 元数据 + 旁挂理由）

**`adjudication.<expert>.jsonl`**（M1 产出，每专家一份）
```json
{"qid":"...","query":"...","context_actual":"...","context_authoritative":"...","answer":"...",
 "expert_id":"alice",
 "human":{"faithfulness":1,"correctness":2},
 "human_quality":{"faithfulness":3,"correctness":4},
 "confidence":{"faithfulness":4,"correctness":2}}
```

**`arbitration_queue.jsonl`**（M2 产出，非全票一致项）
```json
{"qid":"...","query":"...","context_actual":"...","context_authoritative":"...","answer":"...",
 "priority":"high",
 "labels":[{"expert":"alice","faithfulness":1,"faithfulness_quality":3,"correctness":2,"correctness_quality":4},
           {"expert":"bob","faithfulness":0,"faithfulness_quality":2,"correctness":2,"correctness_quality":5},
           {"expert":"carol","faithfulness":2,"faithfulness_quality":4,"correctness":1,"correctness_quality":3}],
 "disagreement_on":["faithfulness","correctness"]}
```

**`gold.jsonl`**（M4 产出，兼容现有 mode 2）
```json
{"qid":"...","query":"...","context_actual":"...","context_authoritative":"...","answer":"...",
 "reference":"...","reference_role":"legacy_self_generated_anchor","not_used_for_human_label":true,
 "human":{"faithfulness":1,"correctness":2},
 "human_quality":{"faithfulness":3,"correctness":4}}
```

**`adjudication_record.jsonl`**（M4 旁挂，理由/改判可追溯，不入 gold 主 schema）
```json
{"qid":"...","adjudication":{"method":"expert4_blind_then_review",
  "blind_initial":{"faithfulness":1},"final":{"faithfulness":1},"changed_after_seeing_experts":false,
  "reason":"...","original_labels":[...]}}
```

**`gold_meta.json`**：见 M4（含 `label_origin / expert_roles / audit / sampling_strategy{representative,diagnostic} / disjoint_from_eval / fleiss_kappa / quality_spearman` 等）。

## 分阶段推进

- **Stage A（MVP，本方案范围）**：双轨 15+15 · 3 专家 + 第 4 人 · 5 条 calibration（disjoint） · 证据域分维固定 · 3/3+audit / 其余两段式仲裁 · 出 Overall+Diagnostic calibration 报告（κ+Spearman+CI）。**代码 ~500–700 行**（v3，回应 P2-7：含 schema 校验、缺值/重复、双证据域对齐、CLI、错误提示，视现有 UI/metrics 复用度） + ~28 单测。
- **Stage B（算法扩展）**：加 Krippendorff α、扩样本 100+、可选 relevance 维、可选按 query 类型分层。
- **Stage C（rubric 迭代）**：若 Stage A κ<0.4 或 audit 揭系统性错，回炉 rubric 重跑。

## 验收标准（Stage A）

1. **代码**：M1–M5 实装；`meta_eval_judge.py` mode 1/2/3 **零回归**（M5 仅在 `human_quality` 存在时加 Spearman+CI，向后兼容）。
2. **不回归**：mode 1 `--from-e2e`、mode 3 `--cross-agreement` 行为不变；标注页路径 2 用法保持（新字段可选、默认向后兼容）。
3. **单测**：`test_collect_adjudications`（分组/票决/完整性/重复 qid/Fleiss/quality Spearman/audit 抽样）、`test_finalize_gold`（provisional+audit+仲裁三径合成 + quality/reference_role 透传 + 理由旁挂）、`test_make_arbitration_ui`（两段式状态 + 分维证据渲染）、`test_make_adjudication_ui`（expert_id/hide-reference/双栏证据/quality）、`agent_core.metrics.test_fleiss_kappa`（全同/全异/单维偏）、`test_bootstrap_ci`（重叠判定）。
4. **门禁**：`uv run --with ruff ruff check` 绿 · `uv run pytest applications/knowledge-service/tests/unit -q` 全过 · `check_doc_sync.py` rc=0 · `lint_architecture.py` rc=0。
5. **端到端**：3 专家 jsonl → 一份 `gold.jsonl` → `--adjudication` 出 `judge_calibration.md`（self/ragas 各自 vs gold 的 **κ + quality Spearman + bootstrap CI，分 Overall/Diagnostic**）。
6. **诚实边界（报告须显式写）**：
   - 专家数与**角色**（不写姓名）、rubric 版本、calibration 是否触发规则回填、**calibration 5 条 ∉ 30 条**；
   - Fleiss κ + quality Spearman + **CI**（Overall/Diagnostic 分开）；
   - **faithfulness 用 actual context、correctness 用 authoritative evidence 的事实**（两维证据域不同，不可跨维直接比）；
   - **样本按 self-judge score 分层存在 selection bias**（diagnostic 轨），只有 representative 轨可弱外推；
   - **Stage A 未校准 relevance**；
   - **gold = 专家仲裁参考标准，非客观真理**；30 条不足以断言"谁绝对更准"。

## 风险与替代

**最大风险**：专家同向错 → gold 也漂；此时 self 与 gold 的低 κ 反而可能说明 self 更接近真相。

**v3 缓解（五管齐下）**：
1. **证据域分维固定**：faithfulness 锁 actual context，correctness 用 authoritative，不混（破除构念漂移）。
2. **3/3 blind audit**：抽 10% 由第 4 人复核，直接检验"全票一致=可靠"假设（破 v2 无法防的 3/3 同向错）。
3. **多数票也过仲裁**（不自动入 gold）：破"2 宽松吞 1 严格"。
4. **第 4 人两段式 blind→review**：破 anchoring。
5. **calibration 前置对齐 + 报告用 CI**：破专家漂移 + 小样本过断。

**替代方案对比**：

| 方案 | 覆盖 | 建设成本 | 依赖外部 | 结论强度 |
|---|---|---|---|---|
| 本方案（多专家仲裁参考标准） | 语义判断类 faithfulness+correctness | ~500–700 行 + 5–7 人时 | 需 3+1 专家 | **中-高**（能答"谁更接近受校准人类判断"；受样本量/参考标准非真理限制，不外推总分布） |
| 程序化 scorer | 可抽 slot 子集 10–20% | ~100 行 | 零 | 中（子集内确定性高，覆盖窄） |
| DB/API 权威源 | 事实类 ~15–25% | 中（接口对接） | 需业务 DB | 高（子集内，真独立 GT） |
| 单专家人工 | 语义类 100% | ~0 行 + 1h | 需 1 位 | 低（无仲裁、单人偏置不可见） |

**建议顺序**：**程序化 scorer → DB/API（有垂直域）→ 多专家仲裁**。前两者先覆盖能机械核验的部分，多专家只兜语义判断，能把所需专家样本压到 15–20 条内。

## Stage A 不做的事

- 不上 Krippendorff α（Stage B）；不引第三方 κ/α 库（`agent_core.metrics.compare` 手写）。
- 不 calibrate relevance（只 faithfulness+correctness）。
- 不做样本量 >30 的 Stage C；不把 30 条当总体 benchmark 或"谁绝对更准"的统计定论。
- 不改 `run_e2e_eval.py` 日常门禁，gold 只做校准参照。
- 不做专家身份认证/签名（内部小圈子）。
- 不做 query 类型分层（先用 representative/diagnostic 双轨）。

## 最终报告措辞（v3 收敛）

**删除** v2 的"多专家 gold → 真能定谁更准"表述。**固定措辞**：

> 在本次定义的样本分布（representative 15）与标注协议下，self judge 与专家仲裁参考标准的一致性为 κ=?（95% CI [?, ?]），RAGAS 为 κ=?（95% CI [?, ?]）；quality Spearman 同理。困难子集（diagnostic 15）另报。gold 为 expert-adjudicated reference standard，非客观真理；本文结果仅用于本轮 judge calibration，**不外推至全部问答分布，也不断言谁客观更准**。CI 高度重叠时判"无可信差异"。
