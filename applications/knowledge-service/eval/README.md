# 检索评测体系（M2，方案 §6）

本目录提供掌柜智库检索链路的质量评测闭环：golden 数据集 → 逐条检索 → 指标计算 →
badcase 归档 → 索引 registry 得分回填。

> **诚实声明**：`golden_queries.jsonl` 为**构造 / 脱敏样例，非线上日志**（方案 §13 口径）。
> 所有指标数字必须实测后填写，本仓库禁止预填任何评测结果。

## 目录结构

| 文件 | 说明 |
|---|---|
| `golden_queries.jsonl` | 脱敏 golden query 数据集（56 条，4 类 tag，含 grade 分级） |
| `metrics.py` | 检索指标纯函数：Recall@K / HitRate@K / MRR / DCG / nDCG |
| `run_eval.py` | 评测 CLI：逐条跑检索链路（召回→RRF→重排，不含 LLM 生成）并输出指标 |
| `runs/` | 评测输出目录（`{timestamp}_{config_hash}/`，gitignore 后由 nightly 归档） |
| `README.md` | 本文件：用法 + 实验索引表（空模板，实测填写） |

## golden 数据集格式

每行一条 JSON（`#` 开头为注释行）：

```json
{"qid":"q001","query":"HAK 180 烫金机额定电压是多少","item_name":"HAK 180 烫金机",
 "relevant_chunk_ids":["c_101"],"grade":{"c_101":2},"tags":["参数查询"]}
```

- `grade`：分级相关性（2=高度相关 / 1=部分相关 / 0=不相关），**nDCG@10 必需**（二值无法计算）。
- `tags`：query 类型（参数查询 / 操作步骤 / 故障排查 / 多跳），用于分桶分析——
  面试能说"HyDE 只在 X 类 query 有增益"，比一个总分有说服力。
- 当前 `relevant_chunk_ids` / `grade` 为**假设性标注**（构造样例），待真实文档入库后需按实际
  chunk_id 重新标注。

## run_eval 用法

```bash
python eval/run_eval.py --out eval/runs/ [--limit N] [--golden eval/golden_queries.jsonl]
                        [--enable-hyde] [--skip-rerank]
```

- `--out`：评测输出根目录（默认 `eval/runs/`）。
- `--limit N`：只跑前 N 条（调试用）。
- `--enable-hyde`：启用 HyDE 召回路（需要 LLM 生成假设文档；默认关闭，纯检索无 LLM）。
- `--skip-rerank`：跳过 BGE 重排，直接使用 RRF 顺序（无 reranker 环境）。

**环境要求**：Milvus 可达且已运行 import_process 建立索引；BGE-M3 embedding 模型可用。
Milvus 不可达 / 集合不存在时脚本打印清晰错误并以非 0 退出（不吞异常）。

## 输出结构

```
eval/runs/{timestamp}_{config_hash}/
  ├── metrics.json        # 总分 + 按 tag 分桶（Recall@5/10, MRR, HitRate@5, nDCG@10）
  ├── per_query.jsonl     # 每条 query 的召回列表与命中情况
  └── badcases.md         # 未命中 / 低排名样本自动归档，供人工归因
```

`config_hash`：`retrieval.yaml + rerank.yaml + 集合名` 的哈希（M3 起读取 yaml 内容；
M2 退化为硬编码基线快照）——每次评测可追溯到当时配置，这就是实验管理（§7.5）。

## 实验索引表（空模板，实测后填写，禁止预填）

| run_id | config_hash | 变更点 | Recall@5 | nDCG@10 | 结论 |
|---|---|---|---|---|---|
| baseline |  | 默认配置（product_manual_v1_bge_m3，EMBEDDING_MODE=api） | 0.0 | 0.0 | 2026-08-06 |
| api-mode-retrieve |  | 默认配置，EMBEDDING_MODE=api / RERANK_MODE=api，50 用户并发 10min | 0.0 | 0.0 | 2026-08-06 |
| （待填） |  | rrf.weights hyde 1.0→0.6 |  |  |  |
| （待填） |  | dynamic_topk gap_ratio 0.25→0.35 |  |  |  |
| （待填） |  | hybrid dense 0.8→0.7 |  |  |  |

> 结论栏应写"是否显著优于 baseline / 是否值得落地"，并附 badcase 归因。
> 单 tag 桶样本可能 <15，仅供定性参考（方案 §13）。
>
> **诚实声明**：`golden_queries.jsonl` 为构造 / 脱敏样例（非线上日志），`relevant_chunk_ids` 为假设性标注（`c_101` 等），未按真实 chunk_id 重标， Recall@5 / nDCG@10 全 0 属预期。真实文档入库后需按实际 chunk_id 重新标注（eval/README §golden 数据集格式）。

## 与索引 registry 的闭环（§5.4）

- import 成功后 `node_import_milvus` 自动登记一条 registry 记录（构建配置事实）。
- 评测跑完 `run_eval.py` 把得分回填到对应集合条目（recall@5 / mrr / ndcg@10 / run_id）。
- 这样形成「索引版本 ↔ 构建配置 ↔ 检索得分」可追溯闭环，换 embedding 模型或切分策略后
  能直接对比新旧索引的评测差异。
