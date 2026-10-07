# 检索评测体系（M2，方案 §6）

本目录提供知识库检索链路的质量评测闭环：golden 数据集 → 逐条检索 → 指标计算 →
badcase 归档 → 索引 registry 得分回填。

> **诚实声明**：`golden_queries.jsonl` 为**构造 / 脱敏样例，非线上日志**（方案 §13 口径）。
> 所有指标数字必须实测后填写，本仓库禁止预填任何评测结果。

## 目录结构

| 文件 | 说明 |
|---|---|
| `golden_queries.jsonl` | 脱敏 golden query 数据集（56 条，4 类 tag，含 grade 分级） |
| `metrics.py` | 检索指标纯函数 shim（重导出 `agent_core.metrics.retrieval`） |
| `run_eval.py` | 评测 CLI：逐条跑检索链路（召回→RRF→重排，不含 LLM 生成）并输出指标 |
| `gen_golden.py` | **真实语料自举 golden**：读真实 chunk → LLM 合成 query → 回注真实 chunk_id + 难负例/近似重复/expected_source 标注（打破 Recall 饱和） |
| `source_adapter.py` | **多路召回插拔契约**：同构 id 源进 RRF / 异构内容源仅 rerank 合流 + canonical id 别名 sidecar |
| `run_route_ablation.py` | 路线消融升级版：LOO/add-one 数据源贡献矩阵（per-bucket + bootstrap 显著性）+ 参数敏感度扫描 + web@rerank 干扰 |
| `scorers.py` | **端到端打分协议**：`Scorer.score(query,context,answer,reference)` + HeuristicScorer / LLMJudgeScorer（纯函数 + 惰性 LLM） |
| `run_e2e_eval.py` | **端到端运行器**：检索→组上下文→LLM 生成→答案质量打分，检索层/生成层**归因分离**报表 |
| `meta_eval_judge.py` | **judge 选型 meta-eval**（有界 spike、不进生产）：自研 judge vs RAGAS/DeepEval 四维对比 → `judge_selection.md` |
| `compare_runs.py` | **回归门禁**：baseline vs candidate 逐指标配对 bootstrap 比较，显著回归非 0 退出 |
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

## 路线消融（RRF 混合排名 vs 单路召回）

区别于本目录的 **TopK 消融**（`run_ablation.py`：fixed_k=3/5/10 vs dynamic，只切「注入前截断深度」），
**路线消融**切的是「哪些召回路参与融合」与「embedding 内 dense/sparse 配比」，回答两个问题：

- **层 1（RRF 通道层）**：`emb_only / hyde_only / kg_only / rrf_emb_hyde / rrf_all`（+ 可选 `rrf_all+rerank`）
  —— 加权 RRF 融合比最好的单路强多少（默认不重排，隔离「融合」本身效果）。
- **层 2（embedding 内层）**：`dense_only / sparse_only / dense+sparse` + `ranker_weights` 扫描
  —— dense+sparse 混合比单向量强多少，并找最优配比（供回填 `retrieval.yaml`）。

指标同为 recall@5 / recall@10 / mrr / hit_rate@5 / ndcg@10（`agent_core.metrics.retrieval`）。

### 前置：合成语料 seed + 真实 chunk_id 重标注（必跑）

`golden_queries.jsonl` 的 `relevant_chunk_ids` 是假设标注（`c_101` 等），而 Milvus `chunk_id` 是自增主键——
不重标注则指标恒为 0。`seed_synthetic_corpus.py` 把 golden 里出现的每个唯一 `chunk_key` 造一条合成 chunk
（content 内嵌引用它的 query 文本），走**线上同一 `node_import_milvus` 节点**写入**专用集合
`eval_rag_routes`**（与生产集合隔离，避免按 item_name 幂等清理误删真实语料），再用回填的真实
`chunk_id` 重写 `golden_queries.labeled.jsonl`（保留原件）。

