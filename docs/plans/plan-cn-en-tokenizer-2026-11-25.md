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
