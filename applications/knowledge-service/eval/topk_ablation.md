# Dynamic TopK 消融实验（M3.5，方案 §6.4）

> **背景**：`node_rerank.py` 的断崖式动态 TopK（`gap_ratio=0.25` / `gap_abs=0.5`，M3 起外置到
> `app/conf/rerank.yaml`）是项目最大的排序侧亮点，但阈值**原本无实验支撑**。面试必问：
> "为什么是 0.25，不是 0.3？"——本消融实验就是回答这个问题的证据链。
>
> **⚠️ 诚实声明**：Review 中曾出现的示例数据表是**编造的示意，严禁照抄**。本文档只提供
> **实验设计与空表模板**，所有数字必须由 `eval/run_ablation.py` 真实跑出后填写。
> 当前 golden 为构造样例（`c_xxx` 假设标注），真实跑分预期全 0，属预期现象，不是失败。

## 1. 实验目的（trade-off，不是"谁 Recall 高"）

动态 TopK 的价值**不是提升 Recall**——固定 k=10 的 Recall@10 一定 ≥ 动态（动态最多取 10 条）。
它的价值在于：

> **在 Recall 几乎不掉的前提下，大幅减少注入 LLM 的无关上下文**
> —— 即 nDCG / ContextPrecision 更高、token 更省、幻觉更少。

实验要证明的正是这个 trade-off：dynamic 相比 fixed_k=10，平均返回条数 / 平均注入 token 显著
下降，而 Recall@10 损失可接受（需给出可接受阈值，如 ≤1pp）。

## 2. 实验设计

| 项 | 设定 |
|---|---|
| 自变量 | 截断策略：`fixed_k=3` / `fixed_k=5` / `fixed_k=10` / `dynamic(0.25, 0.5)` |
| 控制变量 | 同一索引集合、同一 golden set、同一 RRF 权重、同一 reranker、同一随机种子 |
| 因变量 | Recall@K、nDCG@10、**平均返回条数**、**平均上下文 token 数**、P95 延迟 |
| 样本 | `eval/golden_queries.jsonl` 全量（56 条） |
| 重复 | 检索链路确定性执行，跑 1 轮即可；若含 LLM 生成指标则跑 3 轮取均值 |

策略口径（与 `eval/run_ablation.py` 实现一致）：

- `fixed_k=3/5/10`：复用线上链路（embedding 召回 → RRF 融合 → BGE 重排），随后固定截断前 k 条
  （与线上"同一 reranker"的控制变量一致；`--skip-rerank` 时退化为 RRF 顺序截断）。
- `dynamic`：走线上默认链路，断崖式动态 TopK 在 `node_rerank` 内部执行，脚本不截断。
- **不改动任何线上节点代码**，消融仅在 `run_ablation.py` 层面切换策略。

## 3. 结果表（空模板，实测后填写，禁止预填）

| 策略 | Recall@10 | nDCG@10 | 平均返回条数 | 平均上下文 token | P95 延迟(ms) |
|---|---|---|---|---|---|
| fixed k=3 |  |  |  |  |  |
| fixed k=5 |  |  |  |  |  |
| fixed k=10 |  |  |  |  |  |
| **dynamic (0.25/0.5)** |  |  |  |  |  |

> 说明：`avg_returned` 由脚本真实计算（fixed_k 的理论上限等于 k，实际受"总候选 < k"影响
> 可能更低）；`avg_tokens` 为启发式估算（CJK 1 token/字符，其余 4 字符/token）；
> `P95 延迟`为**检索链路**（召回→RRF→重排）口径，不含 LLM 生成。

## 4. 阈值敏感性扫描（P1 可选，空表模板）

| gap_ratio | gap_abs | Recall@10 | nDCG@10 | 平均条数 |
|---|---|---|---|---|
| 0.15 | 0.5 |  |  |  |
| 0.25 | 0.5 |  |  |  |
| 0.35 | 0.5 |  |  |  |

> 敏感性扫描需要 `rerank.yaml` 可动态改阈值后重跑（M3 已外置），可写一个循环脚本；
> 当前 `run_ablation.py` 只固定跑 `dynamic(0.25, 0.5)`，敏感性扫描为 P1 增强。

## 5. 如何跑

```bash
# 前置：1) 已运行 import_process 建立真实索引（集合 product_manual_v1_bge_m3）
#       2) golden_queries.jsonl 的 relevant_chunk_ids / grade 已按真实 chunk_id 重新标注
python eval/run_ablation.py --out eval/runs/          # 全量 56 条 × 4 策略
python eval/run_ablation.py --out eval/runs/ --limit 5   # 调试：前 5 条
python eval/run_ablation.py --out eval/runs/ --skip-rerank  # 无 reranker 环境的退化模式
```

输出：`eval/runs/{timestamp}_{config_hash}/ablation.md`（Markdown 对比表 + 统计口径说明）。

## 6. 跑完后要做的（闭环）

1. 把实测数字填入本文档结果表（以及 `eval/README.md` 实验索引表）。
2. 在 `docs/adr/0003-dynamic-topk-threshold.md` 记录选值依据，Status 由 Proposed → Accepted。
3. 挑选 2~3 个代表性 badcase 做归因（方案 §6.5）：dynamic 比 fixed_k=10 少带了哪些无关块、
   Recall 是否真的没掉、token 省了多少。
