# Plan-C2-Pivot · AI 交叉一致（路径 3）替代人工金标准

- **日期**：2026-09-29
- **范围**：`applications/knowledge-service/eval/meta_eval_judge.py`（仅 c2 spike，**不进生产**）
- **状态**：Completed（Stage 1 已合并；Stage 2 于 126 spike 容器实跑完毕，结论=未收敛回退路径 2，见文末「Stage 2 实测结果」）
- **偏离的原始设计**：批准计划「RAG 可持续评测体系设计」Phase C2 明确"主判据 = 与人工一致性 κ"（`decide()` 走 `mean_kappa(faithfulness, correctness)`，需 `human` 列）。

## 为什么要偏离

- **实际约束**：c2 需要人在 `adjudication_template.jsonl` 的 30 条上填 0/1/2；用户判定"参考 `reference` 字段自身由 `gen_golden.py` 自举生成、无人可担保其为真"→ 用可疑 reference 当锚，人工金标准的可信度不足。
- **不能替代方案**：
  - 让"更强模型"当金标准 → **循环论证**（AI 判 AI，κ 只测自一致不测对人准确），违反 meta-eval 定义。
  - 让 AI 预标 + 人纠正 → **锚定偏差**（人被动顺着预标点），结论仍打折。
- **可选降级**：把 c2 从"选型决策"降为"**评估要不要引入外部框架的初筛**"——三个 AI 在同一批 30 条上**成对**算 κ/ρ：若三方都强一致（κ≥0.6），说明"评判标准本身收敛，暂无需引入新框架"（self 胜出，保持零依赖）；若 self 与两个外部一致性都低、外部之间高，说明 self 是离群者，倾向引入外部胜出方；若三对都低，则**评判标准本身未收敛**，须回退补人工。

## 决策规则（新，写进 `decide_cross_agreement()`）

| 情形 | self vs 外部 平均 κ | 外部 vs 外部 平均 κ | 决策 |
|---|---|---|---|
| 三方收敛 | ≥0.6 | ≥0.6（或缺，仅一个外部时 n/a） | `self`（维持零依赖，spec.md 取向） |
| self 离群 | <0.6 | ≥0.6 | `external`（建议评估引入，**不固化进 pyproject**） |
| 未收敛 | 都 <0.6 | 都 <0.6 | `self` 兜底 + **信号**："须补人工标注（回退路径 2）" |

阈值 0.6 取"substantial agreement"（Landis & Koch 常用），非最优；跑完真数据分布可再校。

## 与批准计划的偏差声明

- 原计划 **四维对比**（①人机一致性 / ②成本 / ③依赖足迹 / ④可解释）→ 路径 3 下 **①变成 AI 交叉一致（代理）**，②③④保留。
- **代价**：不能直接回答"self judge 对人准不准"，只回答"外部框架会不会给出与 self 不同的判"。
- **收益**：零人工负担、可在 126 容器实跑、结论足以支撑"要不要引入 RAGAS/DeepEval"这一具体选型问题（这是最初用户诉求）。
- **不改动**：`decide()`/`evaluate_candidate()`/`agreement_metrics()`（mode 2 保留原语义）；只**新增** mode 3 分支（`--cross-agreement`）。

## Stage 划分

- **Stage 1（本轮）**：本文件 + `meta_eval_judge.py` 加 mode 3 骨架 + 单测（含 stub 分数的成对矩阵+决策分支）。**不动 pyproject，不装 RAGAS/DeepEval**。
- **Stage 2**（Stage 1 合并+确认后）：126 容器 `uv pip install --no-deps ragas deepeval`，写两个 adapter `score_ragas/score_deepeval`（faithfulness/correctness → 0..1），跑真数据出 `judge_selection.md`。用完 `uv pip uninstall` 或 `docker rm` spike 容器（不固化进 pyproject 生产依赖）。
- **Stage 3**（视 Stage 2 结果）：若走"external 建议引入"分支，用户另行批准；否则保持现状、c2 关闭。

## 验收标准（Stage 1）

1. **代码骨架**：`--cross-agreement --dataset <path>` 能读入 jsonl（含 `qid/query/context/answer/reference`）、调用现有 `make_candidate_scorer` 逐个候选打分、算出**对称成对 κ/ρ 矩阵**、按三分支给决策。
2. **不回归**：`--from-e2e`（mode 1）与 `--adjudication`（mode 2）行为不变；`decide()`/`agreement_metrics()` 保留。
3. **单测**：新增纯函数（`agreement_symmetric` / `pairwise_agreement` / `decide_cross_agreement`）+ mode 3 端到端（用 monkeypatch 桩掉 self 打分，产出报告）全部覆盖；三分支决策路径各一条正例。
4. **门禁**：`uv run --with ruff ruff check .` 绿；`uv run pytest applications/knowledge-service/tests/unit/test_meta_eval_judge.py -q` 全过；`uv run python scripts/check_doc_sync.py` rc=0；`uv run python scripts/lint_architecture.py` rc=0。
5. **诚实边界**：Stage 1 报告里**外部候选**（RAGAS/DeepEval）默认标记 `❌(未安装/未接线)`，只有 self 单腿，矩阵为退化态；此时 `decide_cross_agreement()` 应返回 `self` + "等待外部接线"的理由字符串（不误判）。

## Stage 1 不做的事

- 不真跑 LLM（那是 Stage 2 在 126 容器的事）。
- 不修改 `pyproject.toml` / `uv.lock`。
- 不动 mode 1/2 的现有语义。
- 不 commit（等 Stage 1 用户复核后再决定 commit 时机）。

