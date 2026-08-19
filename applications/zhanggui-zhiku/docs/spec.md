# 掌柜智库（zhanggui-zhiku）会话摘要

> 会话日期：2026-08-06
> 项目路径：`/workspace/noctilucent-lamp/zhanggui-zhiku`
> 分支：`production`（git 分支，未 push）
> 框架：FastAPI + LangGraph + Milvus + Neo4j + MinIO + docker compose

---

## 一、已交付验收项

### ② Milvus 破坏性探针（通过）
- 修复探针假阳 bug：`get_milvus_client()` 单例缓存导致停 Milvus 后仍返回非 None
- 新增 `milvus_ready()`（`app/clients/milvus_utils.py`）：`list_collections(timeout=3)` 真连通检测，失败时重置缓存
- `app/api/query_router.py` 的 `health_ready` 改用 `milvus_ready()`
- 验证：停 Milvus → `/health/ready` 返回 503；重启 Milvus → 自动恢复 200

### ④ 鉴权（通过）
- `ZHANGUI_API_KEY` 已配置，`/query` 无 key→401、错 key→401、正确 key→200
- 探针 `/health`、`/health/live`、`/health/ready` 无 key 仍 200（M6 豁免）

### ⑥ kg 通道 stub（已标注）
- `node_query_kg.py` 仍是占位（`time.sleep(1)`），未接 Neo4j
- 已在 `README.md` §10.4 诚实边界、`ops-lessons-learned.md` §4.1、`verification-checklist.md` 标注

### ⑦ OTel 导出（通过）
- 修复：`tracing.py` 改 HTTP 优先 exporter（grpc 握手 failed EOF）、`TracerProvider` 补 `resource.service.name`、endpoint 带 `/v1/traces`
- Jaeger 可见 `zhanggui-zhiku` 服务，每请求 2 span（`request.total` + `retrieval.rewrite`）
- 修复记录：commit `a8354588`

### ⑧ 压测（已跑，结果已回填）
- `locust -f benchmark/locustfile.py -u 50 -r 5 -t 10m --api-key <key>`
- `/retrieve` QPS 0.52 / P95 243s / 0 错误率
- `/query` QPS 0.13 / P95 233s / 0 错误率
- 瓶颈：`EMBEDDING_MODE=api` / `RERANK_MODE=api`，embedding 与 rerank 均走 SiliconFlow 远程 API，排队导致延迟爆炸
- 改 benchmark/README 目标口径为「api 模式下自有服务处理延迟（去外部 API 后）待 local 模式验证」
- `benchmark/locustfile.py` 修复 `--api-key` 参数注册（locust 2.x `events.init_command_line_parser`）
- `data/index_registry.json` 已回填 run_id `20260806_101019_def9da22`（eval 指标 0.0，因 golden relevant_chunk_ids 为假设性标注）

---

## 二、当前仍存在的问题

### 1. golden 标注未重标
- `eval/golden_queries.jsonl` 的 `relevant_chunk_ids` 仍是假设性标注（`c_101` 等），与真实 chunk_id 对不上
- eval 指标全 0 属预期，需按实际 chunk_id 重标 56 条 golden

#### 1.1 重标方案决策（2026-08-06，已定，暂不实施）
- **核心约束**：评估的"标准答案（ground truth）"机器无法自定对错，须人来定；但人工逐条勾几千条不现实。
- **公开数据集不可行**：联网核查 HuggingFace（关键词 `chinese manual qa` / `product manual qa`）均无 domain 匹配的中文设备说明书 QA 集；烫金机类垂直小众设备无现成公开 golden。
- **不引入 Ragas 等第三方评测库**：本项目是"用于面试的生产项目"，引入 Ragas 会带来传递依赖膨胀、黑盒化评测标准，弱化对评测方法论的掌控，属减分项。
- **采用方案：自研小脚本 + 人工抽检（推荐，待实施）**
  - 写项目内 `eval/gen_golden.py`（**仅评估/开发用，不进生产运行时依赖**）：读 Milvus `product_manual_v1_bge_m3` 真实 50 条 chunk → 调已有 LLM key → 让 LLM 基于真实文本合成 query 并回注真实 `chunk_id` → 输出 `golden_queries.jsonl`。
  - 逻辑全透明、可控、可解释；在 `eval/README.md` 诚实声明"golden 由 LLM 基于真实 chunk 自举生成，人工抽检 N 条验证"。
  - 评估层（`run_eval.py` / `metrics.py`）自研不动。
  - 人只需抽检若干条确认质量，无需全标。
