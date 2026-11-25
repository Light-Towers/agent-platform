# 中英混排检索分词改造 — Tasks

> 前置：先读 `spec.md`（做什么）与 `design.md`（怎么做）。
> 依赖链：T1 → T2 → T14 → T3/T4 → T5/T7/T8/T9 → T10 → T11 → T12 → T13。
> 每项完成判据必须带可复核证据（命令 / 读数 / 文件），禁止只写"已完成"。

## T1 — 方案评审与 ADR 登记（D1 批准）

- [ ] 在 `docs/adr/` 新增 ADR，登记：词法路改用 Milvus 内置 BM25 + jieba、dense 保持不变、旧 learned sparse 分阶段退役、放弃 ES 与通用 SPLADE 的理由。
- [ ] 明确 ADR-0009 的未决状态与本 ADR 的关系（接口统一 ≠ 存储统一；本 ADR 只改变 KS 词法实现）。
- [ ] 把本组 Spec/Design/Tasks 路径登记到 `docs/plans/` 入口文档，使 `scripts/check_doc_sync.py` 可通过。
- [ ] **方案件入库**：三件套 + plan 必须 `git add` 并提交；路径在版本控制清单内可解析，且 blob 非空。
- **验收**：人批记录可追溯；`git ls-files docs/specs/cn_en_tok/ docs/plans/plan-cn-en-tokenizer-2026-11-25.md` 列出全部四件，`git cat-file -e HEAD:<path>` 对四件均 rc=0 且 `git cat-file -s HEAD:<path>` >0；`uv run python scripts/check_doc_sync.py` rc=0。
- **依赖**：无。

## T2 — POC：在 v2.5.10 上验证关键能力（隔离环境）

- [ ] 在隔离环境使用 `milvusdb/milvus:v2.5.10`（**本批不升级服务端**），验证锁版 pymilvus 3.0.3 与该服务端的组合可用。
- [ ] 验证 `jieba` tokenizer 的 `dict` 注册方式（文档只给出词典名列表，挂载路径需实测确认）；以 **≥10,000 词条**实测注册耗时、查询加载耗时与检索延迟。
- [ ] v2.5.10 无 `run_analyzer`：改为**建临时集合实测检索**，对混排样本 `HAK-180 烫金机怎么用`、`BGE-M3 sparse 原理`、`running machine` 断言领域词不被拆碎、英文保整词、大小写归一。
- [ ] 验证 hybrid search 中 BM25 腿可直接传原文（`AnnSearchRequest` + `metric_type=BM25`），并验证 `WeightedRanker(norm_score=True)` 融合。
- [ ] 验证 `language_identifier` 在短混排查询上的判定不稳定性，作为"不采用自动路由"的反证记录。
- [ ] 明确记录边界：现网 K8s 引擎升级、存量 `platform_doc_v3_bge_m3` 在新引擎上的兼容验证与服务端回退预案**不在本批**，另立工单。
- **验收**：POC 报告逐条给出 rc / 输出词项 / 耗时读数 / 版本号；任一 verification 失败则停止后续实施并回到 T1。
- **依赖**：T1。

## T3 — 领域词典入库与版本化

- [ ] 新建入库配置文件，记录领域词条、词典版本、使用范围（KS / agent_server / nl2sql 共用）。
- [ ] 词条去重校验；版本变更规则写入配置说明；8,000 词告警、10,000 词拒绝新增，告警 / 拒绝在真实注册路径上生效（非只校验配置文本）。
- [ ] 词典配置由 **T14 的单一事实源**提供，本项不再单造"版本号一致"lint（口径弱于 Spec 5.3，且会形成两把尺）。
- [ ] 词典配置纳入版本控制清单，受文档同步门禁保护。
- **验收**：配置可解析；`uv run python scripts/check_doc_sync.py` rc=0；重复词条检测 rc≠0（自证能咬）；三侧行为等价由 T14 门禁验收。
- **依赖**：T2（词典注册方式已确认）、T14（单一事实源）。

## T4 — 新集合版本与双写 / 重灌

- [ ] 按 `design.md §4.2.1` 定义新集合（建议 `platform_doc_v4_bm25_jieba`）：原文 `enable_analyzer=True` + jieba、dense 字段、BM25 Function 自动生成稀疏字段、租户 / 工作空间 / 知识库 / 状态字段沿用。
- [ ] dense 索引沿用现有口径；稀疏索引用 `SPARSE_INVERTED_INDEX + BM25`。
- [ ] 实现双写 / 重灌脚本；重灌后校验行数、租户隔离用例、BM25 稀疏字段非空且由引擎生成。
- **验收**：新集合就绪且可检索；旧集合仍对外服务；行数与隔离用例全绿。
- **依赖**：T2、T3。

## T5 — knowledge-service 主链路切换到 BM25

