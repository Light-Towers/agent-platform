# Plan：中英混排检索分词改造（2026-11-25）

> 状态：**草案，待批准（D1，可逆、中影响）**。批准前不改代码。
> 详细需求与方案见 SDD 三件套：`docs/specs/cn_en_tok/spec.md`、`docs/specs/cn_en_tok/design.md`、`docs/specs/cn_en_tok/tasks.md`。

## 1. 背景与问题

当前三条检索链路的分词都不是真正的分词器：

| 链路 | 现状 | 证据 |
|---|---|---|
| knowledge-service 词法路 | 英文正则 + 中文重叠 bigram；api 模式下本地 md5-TF 稀疏向量 | `applications/knowledge-service/knowledge_service/lm/sparse_vectorizer.py:28-91` |
| agent_server 降级路 | 英文按词 + 中文 bigram | `applications/agent_server/rag/store.py:37-46` |
| nl2sql 取值召回 | 默认整串 2 字滑窗；jieba 为可选，缺包时**告警一次后降级 bigram（非静默）** | `applications/nl2sql-service/nl2sql_service/tokenizer.py:23-49` |

后果：领域词边界靠猜、型号 / 缩写召回不稳；导入端与查询端稀疏编码不一致会让稀疏路静默失效（已记录在 `docs/plans/plan-rag-sparse-encoding-consistency-2026-09-29.md`）。

## 2. 目标

1. 主检索链路词法路由 Milvus 内置 BM25 Function + jieba analyzer + 领域词典；**dense 路不变**，多路 RRF 与 rerank 顺序不变。
2. agent_server 降级路使用同一分词能力（jieba + 领域词典），保持隔离谓词不变。
3. nl2sql 默认改 jieba，缺包告警不静默，存量行按 `tokenizer` 标记重建。
4. 应用侧手写正则分词实现分阶段退役；分词配置与词典版本入库可复算。

**非目标**：不引入 Elasticsearch；不训练 SPLADE；不改 dense 模型；不改问答生成。

## 3. 关键决策

1. **本批不升级 Milvus 服务端，保持 v2.5.10**。所需能力（内置 BM25 Function、jieba tokenizer、自定义词典）在 2.5.x 已具备；`multi_analyzer_params` / `run_analyzer` 属 2.5.11+ 的便利能力，本方案采用单一 analyzer，不依赖它们，改由"建临时集合实测检索 + 配置复核"验证。现网 K8s 的引擎大版本升级（含存量 `platform_doc_v3_bge_m3` 兼容与服务端级回退）**另立工单 / ADR**，不搭本批车（见 §7）。
2. **采用单一 jieba analyzer，不用 language_identifier 自动路由**。后者对整段文本判一种语言再选一个分析器，短中英混排查询可能丢掉英文词项。官方示例证明 jieba 可在同一串上保英文整词并切中文词典词。
3. **新集合版本 + 双写 / 重灌**，analyzer 是建集合时固定的，禁止原地改配置。
4. **英文不做词干化**：领域召回以精确匹配为主，语义相近由 dense 路承担；如确有需要另设双 analyzer 双 BM25 通道 + RRF。
5. **治本三层齐备（T14，必经）**：单一实现 = `agent-runtime` 共享分词模块（optional extra 声明 jieba，遵守单向依赖）；全局装配 = 唯一 `get_tokenizer()` 入口；强制门禁 = 行为等价门禁（三侧同一样本词项集合相等，口径与 Spec 5.3 一致）+ 架构不变量 lint（禁止服务内本地分词实现）。T14 不可裁剪，否则方案退化为"各服务自己接、靠人记得"的约定。

## 4. 迁移与验证

1. POC（在 v2.5.10 上）：验证词典注册方式与 ≥10,000 词条的加载 / 查询耗时、hybrid BM25 腿传原文、pymilvus 3.0.3 与该服务端的组合可用；分词输出用"临时集合实测检索"而非 `run_analyzer` 验证。
2. 建新集合 + 双写 / 重灌（建议 `platform_doc_v4_bm25_jieba`）。
3. A/B：领域 golden case 覆盖产品型号、黑话、缩写、中英混排、纯英文；按 semantic / lexical / fused 三路记录 recall@5 / recall@10。
4. 灰度切换，旧集合至少保留 14 个自然日且跨一次完整部署窗口；回退演练 ≤10 分钟（仅指集合 / 配置层回退，不含引擎面故障）。
5. 观测通过后分阶段删除旧正则实现。

