# ADR-0003：Dynamic TopK 断崖阈值选值依据

- **日期**：待实测后补充（当前为 M3.5 骨架）
- **状态**：**Proposed**（待消融数据后 Accepted）
- **关联**：`app/conf/rerank.yaml` → `dynamic_topk`；`eval/topk_ablation.md`（消融实验）；方案 §6.4

## Context（背景）

- `node_rerank.py` 实现断崖式动态 TopK：对 BGE reranker 排序后的文档，从 `min_k` 起检测相邻
  分数差，满足「绝对差 ≥ `gap_abs` 或 相对差 ≥ `gap_ratio`」即在断崖处提前截断，输出条数
  介于 `min_k` ~ `max_k`。
- 原始阈值为经验值：`gap_ratio=0.25` / `gap_abs=0.5`（M3 起外置到 `rerank.yaml`），
  **没有任何实验支撑**。面试追问"为什么是 0.25，不是 0.3？"时，必须有消融数据背书。
- 动态 TopK 的价值定位是 **trade-off**：固定 k=10 的 Recall@10 一定 ≥ 动态；动态的收益是
  「在 Recall 几乎不掉的前提下，减少注入 LLM 的无关上下文」（nDCG / ContextPrecision 更高、
  token 更省、幻觉更少）。

## Decision（决策）

1. **以消融实验数据为准**：阈值（`gap_ratio` / `gap_abs`）的最终取值由
   `eval/run_ablation.py`（fixed_k=3/5/10 vs dynamic(0.25,0.5)）与阈值敏感性扫描
   （0.15/0.25/0.35 × 0.5，P1）的真实结果决定。
2. 当前状态：**Proposed**。在取得真实数据前，**不宣称 0.25/0.5 为"已证明的最优值"**，
   仅保留为默认经验值（行为与线上一致）。
3. 若消融表明固定 k 在该数据集上 Recall 损失更小、token 更省，则考虑**降级为固定 k 或
   调整默认阈值**；结论写入本 ADR 并更新 `rerank.yaml`。

## Consequences（影响）

- 正面：阈值选择有据可查；评测结果可归因到具体配置（config_hash 已追踪 `rerank.yaml`）。
- 代价：消融依赖真实索引 + 重新标注的 golden；在构造样例阶段无法给出最终结论。

## 结论区（待消融数据后填写）

| 策略 | Recall@10 | nDCG@10 | 平均返回条数 | 平均上下文 token | P95 延迟(ms) |
|---|---|---|---|---|---|
| fixed k=3 |  |  |  |  |  |
| fixed k=5 |  |  |  |  |  |
| fixed k=10 |  |  |  |  |  |
| **dynamic (0.25/0.5)** |  |  |  |  |  |

**选值结论**：（待填——例如：dynamic 相比 fixed_k=10 Recall 下降 ≤Xpp，平均 token 下降 Y%，
故维持 gap_ratio=0.25 / gap_abs=0.5；或调整为新值。）

## 诚实声明

当前无真实数据：本 ADR 记录的是**选值方法论**（怎么选、用什么实验选），**不是已证明的结论**。
示例数字一律不填；待 `eval/run_ablation.py` 跑出真实结果后回填并翻转状态。