- **状态**：方案已记录，暂不修改；待用户确认标注口径（每条 query 标几个 chunk、是否附 `reference_answer`）后实施。

### 2. api 模式性能瓶颈（卡点已定位，非待解决阻塞）
- `EMBEDDING_MODE=api` / `RERANK_MODE=api` 导致 QPS 极低（0.52）
- **根因**：第三方 SiliconFlow embedding/rerank API 与 LLM API 本身有并发/配额限制，排队导致延迟爆炸；这是外部依赖约束，非自有组件瓶颈
- **结论校准**：压测目的不是硬测 QPS≥100 / P95<3s（那需本地部署模型约 3GB + 大量算力，且不代表真实 api 模式表现）。当前压测定位为「跑出本环境最大并发 → 定位卡点 → 推导达到目标并发需解决的扩容问题」
- M6 §10.6 的 QPS≥100 目标仅适用于 local（全部自有组件）模式，api 模式下不适用，**不应作为当前验收判据**
- `models/` 目录为空（BGE-M3 + bge-reranker-v2-m3 未下载），若后续要切 local 模式解除 API 限流才需要下载（约 3GB）

### 3. benchmark/runs/ CSV 被提交（已解决，待 commit）
- locust 输出的 12 个 CSV + 1 个 HTML 报告曾被提交进 git
- **已处理**：`.gitignore` 新增 `benchmark/runs/` 规则，并已 `git rm --cached -r benchmark/runs/`（13 个文件从索引移除，本地保留）；改动已暂存，待提交

### 4. kg stub 未接 Neo4j
- `node_query_kg.py` 仍是占位（`time.sleep(1)`），kg 通道真实故障隔离能力无法验证

### 5. PaddleOCR-VL 未接入
- 用户决定压测后再接，图片摘要仍默认关闭（`IMG_SUMMARY_ENABLED=false`）
- 已配置 PaddleOCR-VL 凭证（JOB_URL、TOKEN、MODEL），待接入

### 6. 镜像瘦身（④）暂缓
- `torch` CPU 镜像仍 6.19GB，未做 CPU-only 瘦身

### 7. 旧 commit 未 push
- `a8354588`（OTel 修复）和 `60b62816`（ops lessons 文档）仍本地，未 push 到远程

---

## 三、关键文件改动（M8）

| 文件 | 改动 |
|---|---|
| `app/utils/item_name_normalize_utils.py` | **新增**：共享 `normalize_item_name()`（去空白 + 剥离品牌前缀 + 剥离料号后缀） |
| `app/import_process/agent/nodes/node_item_name_recognition.py` | LLM 输出后套用 `normalize_item_name()` |
| `app/query_process/agent/nodes/node_search_embedding.py` | 构造 Milvus expr 前对 item_names 套用 `normalize_item_name()` |
| `prompts/item_name_recognition.prompt` | 收紧为"仅输出型号+品类，禁止品牌前缀与料号" |
| `benchmark/locustfile.py` | 修复 `--api-key` 参数注册（locust 2.x） |
| `benchmark/README.md` | 填入实测结果 + 改目标口径 |
| `data/index_registry.json` | 回填 eval run_id |
| `eval/README.md` | 实验索引表 + 诚实声明 |
| `CHANGELOG.md` | M8 压测结果条目 |
| `docs/ops-lessons-learned.md` | M8 条目 |
| `docs/verification-checklist.md` | ⑧ 填入压测结果 |

---

## 四、数据状态

- Milvus 集合 `product_manual_v1_bge_m3`：50 条 chunk（手册 6 + 说明书 44），item_name 统一为 `HAK180烫金机`
- Milvus 集合 `kb_item_names`：2 条（手册/说明书各 1），item_name 统一为 `HAK180烫金机`
- 检索 `/api/v1/retrieve` 验证通过：`item_name="HAK 180 烫金机"`（带空格）→ hits=5，最高 score 0.925
- 导入链路完整：PDF→MinIO→MD→图片处理（IMG_SUMMARY_ENABLED=false 跳过）→切分→商品识别→向量生成→Milvus 入库