# Plan-C2-Pivot · AI 交叉一致（路径 3）替代人工金标准

- **日期**：2026-09-29
- **范围**：`applications/knowledge-service/eval/meta_eval_judge.py`（仅 c2 spike，**不进生产**）
- **状态**：Executing（Stage 1）
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
