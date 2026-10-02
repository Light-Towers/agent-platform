# RAG sparse 编码一致性修复方案（2026-09-29）

> 关联：RAG 可持续评测体系计划（层2 权重扫描疑点核查的后续修复）。本方案独立成文，不修改该计划文件。
> 状态：**已确认并已 126 容器实跑完成**（方向 A + 防呆门禁；执行期发现 §4「原地 upsert」前提被 auto_id 证伪，改走路径 B，详见 §9 执行记录）。

## 1. 问题与根因（实测坐实）

- 现象：路线消融层2 五档 `ranker_weights`（dense_only/w_0.8_0.2/w_0.5_0.5/w_0.2_0.8/sparse_only）中，`w_0.2_0.8` 与 `dense_only` 在 60/60 query 上 id 列表逐位相同；融合 distance 恒 = `w_dense × dense_score`，稀疏项贡献恒 0。
- 根因（126 容器直连真实 Milvus `product_manual_v1_bge_m3`）：
  - 集合以 `EMBEDDING_MODE=api` 导入（eval/README.md L72 记 2026-08-06），库内 sparse key = `sparse_vectorizer` 的 **md5 哈希 id**（8–10 位，如 `24113990`）。
  - 评测以 `EMBEDDING_MODE=local` 查询，query sparse key = **BGE-M3 词表 token id**（小整数，如 `6`/`49074`）。
  - 两 id 空间不相交 → 稀疏路 IP 恒 0 → 混合检索实际退化为纯 dense。
- 深层设计缺陷：集合名 `..._bge_m3` 承诺稀疏侧为 BGE-M3，实为 md5-TF；且无任何机制保证「导入编码 == 查询编码」，错配静默发生。

## 2. 目标

1. 让 benchmark 集合 `product_manual_v1_bge_m3` 的稀疏侧与其名称/查询侧一致（统一为 **local BGE-M3 learned sparse**）。
2. 恢复层2 权重扫描有效性，复跑得真实配比结论。
3. 加**运行时防呆门禁**：导入/查询编码不一致时**显式报错**，杜绝再次静默退化。

## 3. 影响面

| 面 | 影响 | 处置 |
|----|------|------|
| benchmark 数据 | 60 条 chunk 的 sparse 需重算为 BGE-M3 | **原地 upsert 仅重写 sparse**，保留 chunk_id + dense_vector |
| golden 标注 | `golden_queries.real.jsonl` 依赖真实 chunk_id | 因 chunk_id 不变 → **golden 无需重生成** |
| 层2 消融/ e2e 数字 | sparse 生效后排序/指标会变 | 复跑刷新，旧报告标注作废 |
| 线上查询节点 | 混合检索此前对该集合实际 dense-only | 修复后 sparse 恢复；防呆门禁接入点见 §5 |
| 依赖方向红线 | 改动限 knowledge-service（eval + 该 app 节点/工具） | 不引入跨包反向依赖 |

## 4. 迁移策略（推荐：原地重算 sparse，非整集重导）

> ⚠️ **实测修正（2026-09-29）**：本节「原地 upsert 保留 chunk_id」的前提被证伪——`node_import_milvus` schema 为 `auto_id=True` 主键，Milvus 对 auto_id 集合的 `upsert` 语义是**删原行 + 插入并重新自增主键**，无法把向量写回指定 PK（实测原 PK `...38472` 消失、新 PK `...38664` 出现）。故实际采用**路径 B**：全量 delete + 以 pristine 备份为源重插（生成新 PK）+ 按 old→new 映射重写 `golden_queries.real.jsonl` 的 chunk_id 引用。落地过程与最终数字见 **§9**。以下原文保留作为决策历史。

**为何原地**：`node_import_milvus` schema 为 `auto_id=True` 主键 + `content` 可读；整集重导会重排 chunk_id → golden 全崩、需重跑 Phase A 自举。原地 upsert 保留主键与 dense，只把 sparse 换成 local BGE-M3 产物，风险最小。

步骤（126 `rageval-eval` 容器，`EMBEDDING_MODE=local`）：
1. 备份集合快照（导出 chunk_id/content/dense/sparse 到本地 tgz，可回滚）。
2. 分页 query 全量 chunk（chunk_id, content, dense_vector）。
3. 对每条 `content` 调 `generate_embeddings([content])` 取 local BGE-M3 sparse（**不改 dense**）。
4. `client.upsert` 原 chunk_id + 原 dense_vector + 新 sparse_vector 回写。
5. 校验：单条 self-retrieval canary 通过（§5）；抽样单路 sparse 搜索返回非空、distance>0。
6. 复跑层2 消融 + e2e → 刷新报告；旧层2 数字标注"作废（sparse 编码错配期）"。

> 新增脚本 `eval/reindex_sparse_local.py`（一次性运维工具，纯调既有 `generate_embeddings`/`get_milvus_client`，不改线上入库/查询逻辑）。

## 5. 防呆门禁：self-retrieval 编码一致性 canary（单一实现 + 全局装配）

- **单一实现**：`assert_sparse_encoding_consistent(client, collection, probe_fn)`（放 knowledge_service 工具层）：
  1. query 集合取任意 1 条 chunk 的 `content` + `chunk_id`；
  2. 用**当前模式** `generate_embeddings([content])` 生成 sparse；
  3. 稀疏单路搜索该 sparse，断言命中集合**同一 chunk_id**（同编码自我检索必最高分命中）；
  4. 未命中 → 抛 `SparseEncodingMismatchError`（"库内 sparse 与当前查询编码不一致"）。