```bash
# 只核对语料构造、不连 Milvus
python eval/seed_synthetic_corpus.py --dry-run
# 正式入库 + 重标注（需 Milvus + embedding 可用）
python eval/seed_synthetic_corpus.py
python eval/run_route_ablation.py --golden eval/golden_queries.labeled.jsonl \
    [--limit N] [--max-results 10] [--no-hyde] [--no-kg] [--with-rerank] [--no-layer2]
```

输出 `eval/runs/{ts}_{config_hash}/route_ablation.md`（层1+层2 两张表 + Δ(fusion−best_single) +
**证据包小节**：词法最优配比 / 融合是否优于单路，供后续「检索原语统一」重构方案引用）+
`route_per_query.jsonl`。

### 诚实口径（脚本会在报告里重申）

- 某路缺依赖 / 无候选（KG 未接 Neo4j、HyDE 无 LLM key）→ 该配置标注 **skipped**，不预填数字。
- **KG 命名空间**：`kg_chunks` 的 chunk_id 为 `kg::{item}::{name}`，与 Milvus 真实 chunk_id 不同源；
  未做 KG 侧独立标注/seed 时 kg 相关召回结构性为 0（非缺陷）。
- **EMBEDDING_MODE=api** 时 sparse 为本地 TF 词频（无 IDF / 非 learned sparse），层 2 sparse 语义偏移；
  要评 learned sparse / BM25 须用 local 模式或引入 Milvus v2.4+ 原生 BM25 Function。
- 合成集样本小（单桶可能 <15），仅供定性方向判断，非线上指标。

## 路线消融实跑结论（2026-09-29，真实服务器环境，KG 路已跑通）

在真实基础设施端到端跑通并出真实数字（非预填）。**KG 路补 Neo4j seed 后可计分**的完整 run：
`run_id=20260929_022137_fba10adc2c`，产物见 `runs/20260929_022137_fba10adc2c/route_ablation.md`
（含 `kg_only` 正向数字）。

- **环境**：测试服务器（Milvus + Neo4j 已由 docker-compose 起）；一次性大内存容器跑 `EMBEDDING_MODE=local`
  （BGE-M3 权重本地加载，dense_dim=1024，6G 内存足够），`RERANK_MODE=api`，集合 `eval_rag_routes`，
  KG 路 `pip install neo4j`（驱动 6.3.1）连 `bolt://neo4j:7687`。
- **管线打通验证**：seed 56 golden → 43 合成 chunk 入库 + 真实 chunk_id 重标注 + **43 Neo4j Entity 写入** → 全路 **Recall@10=1.0**。
  证明「指标恒为 0」的前置（真实 chunk_id 标注）已消除，评测可计分。

### 两处「部署镜像落后于工作树」的处置（均只动 eval 脚本，未碰线上检索链路）

1. **缺 `knowledge_service.conf.config_hash`**：旧镜像无该较新模块。`seed/runner` 对 `compute_config_hash`
   做 `try/except ModuleNotFoundError` 降级到 `eval/ablation.py::fallback_config_hash`（基于关键 env 的 sha256 短哈希，
   仅用于 tracing 归因标签 / run_id 目录名，**不参与任何检索数值**）。故本次 `config_hash=fba10adc2c` 为降级值。
2. **旧集合 schema 未 enable dynamic field**：seed 原打算把自定义 `chunk_key` 作为动态字段写入以做映射，被 `insert`
   拒（`unexpected field 'chunk_key' ... without enabling dynamic field`）。改为**不写自定义字段**，
   靠 `node_import_milvus.step_4` 的 **chunk_id 按列表顺序回填** 事实，用 `zip(corpus, imported)` 关联 `chunk_key→chunk_id`。

### 关键结论（层1/层2，合成集方向性判断）

- **层1 融合未超最好单路**：`rrf_all` nDCG@10=0.9683 < `kg_only`=0.9867（Δ = **−0.0184**，最好单路为 KG）。
  小合成集上单路已近满召回（Recall@10 全 1.0），加权 RRF 融合的正增益未被证明；KG 单路平均仅返 1.52 条即达
  最高 nDCG（合成语料 content 内嵌原 query，KG 的 `CONTAINS` 近似精确词法命中 → 高精度少返回），
  提示「融合更多路」在本数据规模下不必然更好。