## 5. 验收判据

- 混排样本分词断言 100% 通过，领域词不被拆碎。
- 领域词与混排问句的词法路 recall@K 不低于基线，融合后指标不低于基线。
- 租户 / 工作空间 / 知识库隔离用例全绿，软删除语义不变。
- 检索端到端 P95 ≤ 基线 110%，并按路记录词法召回耗时（当轮同环境复取基线）。
- 检索读点手写分词正则零命中（待退役件除外）。
- 行为等价门禁：三侧同一样本词项集合相等；注入不一致时 rc≠0（自证能咬）。
- 架构不变量 lint：真实代码 rc=0、合成违规 rc≠0。
- `scripts/check_doc_sync.py` 与 lint rc=0。

## 6. 证据与参考

- Milvus 全文检索 / BM25 Function：`https://milvus.io/docs/v2.6.x/full-text-search.md`
- Milvus hybrid search（dense + 引擎 BM25）：`https://milvus.io/docs/v2.6.x/multi-vector-search.md`
- jieba tokenizer 与自定义词典：`https://milvus.io/docs/v2.5.x/jieba-tokenizer.md`
- language_identifier（2.5.15+，本方案不采用）：`https://milvus.io/docs/language-identifier.md`
- Milvus 3.0 破坏性变更：`https://milvus.io/docs/release_notes.md`
- 向量存储选型现状：`docs/adr/0009-vector-store-selection.md`

## 7. 范围边界

1. 本批只产出 Spec / Plan / Tasks 文档与 POC 验证；**不含产品代码改动**。代码实施以批准后的 `tasks.md` 为准，逐项带证据验收。
2. **不升级 Milvus 服务端**：本批只在现有 v2.5.10 上建新集合并验证。现网（K8s）引擎升级、存量 v3 集合在新引擎上的兼容验证、服务端级回退预案，另立工单 / ADR 后单独批准。
3. **不引入 ES / 不改 dense 模型 / 不做英文词干化**。
4. 方案件落位在版本控制内的 `docs/specs/cn_en_tok/`（`.*/` 规则会忽略 `.opencode/`，不得迁回）；批准前需完成 `git add` 并提交，使 `git ls-files` + `git cat-file -e HEAD:<path>` 可解析且 blob 非空。

## 8. 执行记录（按 `tasks.md` 工单）

- **T1 已完成（2026-11-25，分支 `docs/cn-en-tokenizer-2026-11-25`）**：新增 `docs/adr/0017-zh-en-tokenizer-bm25.md`（含 6 条复审触发条件）；四件方案件在 HEAD `bedf2ce1` 已逐件 `git cat-file -e` + 非空校验通过；`uv run python scripts/check_doc_sync.py` rc=0。
- **T2 受阻（2026-11-25，本机实测）**：`docker` 命令不存在；`127.0.0.1:19530` `connect_ex=10035`（拒连）；本地 `import jieba` 不可用（`pymilvus` 可用）。POC 所需引擎环境缺失，**不得用文档推断代替实测**，需用户提供可用 Milvus v2.5.10 环境（本地 Docker 或内网测试机）后再继续。
- **用户决策（2026-11-25）**：先做代码开发，环境验证顺延次日；据此放宽 T14 对 T2 的本地依赖，引擎侧行为等价留到 T2。
- **T14 本地部分完成**：`agent_runtime/retrieval_tokenizer.py` + 同源配置 JSON + 唯一 `get_tokenizer()`；两把入库门禁 `scripts/check_tokenizer_equivalence.py`（4 条样本 PASS，`--self-test` 注入错误期望 rc≠0）与 `scripts/lint_no_local_tokenizer.py`（真实代码 rc=0，注入违规 rc≠0）；已登记 Makefile / ARCHITECTURE.md / evidence README。`agent-runtime` 单测 5 passed。**引擎侧三路词项集合比对待 T2**。
- **T7 完成**：`agent_server/rag/store.py` 删除本地 `tokenize()`，改调 `get_tokenizer()`；`tests/memory/test_retrieval.py` 改断言为词典分词（不再断言字符 bigram，未删用例），`pytest tests/memory/test_retrieval.py -q` 4 passed。
- **T8 完成**：`Settings.tokenizer` / `app_config.yaml` 默认 `jieba`；nl2sql 生产调用点改 `get_tokenizer()`，`nl2sql_service/tokenizer.py` 退为测试兼容读件；`extract_keywords` 记录分词字典版本到可检索日志；`pytest tests/nl2sql_service -q` 219 passed/1 skipped，`pytest applications/nl2sql-service/tests -q` 235 passed/8 skipped。
- **本批门禁读数**：`ruff check .` rc=0；`lint_architecture.py` 中 P8/P15 与 `lint_public_mirror.py` P-4 共 8 项为本批之前的存量失败（未在本次改动面），新加两把门禁与 `lint_migration_refs.py` / `lint_graph_state_boundary.py` 均通过。