- [ ] `node_search_embedding.py`：去掉 `generate_embeddings()` 的 sparse 取值，查询只传原文 + dense。
- [ ] `node_search_embedding_hyde.py`：同上，HyDE 拼接文本的词法腿传原文。
- [ ] `clients/milvus_utils.py`：按集合版本分支构造 BM25 腿；`hybrid_search` 权重含义改为 dense / BM25，权重仍读 `conf/retrieval.yaml`。
- [ ] 导入侧停止写入应用侧 sparse 向量，改由引擎 Function 生成。
- [ ] `node_rrf.py` / `node_rerank.py` / 四路 fanout 行为保持不变。
- [ ] 列出因契约变更而需**改断言（非删用例）**的测试清单并逐条给新断言：`tests/integration/test_main_graph.py:88,104`（不再断言 `sparse_vector` 由应用写入，改为断言 BM25 稀疏栏位非空 / 由引擎生成）、`tests/unit/test_kb_delete.py:40,59`（写入夹具去掉应用侧 sparse）、`tests/unit/test_sparse_vectorizer.py` 与 `tests/unit/test_normalize_sparse.py`（随实现退役转为历史读件，禁止直接删除）、`tests/unit/test_sparse_consistency.py`（从主门禁降为历史读件）。
- **验收**：`uv run --with ruff ruff check applications/knowledge-service` rc=0；`uv run pytest applications/knowledge-service/tests -q` 全绿；新旧集合分别可检索且响应形状一致；测试清单逐条有"改断言而非删用例"的复核记录。
- **依赖**：T4。

## T6 — 退役手写稀疏实现（分阶段）

- [ ] 阶段一：从主链路读点摘除 `sparse_vectorizer.py` / `agent_runtime/vector_sparse.py` 的调用；保留文件供历史读数复跑。
- [ ] 阶段二：`sparse_consistency.py` canary 从主门禁降为历史读件；评测脚本保留旧链路复跑入口。
- [ ] 阶段三（观测周期后）：删除正则实现与旧 canary 的门禁引用，更新关联文档。
- [ ] "禁止本地分词实现 / 手写正则"由 **T14 的架构不变量 lint**统一兜底，本项不再新增第二把尺；旧 canary 只作历史读件。
- **验收**：T14 lint 对真实代码 rc=0、对合成违规 rc≠0；检索读点零命中（待退役件除外）；阶段一 / 二各留一条可检索的变更记录。
- **依赖**：T5、T14 且评测通过。

## T7 — agent_server 降级链路分词替换

- [ ] 在依赖中声明 jieba（全局 / 应用级按仓库依赖方向决策），避免缺包静默降级。
- [ ] `rag/store.py:37-46` 的 `tokenize()` 改为 jieba 单源实现：中文按词、英文按词元、小写归一。
- [ ] `pg_backend.py` 检索行为与隔离谓词保持不变；确认 `to_tsvector('simple', ...)` 接收 jieba 词元。
- **验收**：`uv run --with ruff ruff check .` rc=0；`uv run pytest tests -q` 全绿；补充 2 条混排分词单测（中英混排 + 领域词完整）。
- **依赖**：T3（词典可用）；与 T5 可并行。

## T8 — nl2sql 默认分词切到 jieba

- [ ] `conf/settings.py:98-99` 与 `conf/app_config.yaml:53-54` 默认值改为 `jieba`。
- [ ] `pyproject.toml:49-52` 的 `[tokenizer]` extra 进入部署安装清单。
- [ ] `tokenizer.py` 现状已是"告警一次后降级 bigram"（`tokenizer.py:33-42`），本项只补强：把实际分词器写入可检索日志 / 指标，并确保告警不是一次性不可追溯；不得把已有告警能力误判为新增工作量。
- **验收**：默认配置启动读数为 `jieba`；缺包场景产生告警且日志可检索；`uv run pytest applications/nl2sql-service/tests -q` 全绿。
- **依赖**：T3；与 T5 可并行。

## T9 — nl2sql 存量取值行重建

- [ ] 以 `value_info.tokenizer` 为标记，识别与当前配置不一致的行。
- [ ] 补迁移 / 运维脚本：按新分词器写入**影子存储**（影子列 / 影子表），校验通过后原子切换生效配置，再更新 `tokenizer` 标记；旧存储保留一周期回退。
- [ ] 重建期间查询侧继续按当前生效配置（旧分词器）对外服务，禁止排除旧行导致空召回。
- **验收**：重建前后行数一致；标记不等于当前生效配置的行数为 0；重建期间对外召回非空且用户可感知行为无变化；取值召回 A/B 不回退。
- **依赖**：T8。

## T10 — 评测管线按路指标与领域样本