- **层2 词法侧略优**：`sparse_only`(BGE-M3 learned sparse) nDCG@10=0.9709 > `dense_only`=0.968；
  默认档 `dense+sparse`(0.8/0.2)=0.967。各配比差异均 <0.005，处于 56 条样本的噪声区间，
  不足以据此改 `retrieval.yaml`，仅支持「learned sparse 值得保留」的方向判断。

### KG 路跑通：Neo4j seed + canonical id 别名（本轮新增，只动 eval）

上一轮 KG 因镜像缺 `neo4j` 驱动且合成语料未进 Neo4j 而标 skipped。本轮真正打通：

1. **装驱动 + Neo4j seed**：一次性容器 `pip install neo4j`；seed 新增 `--with-kg`，把每个 chunk_key 写为
   Neo4j `Entity`（`item_name`=**原始** golden 名以配合 `query_kg` 精确 `IN`、`name`=`evalsyn::{chunk_key}`、
   `content`=与向量路同一文本），按 `eval_tag=route_ablation` 幂等 `DETACH DELETE` 隔离，**不触碰生产其它实体**。
2. **canonical id 别名**：`query_kg` 合成 `kg::{item}::{name}` 与 Milvus 整数主键不同源。seed 产出 sidecar
   `kg_id_map.json`（`kg::{item_raw}::{evalsyn::ck}` → canonical Milvus chunk_id）；runner 用 `_alias_kg_ids` 把
   KG 命中归一到 canonical，使 KG 与 emb/hyde 在同一 relevant 基准上公平比较（单测 `test_kg_alias_roundtrip_*` 锁死“别名键==query_kg 合成键”）。
3. **nDCG>1 修复（去重）**：别名后同一底层 chunk 会以「向量路 `id`(int) + KG 路 `chunk_id`(str)」两个不同 RRF key
   各出现一次（int/str 键不等使线上 RRF 无法合并）→ DCG 双计 gain → nDCG 算出 1.3434 的**测量假象**。runner 加
   `_dedupe_docs_by_id` 按 str 归一 id 对融合结果去重（保留首次/最高名次）后再算指标 → `rrf_all` 回到 0.9683（合法）、
   平均返回从虚高的 10.0 降为真实的 8.48。单测 `test_ndcg_never_exceeds_one_after_dedupe` 固定此不变量。

> 诚实边界：上述 3 步均只改 eval 脚本，**未改任何线上检索/融合代码**；`kg_only=0.9867` 是合成集上的方向性数字
> （content 内嵌 query 使 KG 词法命中偏乐观），非线上真实图谱质量；真实图谱评测需另一套独立语料与标注。

---

## 可持续评测体系（M3：真实 golden + 数据源贡献归因 + 端到端 + 回归门禁）

上面「路线消融」解决了「融合 vs 单路」，但暴露三个根因缺陷，本节逐一对症：

1. **合成集 Recall 恒 = 1.0**（词法近似精确命中）——只能比排序、比不了「某数据源该不该加」。
2. **无端到端答案质量层**——检索指标到「召回对不对」为止，没到「答案好不好」。
3. **无回归门禁与数据源贡献归因**——改参数/加源后没有 baseline-vs-candidate + 显著性 + 边际贡献机制。

> 全链路红线：只动 eval 侧，**不改任何线上检索/融合/rerank 代码**；指标单实现扩到 `agent_core.metrics.retrieval`；
> 缺依赖诚实标 skipped / 清晰报错，**绝不预填或伪造数字**。

### Phase A — 真实语料自举 golden（打破 Recall 饱和）

`gen_golden.py`（仅 eval/开发用，不进生产依赖）：读真实 chunk → LLM 基于真实文本合成 query → 回注**真实** `chunk_id`
→ 输出 `golden_queries.real.jsonl`（每条附 `reference_answer`）。区别于玩具集的关键标注：