## 9. 第二批本地开发（引擎/DB 真机验证顺延）

- **T3**：词典版本与词条收敛到 `retrieval_tokenizer_config.json`；8,000 词告警 / 10,000 词拒绝在模块加载路径生效（当前词条数远低于阈值，仅代码就绪）。
- **T4**：`applications/knowledge-service/scripts/create_bm25_collection.py` 建新集合（BM25 Function + 同源 analyzer + `SPARSE_INVERTED_INDEX/BM25`），不改旧集合；**未执行**，等 T2 真机。
- **T5**：`retrieval.yaml` 新增 `lexical.mode=bm25_engine`；`milvus_utils.create_hybrid_search_requests` 按模式构造 BM25 原文腿；embedding / hyde 节点按模式选集合并传原文；商品名集合显式保留旧模式；导入侧新集合不写 `sparse_vector`。`test_bm25_search_requests.py` 3 passed；KS `tests/unit` 545 passed。
- **T6（阶段一/二）**：主链路读点不再消费本地 sparse；旧 canary 保留为历史读件，不进主门禁。**阶段三（删除旧文件）待真机观测周期后**。
- **T9**：迁移 `008_tokenizer_shadow.up.sql` / `.down.sql` + `rebuild_tokenizer_shadow.py`（默认 dry-run，`--apply` 事务内影子→正式原子切换）。**未在真库执行**。
- **T10**：`eval/golden_queries.zh_en_tokenizer.jsonl` 8 条领域样本（四类覆盖），`relevant_chunk_ids` 留空，明确标注空标注跑出 recall=0 是前置未就绪而非效果结论。
- **T11/T12/T13 的 A/B、灰度、回退与观测**：全部依赖 T2 真机环境，顺延；本批不伪造任何引擎或真库读数。
- **回归读数（2026-11-25）**：KS `tests/unit` 545 passed；`packages/agent-runtime/tests` 927 passed / 2 skipped；`tests/nl2sql_service` 219 passed / 1 skipped；`applications/nl2sql-service/tests` 235 passed / 8 skipped；`tests/governance/test_app_env_templates.py` 2 passed（新增 `MILVUS_BM25_SCHEMA_VERSION` / `BM25_CHUNKS_COLLECTION` 已补入 KS `.env.example` 后复跑）。
- **根套件存量失败（与本批改动面无关）**：`test_exception_echo_governance::test_p8_current_tree_has_zero_violations`（`health_router.py:112`）、`test_role_feature_gates::test_p15_current_tree_is_clean_and_really_judged`（`scripts/reimport_kb_to_milvus.py`）；另有 5 条 `tests/skill_live_check/*` 因 `192.168.100.9:80` ConnectTimeout 失败（环境依赖）。这些文件均不在本批改动面，不删用例、不放宽断言。

## 10. T2 POC 环境（2026-11-26 实取）

- 本机无 Docker、无 `127.0.0.1:19530`；`ssh BatchMode root@126`/`@241` 均 rc=0（126=ambari03，241=ambari01），`192.168.100.132:30001` 与 `192.168.100.9:80` TCP OPEN。
- K8s 存量 `milvus` 为 ClusterIP `10.111.204.66:19530`，Pod 有 66 次重启，不适合作 POC 靶机；其镜像为 `milvusdb/milvus:v2.5.10`。
- 按用户授权，在 126 上用本地已有镜像启动**隔离 POC 栈**（不碰 K8s 实例）：
  - 网络 `milvus-poc-net`；MinIO 容器 `milvus-poc-minio`（镜像从 241 以 `docker save`/`scp`/`docker load` 内网导入，外部 registry 不可达）；
  - Milvus 容器 `milvus-poc-zh-en`，`milvusdb/milvus:v2.5.10`，内嵌 etcd 配置 `etcd.use.embed=true` / `dir=/var/lib/etcd`；
  - 端口只绑 126 回环：`127.0.0.1:19531 -> 19530`、`127.0.0.1:9092 -> 9091`，不暴露内网；
  - 就绪证据：`curl -sf http://127.0.0.1:9092/healthz` 通过，日志 `Proxy successfully initialized and ready to serve!`。
