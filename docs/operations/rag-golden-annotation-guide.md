# RAG 人工标注集规范（ADR-0017 后续）

> 用途：为"稠密 + 引擎 BM25"与旧方案的质量判决提供**人工 golden**。
> 当前只有 self-retrieval canary（`real_corpus_ab.json`）与 12 条合成样本，**不能**作为最终上线质量依据。

## 1. 候选集生成

量具：`applications/knowledge-service/eval/build_golden_candidates.py`

```bash
python eval/build_golden_candidates.py \
  --uri http://milvus:19530 \
  --collection product_manual_v4_bge_m3 \
  --limit 20 \
  --out eval/golden_queries.real_candidates.jsonl
```

输出每条强制带 `review_status=pending_human_review`，`relevant_chunk_ids` 只是"来源文档"假设，**不是标注结论**。人工复核前不得喂给 `run_eval.py` / `run_route_ablation.py` 做判决。

已生成交接件：`applications/knowledge-service/eval/golden_queries.real_candidates.jsonl`（20 条候选，来自 v4 集合；仍有截断句，标注人须改写为自然问句后再 `approved`）。

## 2. 抽样规则

1. 从 v4 集合（83 行真实切片）按文档去重，每篇文档最多 1 条候选。
2. 覆盖三类：
   - **精确型**：含型号、缩写、产品名（如 `HAK-180`、`BGE-M3`）；
   - **术语型**：领域名词、工序、材料；
   - **口语改写型**：从正文抽取的问法，或人工把标题改写成用户口吻。
3. 每类至少 5 条，总数不少于 20 条；不足 20 条时允许补同类文档，但须在 `tags` 标注。

## 3. 标注规则

- 每条 query 必须能在标注集中找到至少 1 个 `grade >= 2` 的 chunk；找不到则丢弃该候选，不强行标注。
- `grade` 取值：`2` = 直接回答；`1` = 部分相关；`0` = 不相关（不写入 `grade`）。
- 多文档相关时全部写入 `relevant_chunk_ids` 并逐条给 `grade`；禁止只标 top1。
- query 不得抄整段原文（>40 字须改写为自然问句），否则退化成精确匹配测试。
- 标注人不得参考模型检索结果；先定标注，后跑评测。

## 4. 判决流程

1. 人工复核后把 `review_status` 改为 `approved`，并填写标注人 / 日期。
2. 在同一环境、同一 rev 上分别跑：
   ```bash
   python eval/run_route_ablation.py --golden <approved.jsonl> ...
   ```
   对比 dense-only / 旧 hybrid / 新 hybrid 的 recall@5、recall@10、MRR。
3. 切换判据：**新 hybrid 在精确型与术语型上不低于旧方案，且口语改写型整体 MRR 不低于旧方案**。任一回退即不切换。
4. 读数必须绑定 rev、集合版本、分词器 profile、判决时间，按 `docs/operations/evidence-format.md` 记录。

## 5. 复审触发条件

- 词典内容或 `RETRIEVAL_ANALYZER_PROFILE` 变化；
- Milvus 版本变化（2.6 → 3.0 等）；
- golden 集合增删超过 10%；
- 出现"标注集跑分变绿但现网用户反馈变差"的情形。

出现任一即重新抽样、重新标注，不复用旧读数。
