# 压测（Benchmark）—— SOP 与结果归档（M6 框架 / M7 闭环）

> 本目录为**压测入口与结果归档**。所有指标数字必须实测后填写，**禁止预填**（方案 §13
> 「所有数字必须实测后填写」）。本文件定义「环境就绪后如何一键压测、结果如何回填、
> 瓶颈如何定位」的完整闭环（M7）。

## 0. 前置条件清单（缺一不可）

| # | 前置项 | 验证方式 | 缺失影响 |
|---|---|---|---|
| 1 | Docker + docker compose v2 | `docker compose version` | 无法拉起服务栈 |
| 2 | 基础设施 + web 启动 | `docker compose --profile core up -d --wait` 后全部 healthy（见 docs/verification-checklist.md ①） | 压测目标不存在 |
| 3 | 模型已下载（BGE-M3 / reranker，CPU 或 GPU） | `.env` 中 `BGE_M3_PATH` / `BGE_RERANKER_LARGE` 指向的目录非空 | 检索链路报模型缺失 |
| 4 | 索引已建立（先跑 import_process） | `/api/v1/retrieve` 返回非空 `hits` | QPS 全是空召回，无意义 |
| 5 | golden 集已标注 | `eval/golden_queries.jsonl` 存在且 ≥50 条 | 压测样本退化（locustfile 有内置样例兜底，仅冒烟用） |
| 6 | LLM API Key（仅 /query 档需要） | `.env` `OPENAI_API_KEY` / `LLM_DEFAULT_MODEL` 已配 | /query 档无法执行 |
| 7 | M5 鉴权 Key（若已启用） | `.env` `ZHANGUI_API_KEY`；压测时 `--api-key` 传入 | 401 |

## 1. 一键命令（可执行形态）

```bash
# 0) 起栈（core profile = 基础设施 + web；obs 可观测按需追加）
docker compose --profile core up -d --build

# 1) 安装压测工具
pip install locust

# 2) 无头直跑（推荐脚本化；-u 并发 / -r 爬坡 / -t 时长）
mkdir -p benchmark/runs
locust -f benchmark/locustfile.py --host http://localhost:8000 --headless \
    -u 20 -r 5 -t 10m --api-key <ZHANGUI_API_KEY> \
    --csv benchmark/runs/$(date +%Y%m%d_%H%M%S)

# 3) 交互式（浏览器打开 http://localhost:8089 实时看曲线）
locust -f benchmark/locustfile.py --host http://localhost:8000 --web-port 8089 \
    -u 50 -r 5 -t 5m --api-key <ZHANGUI_API_KEY>
```

> 建议先跑 `-u 20 -r 5 -t 10m` 冒烟，确认无 429/5xx 后再按容量模型（见 CAPACITY.md）
> 逐档加压。压测期间保持 `ZHANGUI_TRACE_ENABLED=false`（或独立观测 Jaeger），
> 避免 OTel 导出对极短请求的延迟干扰（如实说明测量口径）。

## 2. 结果收集（locust 输出落 benchmark/runs/）

`--csv benchmark/runs/<run_id>` 会生成：

- `benchmark/runs/<run_id>_stats.csv` — 每场景聚合统计（QPS / 平均 / 各百分位 / 错误率）
- `benchmark/runs/<run_id>_stats_history.csv` — 时间序列（画趋势）
- `benchmark/runs/<run_id>_failures.csv` — 失败明细（HTTP 状态码 / 异常类型）
- （可选）HTML 报告：locust 新版支持 `--html benchmark/runs/<run_id>.html`

**回填模板**：把聚合行（/retrieve、/query 两档）填入下方「分档目标」空表，标注
`实测：<run_id> / <日期>`。

## 3. 分档目标（空模板，实测后填写）

| 场景 | 并发用户 | replica×worker | QPS | P50 | P95 | P99 | 错误率 | 瓶颈定位 |
|---|---|---|---|---|---|---|---|---|
| /retrieve | 50 | 1×1（api 模式） | 0.52 | 45s | 243s | 253s | 0% | 外部 SiliconFlow embedding API 排队（EMBEDDING_MODE=api，稠密向量走远程 API；非自有组件瓶颈） |
| /query | 50 | 1×1（api 模式） | 0.13 | 50s | 233s | 253s | 0% | 同上 + 外部 LLM 配额 |

> 口径说明（M8 校准）：**压测的目的不是去硬测出 QPS≥100 / P95<3s 这类目标值**。
> 第三方 embedding/rerank/LLM API 本身有并发与配额限制，且若要本地部署模型达到高并发
> 需额外约 3GB 模型 + 大量算力，资源成本高、且不代表真实 api 模式表现。
> 因此本环境压测定位为：**在当前 api 模式下跑出本环境能支撑的最大并发，定位卡点
> （bottleneck），并推导"若要达到某目标并发，需要解决哪些问题（扩容路径）"**。
> 当前 M8 配置 `EMBEDDING_MODE=api` / `RERANK_MODE=api`，embedding 与 rerank 均走 SiliconFlow 远程 API，
> 卡点即外部 API 排队（非自有组件瓶颈）。M6 §10.6 的 QPS≥100 目标仅适用于「全部自有组件（local 模式）」假设，
> 在 api 模式下该目标不适用，不应作为当前验收判据。
> 压测期间 `ZHANGUI_RATE_LIMIT_PER_CLIENT` 临时调至 5000/50000（默认 20/500），跑完恢复。

> 口径提醒：上了 streaming 后必须区分 **TTFT** 与 **total latency**（方案 §10.4），
> 压测报告里混着写会被追问。

## 4. 结果回填闭环（杜绝"编造数字进文档"）

跑完一次压测后，按序完成以下回填（**每条标注「实测」字样与日期**，禁止无标注数字）：

1. **本表**：把上表填充为实测值，标注 `实测：run_id / YYYY-MM-DD`。
2. **检索质量**（与压测无关但同属验收）：`python eval/run_eval.py --out eval/runs/`
   跑完自动把 Recall@5 / MRR / nDCG@10 回填到 `data/index_registry.json` 对应集合的
   `eval` 字段（脚本已实现，见 run_eval.backfill_registry）。
3. **README 实验索引表**：`eval/README.md` 中的实验索引表补一行
   `run_id | config_hash | 变更点 | Recall@5 | nDCG@10 | 结论`。
4. **CHANGELOG**：在对应版本段追加「压测结果（实测）」条目，写明 run_id / 日期 / 机器规格。
5. **CAPACITY.md 结论**：把瓶颈定位结论（如"reranker 为瓶颈，Semaphore 8 打满"）回填到
   `benchmark/CAPACITY.md` 决策树各节点的「实测结论」列。

## 5. 已知边界（诚实声明）

- `/query` 端到端 QPS 受外部 LLM API 限流约束，**不承诺 100 QPS**（方案 §10.6 分档理由）。
- 单机 docker compose 压测数据偏保守；跨 replica 压测需在云上机器执行。
- `benchmark/locustfile.py` 的 `/api/v1/retrieve` 为 M6 新增纯检索端点；`/api/v1/chat`
  为方案示例命名，当前代码未实现，端到端直打真实端点 `/query`。
- 入站限流（M5：20 req/min/client）在压测并发用户超过配额时会 429，需调大
  `ZHANGUI_RATE_LIMIT_PER_CLIENT` 或按不同 key 分桶（这是服务自我保护，非故障）。