- 本机连该端口需按需 `ssh -L 19530:127.0.0.1:19531`；本批尚未开该转发，也未在 POC 集合上执行任何建集合 / 写入 / 评测。

## 11. T2 POC 实测结论（2026-11-26）

按用户指示不开 SSH 隧道，把 POC 端口改绑到 126 内网 IP：`192.168.100.126:19531` / `:9092`，本机直连成功（`pymilvus 3.0.3` `list_collections()` rc=0）。

| 验证项 | 结果 | 证据 |
|---|---|---|
| pymilvus 3.0.3 + v2.5.10 兼容 | ✅ | `MilvusClient.list_collections()` rc=0 |
| 内置 BM25 Function + 简单 jieba 建集合 | ✅ | `poc_simple_jieba`、`poc_v4_bge_m3` 创建成功 |
| 自定义 analyzer 配置（`dict`/`mode`/`hmm`） | ❌ **不支持** | 报 `tokenizer name should be string param`；v2.5.10 只接受 `{"tokenizer":"jieba"}` |
| `run_analyzer` | ❌ **UNIMPLEMENTED** | RPC `unknown method RunAnalyzer`；改为样本检索代理验证 |
| 领域词 BM25 命中 | ✅ | `HAK-180 烫金机` / `烫金机` / `向量数据库` 均命中对应文档 |
| 我们自己的 hybrid 原文腿 | ✅ | `create_hybrid_search_requests(lexical_mode='bm25_engine')` + `hybrid_search(0.8/0.2)` 返回正确排序 |
| 索引预热瞬态 | 注意 | 刚插入后首次 hybrid 查询 0 命中，索引就绪后同样查询恢复正常；评测须等索引 ready |

**据此修正代码**：`milvus_analyzer_params()` 改为 `{"tokenizer":"jieba"}`，单测同步更新（5 passed）。领域词完整由 Python 共享 tokenizer 的 `add_word` 保障；引擎侧自定义词典需升级到 2.5.11+/2.6 后另案，本批不假装支持。≥10k 引擎侧注册项在该版本不适用。

## 12. A/B 机制验证结果（2026-11-26，未通过切换判据）

- 量具：`applications/knowledge-service/eval/run_tokenizer_ab_poc.py`，报告 `eval/runs/tokenizer_ab_poc.json`，12 条样本（8 条领域词 + 4 条口语改写难样本）。
- **诚实边界（2026-11-26 二次重跑已更新）**：先用 bge-small（512 维）跑机制验证；拿到硅基流动 key 后，以 `EMBEDDING_MODE=api` + `BAAI/bge-m3`（**1024 维**）重跑，报告 `dim=1024`、disclaimer 记录真实模型。旧路 sparse 仍是 md5/TF 代理（非 BGE-M3 原生 sparse），语料仍是合成样本 ⇒ 这是**真实稠密模型下的机制/相对排序观察**，不是真实业务语料的线上质量结论。key 已写入根与 KS 的 gitignored `.env`，不入库。
- 读数（12 条）：

| 路 | recall@5 | recall@10 | MRR |
|---|---|---|---|
| dense only | 1.000 | 1.000 | 0.944 |
| old sparse only（代理） | 0.750 | 0.750 | 0.694 |
| new BM25 only | 0.750 | 0.750 | 0.646 |
| old hybrid（代理） | 1.000 | 1.000 | 0.944 |
| **new hybrid（bge-small 机制轮）** | 1.000 | 1.000 | 0.882 |
| **new hybrid（BGE-M3 1024d 轮）** | 1.000 | 1.000 | **0.889** |

- 结论：换成真实 BGE-M3 后差距基本不变——**new hybrid MRR 0.889 < old hybrid 0.944 < dense-only 0.944**。口语改写样本 `API 怎么对接` 仍是主因（两路词法都未命中，BM25 把相关文档从第 1 压到第 4）。样本量仅 12 条且为合成语料，**不能据此断言新方案更差，也绝不能据此切换**；同样不能声称更优。
- 处置：**不执行灰度切换**；T11 判据未通过。key 已就绪，后续应用真实业务语料 + 人工标注跑 `run_route_ablation.py` 的 E2，并针对口语改写样本调融合权重 / 加查询改写后再判决。

