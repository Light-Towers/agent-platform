# 更新日志（Changelog）

本文件记录本项目所有值得关注的变更。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本 SemVer](https://semver.org/lang/zh-CN/)。

**版本治理约定**：

- 合并到 `main` / `production` 后打 `vX.Y.Z` tag，tag 与 `pyproject.toml` 的 `version` 保持一致。
- 新增能力升 **minor**，缺陷修复升 **patch**，配置或索引 schema 的破坏性变更在对应版本下单列 `### Breaking`。
- 未发布的变更先累积在 `[Unreleased]` 版本段，发布时补上日期。

---

## [1.1.0] - Unreleased

> M1 工程闭环：只补 CI / 版本治理 / 测试分层三项工程能力，不涉及 `app/` 业务代码改造。
> M2 检索评测体系 + 索引生命周期版本化：开始触碰 `app/` 源码（配置驱动集合命名、chunk 元数据、registry），
> 并落地评测管线（golden dataset / 指标纯函数 / run_eval CLI / 单测）。
> M3 配置外置与实验管理：检索/重排参数外置到 `app/conf/*.yaml`，消除节点内硬编码；
> 并完成 ruff 全量整形与 ignore 收窄（技术债偿还）。
> M3.5 Dynamic TopK 消融实验框架：提供"固定 k vs 动态断崖"的对比实验设计与运行器，
> 为排序阈值提供可追溯的证据链（当前为框架，真实数据待实测）。
> M8 硅基流动 API 模式：embedding/rerank 双模式（local 默认，api 可选），无 GPU / 无本地模型
> 也能完整跑通导入与检索；api 稀疏向量为本地词权重近似（B 路线），保住稠密+稀疏双路混合检索。

### Fixed

- **docker-compose：Milvus standalone 缺失 etcd 依赖导致无法启动**（环境验收 ① 阻塞项）。
  原配置注释假设「standalone 镜像内置 etcd，无需额外服务」，但 v2.5.10 镜像内 `milvus.yaml`
  默认 `etcd.endpoints=localhost:2379` 且 `UseEmbed=false`，容器内无 etcd 时反复
  SIGABRT(134) 重启。按官方 standalone compose 补 `etcd`(quay.io/coreos/etcd:v3.5.18) 服务
  与 `ETCD_ENDPOINTS`/`MINIO_ADDRESS`/`MINIO_REGION` 环境变量，并新增 Milvus `9091/healthz`
  健康探针（此前无探针，`compose ps` 无法反映真实就绪状态）、web 的 `depends_on` 改为
  `service_healthy`。修复后 `RestartCount=0`、`healthz` 返回 OK。
  依赖版本以 **Milvus v2.5.10 官方 standalone compose** 为准（etcd 3.5.18；通用文档写 3.5.0，
  同为 3.5.x 系列）。另显式声明 `MINIO_BUCKET_NAME=a-bucket`（Milvus 内部桶，与应用桶
  `kb-import-bucket` 同实例不同桶，消除隐式依赖；已用变更值反证该变量确被读取）。
  v2.5.10 standalone 默认 MQ 为**嵌入式 rocksmq**（日志实测），无需单独 MQ 服务；
  Milvus 2.6+ 文档所述 Woodpecker 默认 MQ 不适用于本版本。
- **docker-compose：`minio/mc` 镜像 tag 不存在导致 minio-init 拉取失败**。
  原配置与 `minio/minio` 复用同一 tag `RELEASE.2024-01-16T16-07-38Z`，但两者 RELEASE
  体系相互独立，mc 无此 tag（`manifest unknown`）。独立锁版为
  `RELEASE.2025-04-16T18-13-26Z`，桶 `kb-import-bucket` 自动创建已验证成功。
- **`/query` 接口 100% 返回 500（M5 安全中间件重构引入的 Request/Pydantic 混淆 bug）**。
  原 `query()` 签名为 `request: QueryRequest`（Pydantic 请求体模型），却在第 162 行误用
  `request.state.request_id` 取中间件注入的 trace id——Pydantic 模型无 `.state` 属性，
  导致**所有 `/query` 请求（同步/流式、无论 Neo4j 是否运行）在 handler 入口即抛
  `AttributeError` 并返回 500**，整条问答链路完全不可用，更走不到 fan-out 阶段。
  修复：拆分 `request: Request`（取 `request.state.request_id`）+ `payload: QueryRequest`
  （取业务字段），函数体内业务字段引用由 `request.` 改为 `payload.`。重建镜像
  `7b819cbb3464` 后 `/query` 返回 200（未导入文档时为兜底文案，链路已端到端跑通）。
  **此 bug 使交接文档验收项 ⑥ 的"停 Neo4j → /query 仍完成"在修复前根本无法验证。**
- **诚实声明：fan-out kg 通道为占位实现（stub），未接真实 Neo4j，隔离逻辑未真实验证**。
  `app/query_process/agent/nodes/node_query_kg.py` 注释明确"未接 Neo4j，仅 `time.sleep(1)`"，
  `retrieval.yaml` 中 `kg: {enabled:true, timeout_s:1.0}` 与 `fanout.guarded_call`/`wrap_channel_node`
  的超时降级框架均已就绪，但 kg 节点从不连接 Neo4j，故：停 Neo4j **不会**影响 `/query`
  （因从未调用），`recall timeout channel=kg` 日志**不会**出现。交接文档 §（验收项 ⑥）将之
  描述为已验证项与事实不符，应降级为"框架已实现、kg 真实数据源接入后需重测"。M6 fan-out
  的实际故障隔离能力在当前代码下无法证明。
- **验收项 ④ 鉴权实测通过（2026-08-06 补验）**：`.env` 配置 `ZHANGUI_API_KEY`（自生成密钥）并重建
  web 后，中间件真实生效——`POST /query` 无 key/错 key → 401 `UNAUTHORIZED`，带正确
  `X-API-Key` 或 `Authorization: Bearer` → 200；`/health*`、`/import.html` 等豁免路径免鉴权仍 200。
  此前验收因未设 key 仅验证"全放行"态，现补齐 401/200 双向验证。
- **验收项 ⑦ OTel 真实导出跑通（2026-08-06 补验）**：`tracing.py` 修复三处使 OTLP 导出真正可用——
  (a) OTLP exporter 选择改 **HTTP 优先**（原 grpc 优先，到 jaeger 握手 `http2 preface EOF` 失败）；
  (b) `TracerProvider` 补 `resource={"service.name": service_name}`，否则 span 在 jaeger 归到
  `unknown_service`、按服务名不可查；(c) `.env` 的 `OTEL_EXPORTER_OTLP_ENDPOINT` 须带完整
  `/v1/traces` 路径（OTLP HTTP exporter 不自动追加）。修复后 `docker compose --profile core --profile obs up`
  + `ZHANGUI_TRACE_ENABLED=true`，`POST /query` 即在 Jaeger(`localhost:16686`) 的 `zhanggui-zhiku`
  服务名下产出 trace（实测每请求 2 span：`request.total` + `retrieval.rewrite`），无 export error/404。
  Dockerfile 已将 `opentelemetry-sdk` + `opentelemetry-exporter-otlp-proto-http` 纳入镜像依赖，
  确保开箱即用（默认仍 no-op 降级，配置 endpoint + 启用开关后才真实导出）。


### Added

- **GitHub Actions CI 工作流**（`.github/workflows/zhiku-ci.yml`，位于 **monorepo 仓库根**；本仓库为
  noctilucent-lamp 单仓库，GitHub Actions 只扫描根目录 workflow）：`push` 到 `main` / `production` 及所有
  `pull_request` 触发（均带 `paths: ['zhanggui-zhiku/**']` 过滤，仅子项目变更时触发）。
  `quality` job 依次执行 `uv sync --frozen` → ruff 静态检查 → ruff 格式检查 →
  `pytest tests/unit`；`build` job 在 `quality` 通过后执行 `docker compose build web` 构建冒烟，
  **不推送 Registry**、不引入 `docker/build-push-action`。所有 `run` 步骤通过
  `defaults.run.working-directory: zhanggui-zhiku` 定位到子项目。
- **Nightly 工作流**（`.github/workflows/zhiku-nightly.yml`，同样位于 monorepo 仓库根）：UTC 18:00
  定时触发 + 手动 `workflow_dispatch`，拉起基础设施后运行 `tests/integration`，随后执行检索评测并归档
  评测产物（artifact `path` 相对 workspace 根，为 `zhanggui-zhiku/eval/runs/`）。
- **测试目录归并**：建立 `tests/{unit,integration,eval}` 三级测试分层。原先散落在仓库根 `test/` 下、
  **不进 CI** 的 5 个手测脚本（env 优先级 / 日志 / CUDA / 导入图流程 / 主图全流程）已改造为可被 pytest
  收集的用例并迁入 `tests/integration/`，原 `test/` 目录移除。缺依赖或缺外部服务时用例自动跳过，
  不会让流水线误红。
- **版本号治理**：引入本 CHANGELOG 与语义化版本约定（见文件头部"版本治理约定"）。
- **ruff 基线配置**（`pyproject.toml` 的 `[tool.ruff]`）：固定规则集、忽略清单与 target-version，
  作为存量代码的静态检查基线，保证 CI 结果可复现。

### Added（M2：检索评测体系，方案 §6）

- **golden 评测集** `eval/golden_queries.jsonl`：56 条脱敏样例 query（参数查询 / 操作步骤 / 故障排查 /
  多跳 各 14 条），含 `grade` 分级标注（2/1/0，nDCG 必需）与 `relevant_chunk_ids`。头注释明示
  **本数据集为构造 / 脱敏样例，非线上日志**（方案 §13 诚实声明口径），并说明仓库无 `doc/` 素材时的构造依据。
- **检索指标纯函数** `eval/metrics.py`：`recall_at_k` / `hit_rate_at_k` / `mrr` / `dcg_at_k` / `ndcg_at_k` /
  `compute_retrieval_metrics`，零外部依赖，边界完备（空召回 / 空相关 / 全相关 / 排序敏感性）。
- **评测 CLI** `eval/run_eval.py`：`--out eval/runs/ [--limit N]`，逐条调用检索链路（embedding 召回 →
  加权 RRF → BGE 重排，**不含 LLM 生成**，`--enable-hyde` 可选开 HyDE 路）；输出
  `{timestamp}_{config_hash}/metrics.json`（总分 + 按 tag 分桶）、`per_query.jsonl`、`badcases.md`；
  Milvus 不可达 / 集合不存在时打印清晰错误并以非 0 退出（环境守卫，不吞异常）。
- **指标单测** `tests/unit/test_eval_metrics.py`：21 个用例，重点覆盖 nDCG 分级计算与
  "排序好坏拉开分差"的核心断言。
- **配置哈希机制**（方案 §7.5 前置）：`run_eval.py` 的 `config_hash` 优先读
  `app/conf/retrieval.yaml` / `rerank.yaml`（M3 提供），当前退化到 M2 硬编码基线快照 + 集合名。

### Added（M2：索引生命周期版本化，方案 §5）

- **集合版本化命名**：`app/core/config.py` 与 `app/conf/milvus_config.py` 新增
  `collection_prefix` / `schema_version`，集合名统一按 `{prefix}_{schema_version}_{embedding_model}`
  拼装（如 `product_manual_v1_bge_m3`）；`node_import_milvus.py`（导入侧）与
  `node_search_embedding.py` / `node_search_embedding_hyde.py`（检索侧）**全部改为读取同一
  `milvus_config.chunks_collection`**，消除检索侧原先 `os.environ.get("CHUNKS_COLLECTION")`
  与导入侧配置对象不一致的风险（评审点）。显式设置 `CHUNKS_COLLECTION` 时仍兼容沿用（既有数据覆盖路径）。
- **chunk 元数据**：`node_import_milvus.py` schema 与入库数据补充
  `embedding_model`（VARCHAR）/ `chunk_version`（VARCHAR）/ `created_at`（INT64 epoch）/
  `source_doc`（VARCHAR），旧字段（`parent_title` / `file_title` / `item_name` 等）保留不动，向后兼容。
- **索引 registry**：新建 `data/index_registry.json`（初始为空）与 `app/utils/index_registry.py`
  （`register_index` / `backfill_eval_scores` / `read_registry` / `write_registry`）；
  `import_process` 入库成功后自动登记一条（doc_count / chunk_count 填运行时事实，eval 四指标一律 null 待实测）；
  `run_eval.py` 跑完回填得分到对应集合条目（集合条目不存在时提示跳过，不自动创建）。

### Changed

- **锁定依赖由 `uv.lock` 保证可复现**：CI 统一使用 `uv sync --frozen`，流水线内不生成也不更新锁文件，
  确保本地与 CI 装出完全一致的依赖树。
- `pyproject.toml` 的 `version` 由 `1.0.0` 提升至 `1.1.0`。
- 工作流文件随仓库 monorepo 结构落位于**仓库根** `.github/workflows/`（`zhiku-ci.yml` /
  `zhiku-nightly.yml`），并配置 `defaults.run.working-directory` 指向子项目目录。
- `.env.example`：Milvus 段补充 `MILVUS_COLLECTION_PREFIX` / `MILVUS_SCHEMA_VERSION` / `CHUNK_VERSION`
  三个新变量，并注明 `CHUNKS_COLLECTION` 仅在需要沿用旧集合时显式设置。

### Added（M3：配置外置与实验管理，方案 §7）

- **检索配置外置** `app/conf/retrieval.yaml`：`hybrid`（dense_weight 0.8 / sparse_weight 0.2）、
  `rrf`（k 60 / max_results 10 / weights embedding 1.0 + hyde 1.0）、`channels`（embedding/hyde/kg/web
  四路开关 + 超时，配合 §10.3 逐路 timeout，M6 fanout 使用）。默认值与改造前硬编码完全一致。
- **重排配置外置** `app/conf/rerank.yaml`：`model` / `batch_size` / `max_concurrency` /
  `dynamic_topk`（enabled / gap_ratio 0.25 / gap_abs 0.5 / min_k 1 / max_k 10）/ `fallback.on_error
  = passthrough`。默认值与改造前硬编码完全一致。
- **轻量 yaml 加载器** `app/conf/yaml_config_utils.py`：`yaml.safe_load` + `CfgDict`（dict 子类 +
  属性访问，支持 `cfg.rrf.k` 与 `cfg.rrf.weights["embedding"]` 两种风格），支持环境变量
  （`ZHANGUI_RETRIEVAL_YAML` / `ZHANGUI_RERANK_YAML`）覆盖 yaml 路径。**不引入 Hydra / MLflow /
  新依赖**（pyyaml 已随项目传递依赖存在）。
- **节点硬编码消除**：`node_rrf.py` 的权重 / k / max_results、`node_search_embedding.py` 与
  `node_search_embedding_hyde.py` 的 `(0.8, 0.2)`、`node_item_name_confirm.py` 的 `(0.8, 0.2)` 与
  `os.environ.get("ITEM_NAME_COLLECTION")`、`node_rerank.py` 的 `gap_ratio=0.25` / `gap_abs=0.5` /
  `RERANK_*` 常量，全部改为读取配置（默认行为不变）。
- **配置单测** `tests/unit/test_retrieval_config.py`：6 个用例，验证两个 yaml 可加载、默认值与现状
  一致、加载器属性访问、环境变量覆盖、缺失文件报错。
- **评测实验索引表** `eval/README.md`：评测体系用法（golden 格式 / run_eval 参数 / 输出结构）+
  实验索引表**空模板**（run_id / config_hash / 变更点 / Recall@5 / nDCG@10 / 结论，首行 baseline
  占位，全部数值留空，禁止预填）。

### Added（M3.5：Dynamic TopK 消融实验框架，方案 §6.4）

- **消融实验设计文档** `eval/topk_ablation.md`：实验目的（trade-off：动态 TopK 不是提升 Recall，
  而是「Recall 几乎不掉的前提下减少注入 LLM 的无关上下文」）、自变量/控制变量/因变量/样本/重复
  设定、结果表**空模板**（fixed_k=3/5/10 + dynamic 五行，全部留空）、阈值敏感性扫描空表
  （gap_ratio 0.15/0.25/0.35 × gap_abs 0.5）、如何跑。**不照抄 Review 示例数据**。
- **消融运行器** `eval/run_ablation.py`：`--out / --limit / --golden / --enable-hyde / --skip-rerank`；
  对每条 golden query 在 fixed_k=3/5/10/dynamic 四种策略下各跑一次检索（复用 run_eval.retrieve_one，
  **不改动线上节点代码**）；输出 `eval/runs/{timestamp}_{config_hash}/ablation.md`（对比表 + 平均
  返回条数 + token 估算 + 检索链路 P95）；Milvus 环境守卫与 run_eval 一致（return 1）；当前假设
  标注下指标如实输出 0 并注明原因。
- **消融纯函数** `eval/ablation.py`：策略解析 / fixed_k 截断 / token 启发式估算 / 均值与 P95 /
  按策略聚合，零外部依赖，可独立单测。
- **ADR 骨架** `docs/adr/0003-dynamic-topk-threshold.md`：记录 gap_ratio=0.25/gap_abs=0.5 的来源
  （原无实验支撑经验值，M3 起外置）与选值方法论，Status **Proposed（待消融数据后 Accepted）**，
  结论区留空待填。
- **消融单测** `tests/unit/test_ablation.py`：21 个用例（策略解析 / 截断 / token 估算 / 文本提取 /
  均值 / P95 / 聚合），mock 检索结果验证四种策略截断行为，不连 Milvus。
- **脚本直跑路径引导**：`eval/run_eval.py` 与 `eval/run_ablation.py` 增加项目根 sys.path 引导
  （`# noqa: E402` 显式标注），`python eval/*.py --help` 与直跑不再依赖 editable 安装。

### 已知技术债（M3.5 显式记录，后续里程碑消化）

- 消融实验**尚无真实数据**：`run_ablation.py` 已可跑通路径，但 golden 的 `relevant_chunk_ids` /
  `grade` 为构造标注，未建真实索引时输出全 0 属预期；拿到真实文档入库 + 重新标注后即可一键跑出
  对比并回填 `eval/topk_ablation.md` 结果表与 ADR-0003 结论。
- `run_ablation.py` 的 P95 延迟为**检索链路口径**（不含 LLM 生成）；方案 §6.4 结果表的"端到端
  P95 延迟"需在含生成链路中另行压测（M7 benchmark）。
- 阈值敏感性扫描（gap_ratio 0.15/0.25/0.35 × 0.5）为 P1 可选增强，当前 `run_ablation.py`
  只固定跑 dynamic(0.25, 0.5)。

### Changed（M3：技术债消化 + CI 门禁翻转）

- **ruff 全量整形**：执行 `ruff format app tests eval`（62 个文件重排，22 个不变，全部为纯格式，
  无逻辑改动），`ruff format --check` 现为全绿。
- **ignore 收窄**：通过 `ruff check --fix --select F401,F541` 自动修复 **F401 18 处**（含 M2 引入的
  `node_search_embedding.py` 残留 `import os`）与 **F541 6 处**，二者已从
  `pyproject.toml [tool.ruff.lint] ignore` 移除；剩余 ignore 仅保留**非自动修复**存量项
  （E722 1 / F403 6 / F405 18 / F811 1 = 26 处），数量已在 pyproject 注释与本节更新。
- **CI format 门禁翻转**：`zhiku-ci.yml` 的 Format check 移除 `continue-on-error: true`，恢复阻塞语义；
  lint 与 format 作用域由 `app tests` 扩至 `app tests eval`。
- `eval/run_eval.py` 的 `compute_config_hash()` 现已自动读取 `retrieval.yaml + rerank.yaml` 内容
  （M2 已实现"yaml 存在则读 yaml"分支，M3 落地 yaml 后无需改代码即生效，已实测验证）。

### 已知技术债（M1 显式记录，后续里程碑消化）

- `ruff check` 原忽略 `F401` / `F403` / `F405` / `F541` / `E722` / `F811` 共 49 处存量告警。
  **M3 已偿还 F401（18 处）与 F541（6 处）**，从 ignore 移除；剩余非自动修复项
  （E722 1 / F403 6 / F405 18 / F811 1 = 26 处）继续作为待收窄基线。
- `ruff format --check` 原为 **非阻塞**（`continue-on-error`，54 个文件未格式化）。
  **M3 已执行全量整形并翻转为阻塞门禁**。
- Nightly 中的基础设施拉起依赖 `docker compose --profile core`，该 profile 由 **M6** 提供；
  检索评测脚本 `eval/run_eval.py` 由 **M2** 提供。两者在 M1 阶段均做了缺失守卫，不会导致 Nightly 变红。

### 已知技术债（M2 显式记录，后续里程碑消化）

- 评测集为**构造 / 脱敏样例**，且仓库无 `doc/` 素材目录；`relevant_chunk_ids` / `grade` 为假设性标注，
  待真实文档入库后需按实际 chunk_id 重新标注（诚实声明，见 `eval/golden_queries.jsonl` 头注释）。
- 所有检索指标（Recall / MRR / nDCG）**暂无实测值**，`data/index_registry.json` 的 eval 字段全部为 `null`，
  待本地起 Milvus + 建索引 + 跑 `run_eval.py` 后回填（方案 §13「所有数字必须实测后填写」）。
- `config_hash` 原退化为 M2 硬编码基线快照；**M3 已落地 `retrieval.yaml` / `rerank.yaml`，实测确认
  `compute_config_hash()` 已自动切换为读 yaml 内容**（硬编码基线快照仅作为 yaml 缺失时的兜底）。
- 索引 alias（`product_manual_current`）零停机切换为方案 P2 可选项，M2 未落地。

### 已知技术债（M3 显式记录，后续里程碑消化）

- 剩余 ruff ignore 为**非自动修复**存量告警（E722 1 / F403 6 / F405 18 / F811 1 = 26 处），
  需人工重构（显式 import 替代 star import、补具体异常类型、消除重复定义）后逐条收窄。
- `retrieval.yaml` 的 `channels` 超时字段当前仅声明未消费（逐路 timeout 由 M6 `fanout.py` 落地）；
  `rerank.yaml` 的 `batch_size` / `max_concurrency` 同理（M6 Semaphore/batch 落地）。
- RRF 权重当前仅 embedding / hyde 两路生效；kg / web 路接入融合后需在 `weights` 中补对应通道。

### Added（M4：OTel 全链路追踪，方案 §8）

- **OTel 追踪基础设施** `app/core/tracing.py`（新建）：基于 `opentelemetry-sdk` / `opentelemetry-api`
  的懒导入封装，提供 `init_tracing()`（**幂等**）、`get_tracer()`、`start_span()` context manager、
  `@traced_span()` 装饰器、`generate_request_id()`（uuid4 hex 前 12 位）、`user_query_hash()`
  （sha256 前 16 位）。**no-op 降级铁律**：未显式 init（endpoint 为空 / 未启用 / 未装 SDK）时，
  所有 span 调用走 no-op、零性能损耗、绝不抛异常 —— 本地无 collector、CI 无 OTel 也全绿。
- **统一 span 属性**：所有 span 自动携带 `config_hash`（与 `run_eval.compute_config_hash` 同口径）、
  `collection`（milvus_config.chunks_collection）、`request_id` / `user_query_hash`（每请求经
  contextvars 注入，并发请求互不污染）—— trace 直接可归因到配置、索引版本与请求（方案 §7.5 / §8.2）。
- **检索链路 9 类 span 埋点**（只加 span 包裹 / 属性注入，不改变任何节点逻辑与返回值）：
  `retrieval.rewrite`（item_name_confirm 的 query 改写，original_len / rewritten_len）、
  `retrieval.embedding`（dense_w / sparse_w / hits / timeout_s）、`retrieval.hyde`
  （enable_hyde / hyde_doc_len / hits）、`retrieval.kg`（entities_n / hits，**如实标注当前为
  占位实现**）、`retrieval.web`（hits / timeout_s）、`ranking.rrf`（k / weights / in_n / out_n）、
  `ranking.rerank`（in_n / out_n / dynamic_topk / gap_ratio / gap_abs / fallback_used）、
  `llm.generate`（model / answer_len）、`request.total`（根 span：request_id / user_query_hash /
  session_id）。**未找到对应节点的（如 rewrite/kg/web 均为既有真实节点）如实记录，不凭空造节点。**
- **导入管线可选埋点**（顺手补齐）：`ingest.pdf_to_md` / `ingest.document_split` /
  `ingest.embedding` / `ingest.import_milvus`（chunks_n / md_len 属性）。
- **配置接入**：`.env.example` 增 `OTEL_EXPORTER_OTLP_ENDPOINT`（默认空 → no-op）、
  `ZHANGUI_SERVICE_NAME`（默认 zhanggui-zhiku）、`ZHANGUI_TRACE_ENABLED`（默认 false，
  置 true 且 endpoint 非空才真实导出）；web 入口 `app/main.py` 的 `create_app()` 与
  `eval/run_eval.py` 的 `main()` 均调用 `init_tracing()`（幂等，环境未配时 no-op）。
- **响应头 X-Trace-Id**（方案 §8.3）：`/query` 返回 `X-Trace-Id` 请求级 trace id，
  流式后台任务与响应头共用同一 request_id，便于按 trace_id 排障。
- **可选 extra 依赖**：`pyproject.toml` 增 `[project.optional-dependencies] tracing =
  ["opentelemetry-api>=1.24", "opentelemetry-sdk>=1.24"]`（2026-06 实测稳定版 1.44.0），
  **核心依赖树不膨胀**；已执行 `uv lock` 同步锁文件（同时修复 M1 遗留的锁文件 version 漂移
  1.0.0 → 1.1.0，`uv lock --check` 现为全绿），CI `uv sync --frozen` 不受影响。
  真实 OTLP 导出需额外安装 `opentelemetry-exporter-otlp-proto-grpc` 或 `-http`（懒导入，缺包自动 no-op）。
- **单测** `tests/unit/test_tracing.py`（15 个用例）：no-op 降级（start_span / 装饰器 / get_tracer
  不抛、不吞异常、不改返回值）、内存 exporter 真实 span（统一属性注入）、request_id 格式、
  user_query_hash 稳定、幂等 init（重复 init 不重复建 exporter）、空 endpoint 强制 no-op；
  真实 SDK 用例 `skipif` 守卫，CI 无 OTel 也全绿，**不连真实 collector**。

### 已知技术债（M4 显式记录，后续里程碑消化）

- 本地/CI 无 OTel Collector，**真实 OTLP 导出路径未实跑**（单元测试用 InMemorySpanExporter 验证）；
  Jaeger 部署走 `docker-compose --profile obs`（方案 §8.3）属 **M6** 落地，届时需补真实端到端 trace 验证。
- `doc/` 已落真实素材但环境未就绪未入库（`eval/golden_queries.jsonl` 仍为构造 / 脱敏标注，
  待真实文档入库后按实际 chunk_id 重新标注 —— 见 M2 技术债）。
- OTLP exporter 包（`opentelemetry-exporter-otlp-proto-grpc/http`）不在 tracing extra 内，
  真实导出需手动安装；`init_tracing` 已做懒导入 + 缺包自动 no-op 降级。
- 检索链路当前为**同步 LangGraph invoke**，`request_id` 经 contextvars 在单请求内传递；
  `retrieval.web` 的 `timeout_s` 取 `retrieval.yaml channels.web.timeout_s`（M6 fanout 落地后生效，
  当前 MCP 连接自身超时为 300s 硬编码）；`retrieval.kg` 为占位实现，span 属性如实标注 hits=0。
- `ranking.rerank` 的 `fallback_used` 为**启发式探测**（输出非空且全部 score==0.0 判定为降级），
  与节点既有降级行为一致，但非精确标记（真实分数恰全为 0.0 的极端情况会误判，概率极低）。

### Added（M5：入站安全护栏，方案 §9）

- **API Key 鉴权**（`app/api/middleware/security_guards.py`）：新配置 `ZHANGUI_API_KEY`
  （.env.example 已登记；**为空 → 鉴权关闭**，向后兼容既有行为）。请求头 `X-API-Key`
  或 `Authorization: Bearer <key>` 与配置比对（`secrets.compare_digest` 防时序攻击）；
  缺失/不匹配 → **401** `{code, msg, request_id}`（不泄露内部细节）。
  免鉴权路径：`/health`（探针）、`/chat.html`、`/import.html`（静态页）、`/stream/...`
  （SSE 经 EventSource 无法携带自定义头，README/文档说明为已知限制）。
- **入站 rate limit**（复用滑动窗口思路，新增**拒绝式**限流器
  `app/utils/inbound_rate_limit_utils.py`，区别于出站阻塞式
  `rate_limit_utils.apply_api_rate_limit`）：按 client（优先 X-API-Key sha256，其次客户端 IP）
  + 全局双层滑动窗口，默认 20 req/min/client + 500 req/min 全局（`ZHANGUI_RATE_LIMIT_PER_CLIENT`
  / `ZHANGUI_RATE_LIMIT_GLOBAL` / `ZHANGUI_RATE_LIMIT_WINDOW_S` 可 env 覆盖）；
  超限 → **429** + `Retry-After`（按窗口最早请求滑出时间计算）。
- **输入长度护栏**：`query` 字段上限 512 字符（Pydantic 强制，超限 **400**，错误信息含
  当前长度/上限）；历史轮数上限 `ZHANGUI_MAX_HISTORY_ROUNDS`（默认 20，入站 history 字段
  超限截断保留最近 N 轮）；`/history` 查询 `limit` 上限 200；请求体大小上限
  `ZHANGUI_MAX_BODY_BYTES`（默认 64KB，超限 **413**，最廉价 DoS 防护）。
- **错误脱敏**（`app/api/errors.py` + `app/utils/error_response_utils.py`）：对外错误响应统一
  `{code, msg, request_id}`，msg 不含堆栈 / 内部路径 / 密钥；内部异常详情仅入服务端日志。
  注册全局异常处理器（HTTPException / RequestValidationError / 未捕获 Exception），
  并修复既有泄露点：`/history` 500 不再回传异常原文、chat.html 404 不再回传绝对路径。
- **与 M4 OTel 打通**：`SecurityGuardsMiddleware` 在路由/根 span 之前生成 request_id 并
  `set_request_context`（新增 `tracing.get_request_id()`），401/429/400/413 响应与正常响应
  均带 `X-Trace-Id`，body 内 `request_id` 与响应头一致可追踪；`/query` 复用 middleware
  注入的 request_id，与后台任务共用同一 trace。
- **单测** `tests/unit/test_security_guards.py`：纯逻辑用例（错误体格式 / 限流器阈值与窗口 /
  按 key 隔离 / 线程安全 / 鉴权 key 提取与 client key 解析 / 豁免路径 / 校验文案格式化，
  无 fastapi 依赖也全绿）+ web 集成用例（最小 ASGI 应用验证 401/429/413/health 免鉴权/
  鉴权关闭语义/X-Trace-Id 一致性，`skipif` 守卫，**不连真实服务**）。

### 已知技术债（M5 显式记录，后续里程碑消化）

- **入站限流为进程内实现**（线程安全 dict），多副本 / 多 worker 部署时各实例限流独立，
  需外置共享存储（如 Redis）才能全局生效 —— 当前为诚实声明，单机单进程语义正确。
- 本地 venv 无 fastapi/starlette（`uv sync` 安装全量依赖后 CI 可跑 web 集成用例），
  M5 的 web 集成单测在无 web 依赖环境自动 skip，纯逻辑用例始终全绿。
- `ZHANGUI_API_KEY` 启用后，`/stream`（SSE）与静态页面按设计免鉴权；SSE 生产若需鉴权
  建议改用同源 + 会话态或 TLS 下 token 查询参数（README 口径已说明）。
- 当前检索管线历史来自 MongoDB（`node_item_name_confirm` 服务端 `limit=10` 已兜底），
  入站 `history` 字段为兼容/预留（方案 §9 ChatRequest 设计），超限截断后透传；
  后续若启用客户端 history 需在管线内消费。
- 限流器内存治理 `_maybe_sweep` 曾因"空桶恒为空"缺陷而失效（QA D1：长期运行 + 大量不同
  client/IP 时 `_buckets` 无界增长），已修复为按"**最近一次请求滑出窗口**"清理空闲桶
  （活跃桶不误删），并补 3 条 sweep 回归单测。

### Added（M6：部署优化 + 水平扩展，方案 §10 + 里程碑 M6）

- **fan-out 超时隔离**（§10.3，核心）：新建 `app/query_process/agent/fanout.py`。
  现状核查：四路召回（embedding / hyde / kg / web）已由 LangGraph 并行分支**并发**执行，
  **不重写架构**；在其上补「逐路超时 + 失败降级 `return {}` + 异常路径 span 埋点」。
  `guarded_call` 在线程池（有界 8）中执行单路节点并施加超时，超时 / 异常返回 `{}`
  （空状态更新），单路失败不拖垮整体（timeout / retry / fallback 语义，不写熔断）；
  `wrap_channel_node` 消费 M3 预留的 `retrieval.yaml channels.*.timeout_s`
  （embedding 1.5 / hyde 2.5 / kg 1.0 / web 3.0），`enabled=false` 的路直接跳过；
  `main_graph.py` 四路节点注册改走 wrap。说明：检索图当前为**同步** `query_app.invoke()`
  （含 FastAPI 事件循环内同步调用），故用线程级 guard 而非方案示例的 asyncio.gather 形态，
  语义等价；线程级超时无法真正中断被放弃线程（同步代码不可中断），由下游超时兜底释放。
- **web 路 MCP 超时配置驱动**：`node_web_search_mcp` 连接 / 读取超时由硬编码 300s 改为
  `retrieval.yaml channels.web.timeout_s`（默认 3s）—— 外层 guard 负责不拖垮整体，
  MCP 内部超时负责及时释放被放弃的线程。
- **reranker 并发闸门**（§10.4）：新建 `app/utils/rerank_concurrency.py`
  （`threading.BoundedSemaphore` 封装），`node_rerank.step_2_rerank_docs` 的
  `compute_score` 调用包裹在闸门内，并发模型推理数 ≤ `rerank.yaml max_concurrency`
  （默认 8，M3 预留）；超出闸门**排队而非丢弃**。说明：检索图同步执行（节点在线程中），
  用线程级信号量，语义与方案 `asyncio.Semaphore + run_in_threadpool` 等价；
  eval 直跑同步逻辑不受影响（`--skip-rerank` 路径不触闸门）。
- **部署形态**（§10.5 + M6 部署优化）：`docker-compose.yml` 落地
  - profile 分层：`core`（milvus / mongo / minio / minio-init / neo4j 基础设施）、
    `obs`（jaeger 链路追踪，默认不拉起）；web 无 profile 始终拉起；
  - web healthcheck（`/health/live` 存活探针，M6 新增；旧 `/health` 保留兼容）+
    `/health/ready` 就绪探针（Milvus 连通判据，未连则 503，供 LB / compose 摘除）；
  - web `deploy.resources.limits`（cpus 2.0 / memory 2G）、milvus limits（4G）；
  - web 显式 `command --workers 1`（容量模型：模型进程内加载，N worker = N 份模型副本，
    GPU 场景 workers=1~2，**水平扩展优先加 replica 而非加 worker**，见 compose 注释）；
  - minio / minio-init 镜像锁版（消除 `latest`，M1 识别项）；
  - `deploy.replicas` 仅注释示范（K8s / 真实编排生效，Compose 单机无效）。
- **纯检索端点 `/api/v1/retrieve`**（§10.6 压测档前置）：召回 → RRF → 重排，不含 LLM 生成，
  与线上节点同一函数 / 同一配置（RRF 读 retrieval.yaml）；`/query` 端到端仍为唯一生成入口
  （方案示例 `/api/v1/chat` 未实现，压测直打真实端点）。
- **Nightly 守卫更新**：`zhiku-nightly.yml` 删除 M1 的 grep 存在性守卫，直接
  `docker compose --profile core up -d --wait`（M6 落地）。
- **压测框架**（§10.6，不预填数字）：`benchmark/locustfile.py`（`/retrieve` 场景目标
  QPS≥100 / P95<3s / err<1% 写入 docstring；`/query` 端到端注明外部 LLM 限流是硬天花板，
  不承诺 100 QPS；`between(0.5, 2.0)` WaitTime；X-API-Key 支持）+ `benchmark/README.md`
  （运行方式 / 分档目标空模板 / 瓶颈定位清单）。
- **M5 探针豁免扩展**：`security_guard_utils.is_health_path` 将 `/health/live`、
  `/health/ready` 一并豁免鉴权 / 限流（否则启用 ZHANGUI_API_KEY 后容器探针会被 401）。
- **单测** `tests/unit/test_concurrency.py`（新建）：guarded_call 正常透传 / 超时返回 {} /
  异常返回 {} / 非 dict 归一 / 四路混合失败聚合语义；wrap_channel_node 读配置与 enabled 开关；
  Semaphore 并发数 ≤ max_concurrency（mock compute_score + 多线程）；/health 子路径豁免回归。
  全部为轻量纯模块，本地 venv（无 fastapi/torch）可全绿。

### 已知技术债（M6 显式记录，后续里程碑消化）

- **压测数字待真实环境实测**：`benchmark/README.md` 结果表为空模板，禁止预填；
  单机 docker compose 压测数据偏保守，跨 replica 压测需云上机器（方案 §10.6 / §13）。
- **`deploy.replicas` 仅注释示范**：Compose 单机不生效（K8s / 真实编排才消费），
  水平扩展优先加 replica 而非加 worker 的结论需压测验证（M7）。
- **线程级 guard 无法真正中断被放弃线程**：同步节点代码不可中断，超时后线程仍会跑完
  并由下游客户端超时（如 web 路 MCP 3s）兜底释放；若图改为 `ainvoke` 异步形态可平滑
  切换 asyncio.gather + wait_for（§10.3）。
- **默认拉起命令变为 `docker compose --profile core up -d --build`**：因 Compose profile
  语义（web 依赖的 core 服务在未启用 profile 时，plain `up` 会报 `service X is required by
  web but is disabled. Can be enabled by profiles [core]`），已在 compose 头部注释说明。
- **`/health/ready` 以 Milvus 为就绪判据**：Neo4j 驱动 `verify_connectivity` 无轻量超时，
  暂未纳入避免探针挂起，后续可按需扩展。
- **SSE 路径并发未做专门控制**：`/stream` 多连接无独立并发上限（仅受 M5 入站限流约束），
  若作为生产 SSE 出口需补连接数 / 会话级限制。

### Added（M7：压测容量与交付闭环，方案 §12 M7 + §10.6）

- **压测 SOP 闭环**（升级 `benchmark/README.md`）：前置条件清单（Docker / 模型 / 索引 /
  golden / LLM Key / 鉴权 Key）；一键命令可执行形态（`docker compose --profile core up -d
  --build` → `locust --headless -u 20 -r 5 -t 10m --csv benchmark/runs/<run_id>`）；
  结果收集（stats / stats_history / failures CSV + HTML）；**结果回填闭环**：分档表标注
  `实测：run_id/日期` → `eval/run_eval.py` 回填 `data/index_registry.json` eval 字段 →
  `eval/README.md` 实验索引表 → CHANGELOG「实测」条目 → `benchmark/CAPACITY.md` 结论列，
  杜绝"编造数字进文档"。
- **容量模型与瓶颈定位**（新建 `benchmark/CAPACITY.md`）：容量模型表（N worker = N 份模型
  副本，GPU 场景 workers=1~2，水平扩展优先 replica，呼应 M6 compose `--workers 1`）；
  **瓶颈定位决策树**（QPS 上不去按序查：reranker → LLM → Milvus → Neo4j → web 路 MCP，
  每节点给「症状 → 排查命令 → 缓解手段」，配合 M4 OTel span 口径）；
  压测达标判据空表（/retrieve QPS≥100 / P95<3s / err<1%；/query 注明不承诺 100 QPS，
  分 TTFT/total）。
- **环境就绪验收清单**（新建 `docs/verification-checklist.md`）：8 项按序验收
  （①compose core 全 healthy ②`/health/live` 200 / 停 Milvus 后 `/health/ready` 503
  ③`/api/v1/retrieve` 真实查询 200 ④ZHANGUI_API_KEY 探针豁免 + 无 key/错 key 401 + Bearer 200
  ⑤入站限流 20/min → 429 + Retry-After ⑥fan-out 隔离：停 Neo4j 或调小 kg 超时 → `/query`
  仍完成 ⑦OTel：obs profile + OTEL_ENDPOINT → Jaeger 可见 request.total + 8 子 span
  ⑧按 benchmark 压测并回填），每项「预期结果」列 + 「实际结果（待填）」列；
  通过后在 CHANGELOG 记录「环境验收通过（实测）」。
- **README 生产化总览**：新增「10. 生产化改造（v1.1.0）」章节（M1~M7 一句话总览表 +
  关键文件索引 + M6 起运行方式 `--profile core` + 诚实边界），原 License 顺延为 §11。

### 已知技术债（M7 显式记录，后续里程碑消化）

- **真实评测 / 压测数字仍为待实测**：`eval/` 指标、`benchmark/` 分档表、
  `docs/verification-checklist.md` 实际结果列、`data/index_registry.json` eval 字段
  全部为空模板 / null；本地无 Docker/Milvus/GPU，需真实环境按 checklist ⑧ 实测后回填。
- `doc/` 真实素材已就位但环境未就绪未入库，golden 集待真实文档入库后按实际 chunk_id
  重新标注（M2 技术债延续）。
- 压测分档结论（reranker/LLM/Milvus 瓶颈定位）需实测数据支撑后才能写入 CAPACITY.md
  结论列与简历话术（方案 §11 量化结果一律待实测填写）。

### Added（M8：硅基流动 API 模式，方案 §10.5）

- **embedding / rerank 双模式开关**（向后兼容铁律）：新增 `EMBEDDING_MODE` / `RERANK_MODE`
  （默认 `local`，行为与 M7 及之前完全一致；`api` 时走硅基流动 OpenAI 兼容 API）与
  `SILICONFLOW_API_KEY` / `SILICONFLOW_BASE_URL` / `SILICONFLOW_EMBEDDING_MODEL` /
  `SILICONFLOW_RERANK_MODEL` 四个配置项，全部 env 可覆盖并登记 `.env.example`；
  未知模式值回退 `local`（不破坏既有部署）。
- **api 模式稠密向量**：`app/lm/siliconflow_client.py`（仅依赖标准库 urllib，不引入第三方
  网络依赖）`POST {BASE_URL}/embeddings`，返回 1024 维稠密向量并**本地 L2 归一化**
  （API 不保证归一化；与 local 模式 BGE-M3 产物语义对齐，适配 Milvus dense COSINE/IP）；
  批量默认 16 条/次（上游节点仍按 5 条/批喂入，api 端一次多传）。
- **api 模式稀疏向量（B 路线）**：新增 `app/lm/sparse_vectorizer.py`（纯函数、零第三方依赖）
  ——中文重叠 bigram + 短整词、英文/数字词元（小写）、词频 TF 权重、L2 归一化；
  token→id 用 `hashlib.md5` 前 8 位 hex 掩码到 int32 正区间（**跨进程稳定**，严禁内置 `hash()`）；
  导入与检索共用同一实现（同一拼接文本），保证 doc/query token 空间一致；
  `generate_embeddings` api 模式返回结构与 local 完全一致 → 业务节点**零改动**。
- **api 模式 rerank**：`ApiReranker.compute_score(sentence_pairs)` 与 FlagReranker
  **同签名 / 同语义**（分数越高越相关、返回顺序与输入一致，含 API 乱序按 index 重排、
  多 query 按位置回填）；`POST {BASE_URL}/rerank`，`get_reranker_model()` 按 `RERANK_MODE`
  返回本地或 API 实例 → `node_rerank.py` **零改动**。
- **api 路径懒导入**：`embedding_utils.py` / `reranker_utils.py` 顶层不再 import
  pymilvus.model / FlagEmbedding（改为函数内懒导入），api 模式在**裸 venv（未安装
  FlagEmbedding / pymilvus / torch 等重型依赖）可导入、可单测**；`get_bge_m3_ef()` 在
  api 模式返回占位实例（业务节点仅校验非 None，真实向量走 API），`node_bge_embedding.py`
  零改动可跑通。
- **新增单测**（不依赖真实 key / 网络，mock `_post_json`）：`tests/unit/test_sparse_vectorizer.py`
  （稳定 id / md5 定义断言 / L2 归一化 / 中英混合 / 空文本边界）、
  `tests/unit/test_embedding_api_mode.py`（api 返回结构、稠密归一化、乱序重排、local 不受影响、
  缺 key / 缺字段 / 数量不匹配报错）、`tests/unit/test_rerank_api_mode.py`（分数解析、顺序一致、
  多 query 分组、空入参、缺字段报错）。全量 `tests/unit` 由 161 → **192 passed**。

- **压测结果（api 模式实测，2026-08-06）**：`locust -f benchmark/locustfile.py -u 50 -r 5 -t 10m`，
  `/retrieve` QPS 0.52 / P95 243s / 0 错误率；`/query` QPS 0.13 / P95 233s / 0 错误率。
  瓶颈为外部 SiliconFlow API 排队（EMBEDDING_MODE=api / RERANK_MODE=api，稠密向量与 rerank
  均走远程 API），与 M6 §10.6「全部自有组件 QPS≥100 / P95<3s」目标冲突；
  改目标口径为「api 模式下自有服务处理延迟（去外部 API 后）待 local 模式验证」。
  压测期间 `ZHANGUI_RATE_LIMIT_PER_CLIENT` 临时调至 5000/50000（默认 20/500），跑完恢复。
  `benchmark/locustfile.py` 修复 `--api-key` 参数注册（locust 2.x `events.init_command_line_parser`）。

### 已知技术债（M8 显式记录，后续里程碑消化）

- **api 模式稀疏向量为本地词权重近似**：硅基流动 embeddings API 不返回稀疏向量，
  `sparse_vectorizer` 以「中文 bigram + 词频 + L2 归一化」近似 BGE-M3 原生 SPLADE，
  非模型原生语义稀疏，检索效果可能与 local 模式存在差异；对稀疏路效果敏感的场景
  建议 local 模式或用评测管线对比（README §10.5 诚实说明）。
- **批量 / 重试为简单实现**：embedding 固定 16 条/批、rerank 固定 64 条/批；
  429/5xx/网络异常仅简单重试 2 次（退避 0.5s 起），**无熔断、无指数退避抖动、无按批次
  部分成功恢复**；高 QPS 场景可能触发上游限流，需按实测补充自适应退避与熔断策略。
- **api 模式与 local 模式产物混用风险**：两种模式产物（稠密均已归一化，但稀疏语义不同）
  若写入同一 Milvus 集合会造成稀疏路污染；建议不同模式使用不同集合（M2 集合版本化命名
  已含 embedding_model 维度，可结合 `SILICONFLOW_EMBEDDING_MODEL` 区分）。

---

## [1.0.0]

> 项目初始基线（未生产化）。原始发布日期未在仓库中记录，故此处不标注日期。

本版本为项目的初始状态，已具备以下能力（非本次改造产出）：

- 索引侧 `app/import_process/`：PDF→MD→标题感知切分→BGE-M3 稠密+稀疏向量化→Milvus 入库的完整
  LangGraph 管线，按 `item_name` 幂等覆盖。
- 检索侧 `app/query_process/`：LangGraph 编排四路并发召回（embedding / HyDE / 知识图谱 / 联网搜索），
  加权 RRF 融合 → BGE 重排 → 断崖式动态 TopK → LLM 生成。
- 工程侧：`Dockerfile` + `docker-compose.yml` 容器化、`uv.lock` 依赖锁、`app/conf/` 分模块配置、
  `tests/unit/` 5 个单元测试、`README.md` 与 `docs/` 架构文档。

尚不具备：CI/CD、版本治理、质量评测、链路追踪、入站安全护栏。