- **全局装配**：查询链路启动/首次调用处执行一次（结果按 collection 缓存，避免每请求开销）；评测 runner 入口同样调用，fail-fast。
- **优势**：不依赖集合元数据/动态字段（部署镜像建的集合未必 enable dynamic field，§seed 注释），直接验证失败症状本身（id 空间是否对齐），对"未来任何编码漂移"都拦截。

## 6. 验收标准

1. 修复后单条 query 稀疏单路搜索返回**非空、distance>0**（此前恒空）。
2. 层2 `w_0.2_0.8` 与 `dense_only` 至少在部分 query 上 id 排序**出现差异**（权重真正生效）；`sparse_only` distance 不再全 0。
3. self-retrieval canary 在 local 查询 + local 重算集合上**通过**；人为切 api 查询该集合时**报错**（防呆验证）。
4. golden 60 条 chunk_id 不变（`git diff`/校验和确认 `golden_queries.real.jsonl` 未漂移）。
5. 本地 `ruff check eval/ knowledge_service/` 通过 + 受影响单测（`uv run pytest applications/knowledge-service/tests -q`）无回退。
6. e2e/消融数字刷新后如实入档，旧层2 结论标注作废。

## 7. 风险与回退

- upsert 失败/中途中断 → §4 步骤1 的快照可整集回滚。
- 线上若有实例正以 api 查询此集合：修复转 local 后，该实例需同步切 local 或触发 canary 报错——部署需统一 `EMBEDDING_MODE`（记入运维文档）。
- 不动 `node_search_embedding` 检索逻辑本体；仅加可选启动校验。

## 8. 不做（边界）

- 不改 config 默认（保持 local）。
- 不引入外部 BM25/SPLADE 框架（符合"框架选型规则"，local BGE-M3 learned sparse 已足）。
- 不把 md5-TF 与 BGE-M3 两种稀疏强行兼容映射（两套 id 空间无稳定映射，徒增复杂度）。

## 9. 执行记录与方案修正（2026-09-29 126 容器实跑）

### 9.1 auto_id 障碍（推翻 §4「原地 upsert」）
- 修复前 self-retrieval canary（local 查询真实集合）：**FAIL**，稀疏单路搜 top10=`[]` → 坐实 id 空间错配 + 门禁有效。
- `--one` 单行预演：auto_id=True 集合 `upsert` = 删原行 + 插新自增 PK（原 `...38472` 消失、新 `...38664` 现，总行数不变）→ **无法原地保 chunk_id**，§3/§4「golden 无需重生成」前提失效。

### 9.2 路径 B（用户选定）
保留 auto_id，**全量 delete + 以 pristine 备份为源重插 + 按内容 remap golden**：
1. `reindex_sparse_local.py --dry-run` 分页 fetch（`query_iterator`，规避单次 query 窗口 ≤16384）备份 87 行（dense 原样保留，仅 local BGE-M3 重算 sparse）。
2. `--from-backup <pristine> --yes`：delete-all（`filter="chunk_id >= 0"`）+ 分批 insert（auto_id 生成新 PK）→ **canary PASS**、单路 sparse 探针非空（top3 distance 1.54/0.58/0.57）→ 产出 `reindex_pk_map_*.json`（87 条 old→new）。
3. `remap_golden_ids.py --strict`：消费映射重写 `golden_queries.real.jsonl` 的 relevant/grade/hard_negative/near_duplicate 四类 id 引用（60 query / 468 引用 / 0 未映射），写前落 `.preremap.bak`（g001 `...552`→`...748`）。remap 范围仅 benchmark 真实集；`kg_id_map.json`/`labeled.jsonl` 属合成集 `eval_rag_routes`，本次不动。

### 9.3 修复效果（层2 消融复跑，`--golden real`）
各权重档**不再雷同**（原疑点 `w_0.2_0.8` ≡ `dense_only` 已消除，稀疏路真正参与融合）：

| 档位 | 修复后 ndcg | 说明 |
|---|---|---|
| dense_only | 0.8308 | 基线 |
| sparse_only | 0.8563 | 稀疏路独立有效（此前恒 0） |
| w_0.5_0.5 | 0.8366 | |
| w_0.2_0.8 | **0.8727** | 原「与 dense_only 逐位相同」疑点，现最优 → 稀疏贡献被证实 |

### 9.4 e2e 复跑（real / judge / hyde off / rerank on / 60 条）
| 指标 | 修复前基线 | 修复后 | Δ |
|---|---|---|---|
| recall@10 | 0.9167 | 0.9333 | ↑ |
| mrr | 0.8181 | 0.8236 | ↑ |
| ndcg@10 | 0.8431 | 0.8514 | ↑ |
| faithfulness / relevance / correctness | — | 0.925 / 0.975 / 0.90（n=60） | 生成层健康 |

检索层三项小幅↑（rerank 主导故增幅有限，方向与稀疏修复生效一致）；产物入 `eval/runs_server/`。

### 9.5 健壮性补记（e2e 复跑期发现）
外部 SiliconFlow API 偶发**无响应挂起**（非异常，常规 try/except 兜不住，整轮卡死）。给 `run_e2e_eval.py` 加 `--llm-timeout`（默认 90s）：`_call_with_timeout` 守护线程施加墙钟超时，超时按脚本既有契约把该条对应层标 skipped 继续。**改动限 eval harness，不碰生产 LLM 客户端 / 依赖方向**；本次全量 60 条 0 超时完成。

### 9.6 验收对照（对 §6）
- ① 稀疏单路非空：✅；② 层2 各档出现差异：✅（`w_0.2_0.8`≠`dense_only`）；③ canary local 通过：✅；④ **golden chunk_id 变更**（auto_id 重插所致）：以 old→new 映射 + 内容不变 remap 保证审计有效性（替代原「id 不变」条款）；⑤ 本地 ruff + 全 unit 344 passed：✅；⑥ 数字如实入档：✅。