### 12.1 融合权重扫描（同批 BGE-M3 样本）

| dense/sparse 权重 | new hybrid MRR |
|---|---|
| 0.50 / 0.50 | 0.889 |
| 0.80 / 0.20（当前默认） | 0.889 |
| 0.90 / 0.10 | 0.903 |
| **0.95 / 0.05** | **0.944** |
| 1.00 / 0.00（等同 dense-only） | 0.944 |

- 结论：口语改写样本的排序回退**可以通过降低词法路权重缓解**；0.95/0.05 在这 12 条上与 dense-only / old hybrid 持平（0.944）。
- 但 0.95/0.05 意味着词法路贡献很小，"BM25 混合检索"的实际增益尚未被证明；**不据此改默认配置**。候选方案登记为：真实语料 E2 时把 0.8/0.2 与 0.95/0.05 一起扫，并要求领域型号/术语样本不被回退，才允许调权。

## 13. 治本形态 POC（2026-11-26，按用户要求改容器）

- 在 126 上把 POC 容器从 `v2.5.10` 换成 **`milvusdb/milvus:v2.6.3`**（镜像经已配置的华为云加速拉取），单容器 standalone。
- 启动必要参数：`DEPLOY_MODE=STANDALONE` + `ETCD_USE_EMBED=true`（2.6 内嵌 etcd 必须显式声明，否则 panic `embedded etcd can not be used under distributed mode`）；2.6 默认 MQ 为 Woodpecker，不再传 `MQ_TYPE=default`。
- 领域词典：把与 Python 共享配置同批词条写入 `/root/milvus-poc-zh-en/dicts/zh_terms.txt`，挂载到容器 `/var/lib/milvus/dicts/zh_terms.txt`，经 jieba 的 `extra_dict_file={"type":"local","path":...}` 引用。
- 引擎侧实测（`run_analyzer` 在 2.6 可用）：`"HAK-180 烫金机怎么用" -> ['HAK-180', ' ', '烫金', '烫金机', '怎么', '用']`，领域词作为整词出现，治本形态成立。
- **安全档位**：新增 `RETRIEVAL_ANALYZER_PROFILE`，默认 `simple_2_5`（线上 2.5.10 仍只能用简单形式），POC/升级后设 `domain_dict_2_6` 才启用引擎自定义词典；默认配置不破坏当前线上。
- 以 `domain_dict_2_6` + BGE-M3 重跑 A/B：MRR 与 §12 基本一致（new hybrid 0.889；权重 0.90/0.10 起可达 0.944）。领域词典在 12 条合成样本上未改变排序，但引擎侧词项完整性已由 `run_analyzer` 独立验证。
- **边界更新**：POC 与现网 K8s `ks-milvus` 均已升到 v2.6.3（见 `docs/plans/plan-milvus-prod-upgrade-2-6-2026-11-26.md` §9）；下面 §13.1 开始切治本形态。

### 13.1 现网切治本形态（2026-11-26，进行中）

- 领域词典已落 126 hostPath：`/data/k8s-demo/knowledge-service/dicts/zh_terms.txt`（6 条，与 Python 共享配置同批），以只读方式挂到 `ks-milvus` 的 `/var/lib/milvus/dicts`。
- 滚动策略改为 `maxSurge=0, maxUnavailable=1`：第一次 apply 因旧/新 Pod 同时挂同一 hostPath，RocksMQ 的 `/var/lib/milvus/rdb_data_meta_kv/LOCK` 冲突而 CrashLoopBackOff；改策略后 rollout 成功，新 Pod Running、healthz 200。
- 现网 `run_analyzer` 实测：`search` 模式输出 `['HAK-180',' ','烫金','烫金机','怎么','用']`，`exact` 模式输出 `['HAK-180',' ','烫金机','怎么','用']`。**`exact` 保住领域词整词且不产生多余子词**，已将共享配置 `analyzer.mode` 从 `search` 改为 `exact`，单测同步。
- 注意：`向量数据库` 在两种模式下都未作为整词出现（输出 `向量`+`数据库` 或 `向量`/`数据`/`据库`/`数据库`），词典文件的一行一词格式对该词未生效，需后续单独核实 jieba-rs 自定义词典权重格式；本批不据此宣称所有领域词都整词。
- **已完成（2026-11-26）**：
  - `RETRIEVAL_ANALYZER_PROFILE=domain_dict_2_6` 已通过 `kubectl set env deploy/ks-web` 注入；该值由 `agent_runtime.retrieval_tokenizer.milvus_analyzer_params()` 读取，线上默认仍 `simple_2_5`，只有显式注入后才切治本形态。
  - 新集合 `product_manual_v4_bge_m3` 已用治本 analyzer（jieba exact + local 领域词典）创建，并从 `platform_doc_v3_bge_m3` 回填 **83 行**（row_count=83）；引擎侧 BM25 检索可用。