- [ ] 评测管线增加 semantic / lexical / fused 三路 recall@5 / recall@10 输出。
- [ ] 领域 golden case 补四类样本：产品型号、领域黑话、缩写、中英混排（含纯英文对照）。
- [ ] 评测记录绑定分词器版本、集合版本、判决时间、HEAD sha。
- [ ] 明确评测入口与环境：在 `applications/knowledge-service/` 下运行 `python eval/run_route_ablation.py`（层 1 RRF 通道消融 + 层 2 dense/sparse 消融）产出分路 recall@5/recall@10；前置 `python eval/seed_synthetic_corpus.py` 与 labeled golden。**根 `eval/run_eval.py` 是路由评测，不产出分路指标，不得作为本项验收命令。**
- [ ] 基线当轮同环境复取，读数绑定分词器版本、集合版本、判决时间、HEAD sha。
- **验收**：`cd applications/knowledge-service && python eval/run_route_ablation.py ...` rc=0 且输出 semantic / lexical / fused 分路指标；过期 / 无版本读数被判为无效（自证能咬）；根 `eval/run_eval.py` 的误用被评审记录排除。
- **依赖**：T4、T7、T9。

## T11 — A/B 评测与灰度切换

- [ ] 用同一批 golden case 在**同一环境当轮**跑旧链路 vs 新链路，输出按路对比表；基线不得沿用上一轮读数。
- [ ] 判据：领域词与混排问句的词法路 recall@K 不低于基线；融合后指标不低于基线；隔离用例全绿。
- [ ] 灰度切换 KS 集合名与 `DocumentStore` 配置；旧集合至少保留 **14 个自然日且跨一次完整部署窗口**。
- **验收**：A/B 报告入库且绑定 HEAD sha 与判决时间；未达判据时不得切换（用反例自证门禁有效）。
- **依赖**：T10。

## T12 — 回退演练与观测周期清理

- [ ] 回退演练：从新集合恢复到旧集合与旧配置，计时 ≤10 分钟；明确该时长**仅覆盖集合 / 配置层**，不含引擎面故障（引擎升级不属本批）。
- [ ] 观测至少 14 个自然日且跨一次完整部署窗口：检索端到端 P95 ≤ 基线 110%、按路词法召回耗时有读数、无分词一致性告警。
- [ ] 观测通过后按 T6 阶段三删除旧实现。
- **验收**：回退演练记录含耗时与读数；清理后 `make lint` 与 `make test` 对齐 CI（Windows 用等价命令）。
- **依赖**：T11。

## T13 — 文档与门禁收尾

- [ ] 更新 `ARCHITECTURE.md` / 相关 README 的检索方案描述，区分 dense+BM25 与旧 learned sparse。
- [ ] 把方案件、ADR、评测入口、量具路径（含 **T14 的共享分词模块与两把门禁**）登记进 `scripts/evidence/README.md` 与 `ARCHITECTURE.md`，保证入库可解析。
- [ ] 运行 `uv run python scripts/check_doc_sync.py` 与 `make lint` 等价命令。
- **验收**：两项 rc=0；文档中的路径可用 `git ls-files` + `git cat-file -e` 解析且 blob 非空。
- **依赖**：T12、T14（量具登记不可漏）。

## T14 — 治本补强：单一实现 / 单一装配 / 行为等价门禁

> 本工单是从"全局治理"升级到"全局治本"的必经项，**不可作为可选优化删去**（design §4.3 三层齐备性）。

- [ ] 在 `agent-runtime` 新增共享分词模块，以 optional extra 声明 `jieba>=0.42`；严格遵守 `applications → agent-runtime → agent-core` 单向依赖，不放入零依赖的 `agent-core`。
- [ ] 建立**单一事实源**：词典版本、分词器配置、Milvus analyzer 配置由同一份入库配置生成；KS / agent_server / nl2sql 三侧不再各写一份。
- [ ] 提供唯一装配入口 `get_tokenizer()`（或等价工厂）；三个服务只从该入口取分词能力，服务内禁止自建分词函数、正则切词或词典读取逻辑。
- [ ] 实现**行为等价门禁**：对约定混排样本，三侧（引擎侧用临时集合实测）产出词项集合必须相等；注入配置或词典版本不一致时 rc≠0，恢复后 rc=0。该门禁替代 T3 的"版本号一致"lint，口径与 Spec 5.3 对齐，全仓只此一把。
- [ ] 实现**架构不变量 lint**：禁止服务内出现本地分词实现 / 手写正则；对合成违规样本 rc≠0，对真实代码 rc=0。该门禁替代 T6 的临时扫描脚本，全仓只此一把。
- [ ] 两把量具与共享模块全部入库，登记进 `scripts/evidence/README.md` 与 `ARCHITECTURE.md`，受 `scripts/check_doc_sync.py` 保护；纳入 `make lint` 等价命令。
- **验收**：
  - `uv run --with ruff ruff check packages/agent-runtime` rc=0；
  - `uv run pytest packages/agent-runtime/tests -q` 全绿（含共享分词模块单测）；
  - 行为等价门禁：三侧一致时 rc=0、注入不一致时 rc≠0（两条读数）；
  - 架构不变量 lint：真实代码 rc=0、合成违规 rc≠0（两条读数）；
  - `uv run python scripts/check_doc_sync.py` rc=0；
  - `git ls-files` + `git cat-file -e HEAD:<path>` 对新模块与两把量具均解析成功且 blob 非空。
- **依赖**：T2；被 T3 / T5 / T6 / T7 / T8 / T13 依赖。