## Stage 2 实测结果（2026-09-30，126 spike 容器实跑）

**环境**：`rageval-eval` 容器，`/tmp/spike-venv`（`--system-site-packages`）临时装 `ragas 0.4.3`；未进 pyproject，用完即弃。数据 = 真实 60 条 run（`e2e_after_reindex/20260929_103435`）经 mode 1 抽样 30 条（seed=0）。候选 = self + ragas（DeepEval 4.2.7 无 `AnswerCorrectnessMetric`，correctness 语义错配，本轮不接，诚实留 `_unwired`）。

**RAGAS adapter 关键工程点**（`eval/score_ragas.py`，真实 API 端到端验证）：
- ragas 0.4.3 无条件 `import langchain_community.chat_models.vertexai`（未装）→ 注入占位 `ChatVertexAI` 桩绕过；
- collections API 用 `ascore(**kwargs)`（非 `.score(sample)`），`MetricResult.value` 取 0..1；
- `AnswerCorrectness(llm, weights=[1.0, 0.0])` 关闭 embedding 相似度分量，走纯 claim-based 事实性，避免 spike 再引 embedding 模型。

**成对一致性（30 条，RC=0）**：

| 维度 | self ↔ ragas |
|---|---|
| faithfulness | κ=0.339 · ρ=0.275 |
| correctness | κ=0.097 · ρ=0.101 |

**本轮实验的直接结论**：本轮验证 Self Judge 与 RAGAS Judge 在 faithfulness/correctness 上存在较低一致性（κ=0.34/0.10）；但由于缺乏**独立于两者的 Ground Truth**（下文「自举偏差声明」），无法判断哪一个更接近真实质量。与此同时，Self Judge 在**零额外依赖、逐维理由可解释性、成本控制**三方面更符合当前工程约束，因此**暂维持 Self Judge 方案**。三分支里只有「未收敛」能触发：因为只有 1 个外部候选，「外部↔外部」对为 n/a，「self 离群→采纳外部」这条规则**结构上无法触发**。

**诚实边界（勿误读）**：

- κ 低 ≠ self judge 错。self 是 0/1/2 rubric、RAGAS AnswerCorrectness 是 claim-F1（weights=[1,0] 关 embedding），两者语义不同构；连续分再分箱到 0/1/2 损失分辨率，correctness κ=0.097 多为分箱错位。
- **Agreement ≠ Accuracy**。本轮量化的是「两个评价器行为是否一致」，不是「哪个更接近真实质量」。前者已完成（结论：不一致），后者需独立 GT。
- **GT 不必然 = 人工**。可用渠道至少四种：① 程序/规则（可抽 slot 子集）、② 权威数据源（如 exhibition-agent warehouse DB）、③ 人工专家标注、④ 多专家仲裁。本轮一个都未接入，因此无法给出选型定论。
- 产物见 `applications/knowledge-service/eval/judge_selection.md`（脚本自动产出，纯聚合、无语料明文，可入库）。

## 自举偏差声明（本 spike 的固有局限）

本轮数据集的 `reference` 字段由 `gen_golden.py`（LLM 自举）生成，无独立权威背书。这构成两个层面的风险，**均需诚实声明而非当作已解决**：

1. **锚自身可信度存疑**：若 `gen_golden.py` 对某条 query 给出了错误的 reference，self judge 与 RAGAS 会同时以同一错锚为参考 → 两方的 κ 上限被锤到锚自身质量，**高一致 ≠ 高准确**（共享同一种错误），**低一致 也不代表其中某方对**（它们可能在错锚周围各自抽射不同方向）。
2. **循环验证风险**：同一个 LLM 网关既产生 reference（写）、又当 self judge 打分（读）→ “AI 生成标准 + AI 验证标准”的环。RAGAS 虽用不同算法，但同网关同模型（Qwen2.5-7B-Instruct）→ 共享训练数据先验、共享 prompt 偏置、共享 reference→“不同”不一定“独立”。

**影响面**：本声明适用于本轮所有 κ 结果。即使后续跑人工标注（路径 2），若人工直接以同一 `gen_golden` reference 为据判断，仍受同一偏差支配。若要消除，需**至少**对 30 条抽样中的 reference 做一层独立校验（专家确认 / DB 查 / 程序抽 slot）。

**不消除 ≠ 本轮无效**。本轮回答的是“评价器行为一致性”，该问题本身不依赖 GT（一致性直接可测）；未回答的是“哪个评价器更接近真实质量”，该问题需独立 GT。两个问题不混。

## Stage 3 处置与后续分层

本轮 c2 到此**关闭选型议题**（无选型信号、工程约束满足 self）。以下后续不属于 c2 范围，归入 benchmark 化的分层后续，待用户另行推动：

- **短期（若用户想真拿定论）**：走路径 2——标注页（commit `1aea73e`）已就绪，用户人工标 30 条后跑 `--adjudication`，得 `self vs human κ` 与 `ragas vs human κ`。需先对 reference 做独立确认（避免同一偏差）。
- **中期**：给 `scorers.py` 加 `ProgrammaticScorer`，对可抽 slot 子集（日期/枚举/数字）给确定性 gold，作为第二层交叉核验。
- **长期（对齐分层）**：将 `judge_vs_human` / `judge_vs_program` / `judge_vs_db` 三张校准表显式建入 eval 架构，回答“哪个 judge 在哪个子集上可信”。检索层已分拆（`make_baseline.py` 已含 recall/mrr/ndcg，不依 LLM judge），本层仅针对 Generation 层。