- `hard_negatives`：语义相近但**不该命中**的 chunk，强制检索要能区分（打破 Recall=1.0 饱和）。
- `near_dupes`：跨 chunk 近似重复段，检验去重与排序稳定性。
- `expected_source`（per-query）：标注该 query 本应由哪条通道答，用于数据源贡献归因。
- `grade` 分级相关性保留（nDCG 必需）。

```bash
python eval/gen_golden.py --dry-run          # 不连 Milvus，仅演示纯函数标注逻辑（自洽样例）
python eval/gen_golden.py --collection <真实集合> --target-count 120 --audit 30   # 真实自举 + 抽检表
```

前置不满足（真实集合空/不足）则清晰报错终止，**不回退内嵌-query 玩具语料**。产出 `golden_queries.real.jsonl` + `golden_audit.md`（人工抽检表）。

### Phase B — 可扩展多路召回 & 数据源贡献归因

**通道插拔契约**（`source_adapter.py`，回答「新增数据源怎么接进来评测」）——每个数据源声明合流类别：

- **同构 id 源**（可归一 canonical chunk_id，如 KG）：进 RRF；非 Milvus id 走 `<source>_id_map.json` **id 别名 sidecar**（泛化自 `kg_id_map.json`）归一后参与，沿用 `_dedupe_docs_by_id` 防 nDCG>1。
- **异构内容源**（无 canonical id，如 web）：**不进 RRF**，只在 rerank 阶段合流；用 rerank 后最终序 + 本地相关块干扰度度量，不假装能给 web 算 recall。

**边际贡献归因**（`run_route_ablation.py --with-contrib`，回答「这路到底帮没帮上忙」），per-bucket（tag × expected_source）：

- **Leave-one-out**：基线 `rrf_all` 逐一移除某路，Δ(nDCG@10/Recall) = 该路净贡献（负=拖后腿，≈0=冗余）。
- **Add-one-in**：从 `emb_only` 起逐路叠加，看每加一路的增量。
- 融合 vs 最好单路 `Δ = rrf_all − max(single)` 保留。配对 bootstrap 95% CI 判显著（CI 含 0 → 噪声/冗余，不渲染「更优」）。

**参数敏感度扫描**（`--param-scan`）：`hybrid.dense/sparse_weight`、`rrf.weights.*`、`rrf.k`、`dynamic_topk.gap_ratio` 单因子扫描，输出最优档 + 敏感度曲线（供回填 `retrieval.yaml`，非拍脑袋）。

```bash
python eval/run_route_ablation.py --golden eval/golden_queries.real.jsonl --with-contrib --param-scan \
    [--id-map SOURCE=PATH] [--web-snapshot eval/web_snapshot.json] [--with-rerank]
```

### Phase C — 端到端答案质量（含 judge 选型 meta-eval）

**C1 端到端运行器**（`run_e2e_eval.py`）：完整链路 检索 → 组上下文 → LLM 生成 → 答案质量打分，
**检索层与生成层分离出报表**（归因分离：检索差 ≠ 生成差）。打分维度 faithfulness / relevance / correctness（值域 0..1）。
无 LLM key → 生成层整体标 skipped（检索层仍实测），不拿空答案凑分。

```bash
python eval/run_e2e_eval.py --golden eval/golden_queries.real.jsonl [--scorer judge|heuristic] \
    [--limit N] [--enable-hyde] [--skip-rerank] [--max-context-chars 6000]
# 产物：runs/{ts}_{hash}/e2e_report.md + e2e_per_query.jsonl + e2e_metrics.json
```

打分逻辑抽象成 `scorer` 协议（`scorers.py`），便于 C2 三方替换实现。