- **仍未完成 / 新发现（2026-11-26）**：
  - ks-web 已恢复为 1/1 Running，且新 RS Pod 已带 `RETRIEVAL_ANALYZER_PROFILE=domain_dict_2_6`；它就是 `knowledge_service` 宿主（`/app/knowledge_service/__init__.py`）。
  - **硬阻塞**：该镜像里**没有 `agent_runtime`**（只有 `agent-core`），也没有 `jieba`；`agent-server` 镜像同样没有 `jieba`。我们新代码 `node_import_milvus.py` 依赖 `agent_runtime.retrieval_tokenizer`、`get_tokenizer()` 也依赖 jieba，直接上生产会 `ModuleNotFoundError` / `RuntimeError`。
  - 因此治本形态目前只在 v4 集合与引擎侧生效；**Python 侧必须随镜像重建补齐 `agent-runtime` + `jieba`**，否则不能宣称端到端切换完成。镜像重建/分发属 D2，另行批准。
  - 真实业务语料 A/B、`向量数据库` 词典格式核实、30 分钟观察与旧集合保留期满清理仍未做。
  - **镜像重建（2026-11-26，D2 已批准）**：已在 241 上从 rev `d9cd7daa` 建立独立 worktree；KS 镜像补 `agent-runtime[tokenizer]` + `jieba`，根镜像经根 pyproject 带入 jieba。两个镜像均构建、A1 通过、按 `--address /run/containerd-k8s/containerd.sock` 分发到 125/126，`crictl images` 回读一致。
  - **生产验收（2026-11-26）**：
    - `agent-platform` Pod imageID `sha256:143e88117651…`、容器 `GIT_REV=d9cd7daa…`、`jieba 0.42.1` 可用，共享 tokenizer 产出 `['hak-180','烫金机','怎么','用']`。
    - `ks-web` Pod imageID `sha256:3274470d8afe…`，env `RETRIEVAL_ANALYZER_PROFILE=domain_dict_2_6`；Pod 内探针读到 `PROFILE_PARAMS={'tokenizer':{'type':'jieba','dict':['_default_'],'mode':'exact','hmm':True,'extra_dict_file':{'type':'local','path':'/var/lib/milvus/dicts/zh_terms.txt'}}}`，领域词同样整词。
    - Milvus 1/1、ks-web 1/1、healthz 200；v4 集合 `product_manual_v4_bge_m3` 83 行可查。
    - ks-web 滚动策略保持 `maxSurge=0/maxUnavailable=1`（避 hostPort 死锁）。
  - 注意：镜像重建期间 CRI 多次 GC 把 milvus / ks-web 镜像挤出，已从 tar 恢复并重建 Pod；这类副作用已记录，后续分发应逐节点回读关键镜像。
  - **已知限制**：`向量数据库` 在 jieba `exact` 模式下仍切成 `向量`+`数据库`。2026-11-26 实测把词典改成带词频格式（`向量数据库 1000`）后输出不变，说明内置词典优先级压过自定义条目；该词不影响当前 12 条 golden 与 83 行 canary 的判决，留作后续词典方案专项，不在本批宣称已解决。
  - **真实语料 A/B（2026-11-26）**：量具 `applications/knowledge-service/eval/run_real_corpus_ab.py`，83 行现网文档 self-retrieval canary（从每篇文档自身抽 query，标注该文档 relevant）。读数：dense 1.000/1.000/1.000；旧 md5/TF hybrid recall@5=0.964、recall@10=1.000、MRR=0.839；**新引擎 BM25 hybrid recall@5=0.988、recall@10=1.000、MRR=0.889**。新路在这组 canary 上优于旧路；但 dense 是自身向量所以恒为 1，且这不是人工语义 golden，不能当作线上质量最终判决。报告在 `eval/runs/real_corpus_ab.json`。