**C2 judge 选型 meta-eval**（`meta_eval_judge.py`，有界 spike、**不进生产**）：把「端到端质量框架选型」做成有裁决基准、
有判据的对比决策（调和 AGENTS.md「引入 RAGAS/DeepEval」vs spec.md「自研」的冲突）。四维对比（主判据=与人工一致性）：
① 一致性（分箱 Cohen kappa + 原值 Spearman）② 成本（token/延迟）③ 依赖足迹（额外第三方包数）④ 可解释（理由可否复核）。

```bash
python eval/meta_eval_judge.py --from-e2e eval/runs/<run>/e2e_per_query.jsonl --sample 30   # 出人工待标注模板
# 人工填 human.faithfulness/correctness(0/1/2) 后：
python eval/meta_eval_judge.py --adjudication eval/adjudication.jsonl --candidates self,ragas,deepeval
# 产物：judge_selection.md（决策备忘）
```

决策规则：一致性显著更高且成本可接受者胜出；差异 ≤0.05 落噪声内 → 按 spec.md 取**自研**（可控、零长期依赖）。
RAGAS/DeepEval 默认未装 → 标 ❌ available=False 不出假数字；**未胜出方不进 pyproject 生产依赖**。

### Phase D — 回归门禁与实验台账

**baseline vs candidate + 显著性**（`compare_runs.py`）：两次 run 的同一批 query 按 qid 对齐，逐指标配对 bootstrap CI，
用「CI 是否含 0」判真回归 vs 样本噪声。核心指标（默认 `ndcg@10 / faithfulness / correctness`）显著回归 → `--fail-on-regression` 非 0 退出。

```bash
python eval/compare_runs.py --baseline eval/runs/<tsA_hashA>/ --candidate eval/runs/<tsB_hashB>/ --fail-on-regression
```

**门禁分层**（根 `Makefile`，对齐验证策略，**不进 hermetic `make ci`**，因依赖真实外部服务）：

| 目标 | 阶段 | 依赖 | 缺环境行为 |
|---|---|---|---|
| `make eval-rag-retrieval` | Phase B（gen_golden + ablation --with-contrib --param-scan） | Milvus(+可选 Neo4j/rerank) | 脚本清晰报错 return 1 |
| `make eval-rag-e2e` | Phase C（run_e2e_eval --scorer judge） | LLM | 生成层诚实 skipped |
| `make eval-rag-gate` | Phase D（compare_runs --fail-on-regression） | 两次 run 产物 | 缺 BASELINE/CANDIDATE → 用法提示 exit 2 |

```bash
BASELINE=eval/runs/<tsA_hashA> CANDIDATE=eval/runs/<tsB_hashB> make eval-rag-gate
```

### 端到端 / 回归门禁 实验索引表（空模板，实测后填写，禁止预填）

> 本机（无 Milvus/Neo4j/LLM）只能跑 hermetic 单测 + `--dry-run`；下表数字须在真实服务器环境实测后回填。

| run_id | config_hash | 变更点 | faithfulness | relevance | correctness | 检索 ndcg@10 | 对 baseline 判定 |
|---|---|---|---|---|---|---|---|
| （待填·服务器） |  | 真实自举 golden 基线（judge） |  |  |  |  | — |
| （待填·服务器） |  | 新增数据源 X（add-one-in 后） |  |  |  |  | 显著改进/噪声/回归 |
| （待填·服务器） |  | rrf.k 40→60 参数扫描回填 |  |  |  |  |  |

### 本地可验证 vs 服务器实跑边界（诚实）

- **本地全绿**（无外部依赖）：`gen_golden --dry-run`、`source_adapter` / `ablation` / `analysis` / `scorers` / `run_e2e_eval` 纯函数 /
  `meta_eval_judge` / `compare_runs` 单测；`uv run --with ruff ruff check eval/`；两个 runner + meta-eval + compare 的 `--help`。
- **服务器盲区**（须真实基础设施）：真实语料自举 golden 的实际 Recall 去饱和验证、LOO/add-one 贡献矩阵实际数字、
  端到端 faithfulness/relevance/correctness 实际值、judge 选型四维一致性实际结论。**这些数字本仓库不预填**。

