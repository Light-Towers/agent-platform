# agent-platform 真实 LLM 数据端到端测试闭环

验证日期：2026-08-18
结论：**闭环通过（[PASS]）** —— 真实 LLM 通道打通，Postgres checkpoint 写读恢复验证成功，RAG 真实 embedding + rerank 重排主链路已闭环。
剩余 1 个非阻塞缺陷：后台长期记忆写入线程的 event-loop 错配（见 §5）。

> **2026-10-18 更新（opencode 通道复跑）**：① 模型 ID 已由下线的 `deepseek-v4-flash-free` 更正为 **`deepseek-v4.1-flash-free`**（本文所有命令/配置已同步）——用过期 ID 会得到无信息量的 `Unexpected server error`。② `Detect Abuse Traffic`(403) 是**免费层突发限流、非永久封禁**，降频即恢复，管线可容忍偶发单次限流。③ `opencode_gateway.py` 已修**错误吞掉**问题（此前真实上游错误被显示成空壳 `rc=1`），现在透出真实 message。详见 §2.3。④ nl2sql-service 已在真 PG+pgvector 下用真实 LLM 端到端跑通（正确 SQL + 正确答案）。⑤ **同日深挖（§9）**：403 只是第一级形态——持续高频后免费层会升级为 **IP 级硬封**（"abusive traffic from this IP address"，降频无效，需数小时~隔天恢复或换 IP）；免费层实为 **IP 级限额 ≈10 RPM / 1 RPS / 每日约 50 次，安全并发=1**，网关已加**全局串行闸 + 最小间隔**适配；另解一个高价值误判：**硅基账户余额归零时免费 embedding ID 也报 402**（免费 chat 仍可用）。

---

## 1. 环境准备

| 组件 | 状态 | 说明 |
|------|------|------|
| `.venv` (fastapi 0.141 / uvicorn 0.52) | ✅ | 已就绪 |
| `opencode` CLI | ✅ | `/root/.nvm/.../opencode`，`opencode models` 可列出含 `opencode/deepseek-v4.1-flash-free` 等的免费模型 |
| pgvector 容器 | ✅ | `pgvector/pgvector:pg16` @ `localhost:5433`，扩展 `vector 0.8.6` 已装 |
| opencode-gateway | ✅ | `scripts/opencode_gateway.py` @ `:8799`，`/health` → `{"status":"ok"}` |

### 1.1 启动命令（可复现）

```bash
# 1) pgvector 专用容器（解决历史卡点：本机 PG 无 pgvector 扩展）
docker run -d --name agent-platform-pg --restart unless-stopped \
  -p 5433:5432 \
  -e POSTGRES_USER=agent -e POSTGRES_PASSWORD=agent_platform_dev \
  -e POSTGRES_DB=agent_platform pgvector/pgvector:pg16
docker exec agent-platform-pg psql -U agent -d agent_platform -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 2) opencode 网关（后台、脱离 shell 会话存活）
cd /workspace/agent-platform
setsid .venv/bin/python scripts/opencode_gateway.py \
  --port 8799 --model opencode/deepseek-v4.1-flash-free > /tmp/opencode_gateway.log 2>&1 < /dev/null &

# 3) 验证
curl -s http://127.0.0.1:8799/health          # {"status":"ok","gateway":"opencode"}
```

### 1.2 `.env` 关键配置（已就位）

```
DATABASE_URL=postgresql://agent:agent_platform_dev@localhost:5433/agent_platform
VECTOR_DIM=512
LLM_API_KEY=<任意非空串>          # 任意非空串即可
LLM_BASE_URL=http://127.0.0.1:8799/v1
LLM_MODEL=opencode/deepseek-v4.1-flash-free
LLM_TIMEOUT=120                              # 免费模型冷启动慢，原 60 会超时
```

---

## 2. LLM 通道验证

### 2.1 网关 → opencode → 真实模型 往返

```bash
curl -s -X POST http://127.0.0.1:8799/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"opencode/deepseek-v4.1-flash-free","stream":false,
       "messages":[{"role":"user","content":"用10字解释量子计算"}]}'
# → {"choices":[{"message":{"content":"量子纠缠并行算。"}}],"usage":{...}}
# http_code=200, elapsed≈7s
```

### 2.2 通道真实性证明

`smoke_query_real.py` 第一轮真实 LLM 返回：

> 「证据表明知识库中未检索到任何相关内容……不过据我所知（非来自上述证据），**我是 deepseek-v4.1-flash-free（opencode/deepseek-v4.1-flash-free）**。」

这是模型**真实自报身份**，启发式分支不可能产出此类内容 → **确认走真实 LLM，非启发式**。

### 2.3 上游错误辨析（2026-10-18 深挖，纠正早期误判）

早期把 `Unexpected server error` 当成"瞬时服务端错误"是**误判**。实测（`opencode run --format json` 直接跑 + 经网关）辨明三类错误，根因各不相同：

| 现象 | 真实根因 | 处置 |
|------|---------|------|
| `Unexpected server error. Check server logs...` | **模型 ID 不存在**——配置的 `deepseek-v4-flash-free` 已下线，现为 `deepseek-v4.1-flash-free`（`opencode models` 可查）。过期 ID → 上游通用 500 | 改模型 ID（本文已全部更新为 `.1`） |
| `403 FreeTierError: Detect Abuse Traffic` | **免费层突发限流**（`opencode.ai/inference` 反滥用），数据中心 IP + 短时间多次调用触发。**非永久封禁**——间隔一会儿复测即恢复 | 降调用频率；管线对单次限流**优雅容忍**（nl2sql 单查询 ~4-5 次 LLM 调用中偶发 1 次被限流，仍产出正确答案） |
| `github-copilot/*` → `400 Personal Access Tokens are not supported` | `GITHUB_TOKEN` 是 PAT，Copilot 端点只要 OAuth token | 用 opencode 免费模型路即可；要用 Copilot 需 OAuth token |

**网关错误可见性（已修，commit 见仓库）**：`opencode_gateway.py` 此前 `stderr=DEVNULL` 且不解析 opencode 的 `type=="error"` 事件，上游真实错误被吞成 `[opencode error rc=1: ]` 空壳——这正是早期排查看不到真实原因的原因。现：捕获 stderr + 解析 error 事件，真实 message 透出到响应 content 并落网关日志（`[opencode-gateway] ...`）。

**nl2sql 真实 LLM 端到端（2026-10-18，真 PG+pgvector）**：修模型 ID 后单查询全链跑通——LLM 生成 `SELECT COUNT(*), SUM(amount) FROM orders WHERE status='已支付'`，答案"已支付订单共 4 笔，总金额 388.50"（与种子数据验算一致）。证明 generate→guard→execute→answer 全腿在真实 LLM 下正确。

---

## 3. Checkpoint 写读恢复验证（Postgres）

`scripts/smoke_query_real.py` 对同一 `thread_id = smoke-real-query-001` 连发两轮 `graph.astream`：

| 项 | 结果 |
|----|------|
| 第一轮写入 checkpoint | ✅ Postgres `checkpoints` 表该 thread 行数 = **11** |
| 第二轮读取续跑 | ✅ `aget_state` 读回消息数 = **4**（>0 证明读路径通） |
| 第二轮真实 LLM 答复 | ✅ 「作为这个 monorepo 的助手，我可以帮你：改代码 / 查代码 / 跑验证 / 写文档…」 |

**结论**：`AsyncPostgresSaver` 真连 Postgres 的写→读→续跑闭环验证成功。

---

## 4. 最终冒烟结果

```
[config] db_enabled=True llm_enabled=True
[config] LLM_BASE_URL=http://127.0.0.1:8799/v1 LLM_MODEL=opencode/deepseek-v4.1-flash-free
=== 第一轮：写入 checkpoint + 真实 LLM 调用 ===
[round1] chunks=9 answer='...我是 deepseek-v4.1-flash-free（opencode/deepseek-v4.1-flash-free）。'
[checkpoint] Postgres 中 thread=smoke-real-query-001 的 checkpoint 行数 = 11
=== 第二轮：同一 thread_id 读回 checkpoint 续跑（写读恢复） ===
[round2] chunks=3 answer='作为这个 monorepo 的助手，我可以帮你：...'
[checkpoint] aget_state 读回消息数 = 4
=== 结论 ===
[PASS] 真实 LLM 往返 + checkpoint 写读恢复
```

---

## 5. 剩余卡点 / 非阻塞缺陷

### 🔴 P1（非阻塞）：后台长期记忆写入线程 event-loop 错配

`agent-core/agent_core/memory/vector_backend.py` 的 `PgVectorMemoryBackend.remember()`：

```python
def remember(self, pool, user_id, content):
    def _run():
        loop = _new_loop()                       # 新线程新建 loop
        loop.run_until_complete(self._aremember(pool, user_id, content))  # 但 pool 来自主 loop
    threading.Thread(target=_run, daemon=True).start()
```

`pool`（asyncpg 连接池）在主事件循环创建，却被后台线程的新 loop 使用，
触发：

```
RuntimeError: Task ... got Future ... attached to a different loop
asyncpg.exceptions.InterfaceError: cannot perform operation: another operation is in progress
```

- **影响范围**：仅后台长期记忆（`memories` 表）的异步写入线程；**不阻塞**主 query / checkpoint 路径。
- **修复方向**：后台写入要么 (a) 复用与主循环同一 loop（如用 `loop.call_soon_threadsafe` / `asyncio.run_coroutine_threadsafe` + 共享 loop），要么 (b) `remember()` 自建独立连接池（不跨 loop 共享），要么 (c) 走同步 `psycopg` 线程写入。

### 🟡 观察项

- gateway 对 opencode 上游 `UnknownError` 无重试（见 §2.3）。

---

## 7. 真实 Embedding / Rerank 接入（硅基流动）

用户提供硅基流动 token，已接入**真实远程 embedding**，并已将 **rerank 接进主检索链路**（融合后过 `bge-reranker-v2-m3` 重排 top-K）。

### 7.1 可用免费模型（已用 token 拉取 /v1/models 确认）

| 类型 | 模型 | 维度 | 备注 |
|------|------|------|------|
| embedding | `BAAI/bge-m3` | 1024 | 免费，选用 |
| embedding | `BAAI/bge-large-zh-v1.5` | 1024 | 免费 |
| rerank | `BAAI/bge-reranker-v2-m3` | — | 免费，**已接入主检索链路** |
| rerank | `Qwen/Qwen3-Reranker-0.6B` | — | 免费 |
| （无免费 512 维 embedding） | — | — | 故向量列统一改 1024 |

### 7.2 Embedding 闭环验证 [PASS]

`.env` 改动：

```
VECTOR_DIM=1024                                   # 升维以对齐 bge-m3
EMBEDDING_MODE=remote
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_API_KEY=<硅基流动 token>                 # 已在 .gitignore 的 .env 中，不入库
```

- 因维度从 512→1024，**已 DROP 旧 `vector(512)` 表**（`chunks/memories/semantic_cache/sql_*` 等），由 `ensure_schema` 以 1024 重建。
- `scripts/smoke_rag_real.py` 真实入库 3 篇文档（pg/kafka/redis）→ 真实查询召回：**3/3 语义命中正确**
  （pg 查询→pg.md、kafka 查询→kafka.md、redis 查询→redis.md）。
- 同时修复了 `store.py.add_document` 的真实 bug：psycopg3 的 `AsyncConnection` 无 `executemany`，
  改为 `conn.cursor().executemany(...)`。该 bug 在 mock 模式下从未触发（入库路径此前未真跑 PG 批量写）。

### 7.3 Rerank 已接线 [PASS]

`retrieve_chunks` 的检索链路现为：**向量召回 + BM25 召回 → RRF 融合（候选取 `max(rag_top_k, rerank_top_n)`）→ rerank 重排 top-K**。

- 新增 `app/rag/rerank.py`：`ApiReranker`（零依赖 urllib 封装，与 `zhanggui-zhiku` 同语义，但放在主 app 内自洽，避免跨子项目耦合）。
  `get_reranker()` 按 `rerank_effective_enabled` 惰性返回实例，未开启/无 key 返回 `None`。
- `store.py.retrieve_chunks`：融合候选送入 `ApiReranker.compute_score([[query, content], ...])`，
  rerank 分（0~1）降序取 top-K；**rerank 失败（网络/429）优雅回退 RRF 融合序**，不影响主链路。
- 配置（`.env`）：`RERANK_ENABLED=true`、`RERANK_TOP_N=8`、`RERANK_API_KEY=<同 embedding token>`、`RERANK_MODEL=BAAI/bge-reranker-v2-m3`。
  基类 `shared_schemas.settings.BaseLLMSettings` 与 `app/config.py` 各补 `rerank_*` 字段；`rerank_effective_enabled` 需「开启且配 key」才生效。
- 验证：`smoke_rag_real.py` 加 rerank 校验——3/3 语义命中且 top-1 score 为 0~1 的 rerank 分（如 `0.9956`，原 RRF 分为固定 `1/(60+rank)`）。

**未做**（保持最小必要）：rerank 候选未做 query 改写/分页批量（单批 64 上限内，万级语料足够）；未接入 `zhanggui-zhiku` 的 `ApiReranker` 单例（跨包耦合，主 app 自持一份更内聚）。

### 7.4 限速提醒

硅基流动免费档有 RPM/TPM 限流，批量 embedding 注意节流；冒烟脚本仅数次调用，安全。
`agent_core` 的 `RemoteEmbedder`/`SiliconFlowEmbedder` 对 429 有简单重试（2 次、退避 0.5s）。

---

## 8. 检索回归基线（rerank 增益可衡量）

为回答「几版改动后检索准确率是否有提升」，用 **FlashRAG `retrieval_recall@k`** 做了可复现的回归对照：
「关 rerank（纯 RRF 融合序）」vs「开 rerank（融合后过 `bge-reranker-v2-m3` 重排 top-K）」。

评测语料：`scripts/flashrag_eval/run_eval.py` 内置 6 篇多段 markdown（pg / kafka / redis + 干扰项 mysql / elasticsearch / rabbitmq，
每个 `##` 主题切成独立 chunk），8 条业务黄金问题（golden_answers 为排他性短语，避免近义文档误命中）。

> ⚠️ 实测该评测集在「向量召回 + BM25 召回 → RRF 融合」下已近饱和：
> rerank 关/开两档 `recall@5` 均为 **1.0**（8/8 全命中），rerank 未带来额外 recall 增益。
> 这反映当前评测集对 rerank 不够敏感（语料小、golden 多为单 chunk 命中，无近义强竞争）。
> 若要衡量 rerank 增益，需扩充带近义竞争的黄金问题（见 §8.3）。

### 8.1 基线结果（top-k=5，实测于 2026-08-18）

| 配置 | recall@1 | recall@5 | precision@5 | 备注 |
|------|----------|----------|-------------|------|
| rerank **关**（RRF 融合序） | 1.0 | 1.0 | 0.325 | 8/8 全命中 |
| rerank **开**（重排 top-K） | 1.0 | 1.0 | 0.300 | 8/8 全命中，与关档持平 |
| **Δ（rerank 增益）** | 0 | 0 | -0.025 | 饱和评测集下 rerank 未显增益 |

- precision@5 在 0.30~0.33 区间（语料小、chunk 多，属预期）。
- 结论：rerank 主链路已闭环且**优雅回退**机制验证有效（§7.3），但在当前 8 题评测集上 recall 已封顶，
  增益无从体现。检索回归基线的价值在于**锁定「不退化」**：后续改动检索逻辑后重跑，`recall@5` 须维持 1.0。

### 8.3 评测集待增强（非阻塞）

当前 8 题 golden 多为单 chunk 命中，rerank 无发挥空间。建议后续补充：
- 近义强竞争问题（如「消息不丢」同时命中 Kafka/RabbitMQ 多篇），制造 rerank 可纠正的 top-1 错排；
- 跨文档多跳问题，验证 rerank 对融合序的二次排序收益。

### 8.2 复跑

```bash
# 前置：pgvector 容器 + 真实 embedding/rerank 可达（见 §1.1 / §7）
cd /workspace/agent-platform
make eval-rag        # 先关后开，打印对照聚合指标 + 逐条命中
```

脚本零副作用：每次清空 `chunks` 表后重新入库内置语料，不影响业务数据。
rerank 开关完全由 `.env` / 环境变量 `RERANK_ENABLED` 控制，脚本本身不改检索逻辑。

---

## 9. opencode 免费层深度实测与使用技巧（2026-10-18）

> 本章是 §2.3 的深化：一天高频实测 + 社区多源调研后，免费层的完整形态与适配方案。
> 一句话结论：**免费层是 IP 级限额（≈10 RPM / 1 RPS / 每日约 50 次），安全并发 = 1；403 只是第一级，持续高频会升级为 IP 硬封**。

### 9.1 限额实测（社区调研交叉 + 本机全天实测）

| 维度 | 结论 | 来源 |
|------|------|------|
| 速率 | **约 10 RPM / 1 RPS**（每分钟 10 次、每秒 1 次） | 社区实测贴（2026 版）；本机：1.2s 间隔顺序调用零 403 |
| 每日额度 | **约 50 次/天**（UTC 0 点重置，北京时间早 8 点） | 社区实测贴 |
| 限额粒度 | **IP 级**（按出口 IP 算；换 IP/代理即恢复，与账号无关） | 社区多帖 + 官方封禁文案 "from this IP address" |
| 安全并发 | **1（串行）** | NVIDIA 通道文档明说"并发 1 串行处理"；本机并发即 403 |
| 突发 | burst 即 403 `Detect Abuse Traffic` | 本机全天复现 |

单次 nl2sql 查询的成本：**~4-5 次 LLM 调用**（extract_keywords → filter_table → generate_sql → answer，出错再加 correct）。即每日 50 次额度约够 **10 次查询**——dev 验证够用，别拿它跑批量/回归。

### 9.2 三级错误形态与处置（今天踩全了）

| 级 | 现象 | 根因 | 处置 |
|----|------|------|------|
| L1 瞬时 | `403 FreeTierError: Detect Abuse Traffic` | 短时突发超过 ~1 RPS/10 RPM | **网关已自动重试**（指数退避 2s→4s→8s，最多 3 次）；同时闸+间隔从源头压平 burst |
| L2 IP 封禁 | `403 ... abusive traffic from this IP address. This isn't related to your account. If you're on a VPN or proxy, turn it off... or subscribe to OpenCode Go` | 持续高频后出口 IP 被反滥用标记（本机 2026-10-18 全天测试后触发） | **降频无效**。等数小时~隔天按 IP 恢复（社区经验）；或换出口 IP/代理；或订阅 OpenCode Go。dev 期可临时切其他免费 LLM（见 §9.6） |
| L3 账号/配置 | `Unexpected server error`（模型 ID 过期）/ `400 PAT not supported`（Copilot） | 配置问题，非限额 | 见 §2.3 |

**教训**：L1 靠重试能救；L2 是 IP 进了观察名单，**任何客户端侧优化（含重试）都无效**——识别特征是错误文案从 "Detect Abuse Traffic" 变成 "abusive traffic from this IP address"。

### 9.3 网关并发适配（`scripts/opencode_gateway.py`，已落地）

| 机制 | 默认 | env 覆盖 | 说明 |
|------|------|---------|------|
| 全局串行闸 | 容量 1 | `OPENCODE_GATEWAY_MAX_CONCURRENCY` | `asyncio.Semaphore`，跨请求 + 单查询内所有 `opencode run` 子进程排队；有付费额度/自建端点时可放大 |
| 最小调用间隔 | 1.2s | `OPENCODE_GATEWAY_MIN_INTERVAL` | 持闸放行前保证与上次调用间隔 ≥ 此值——把 burst 形状压平再发（1 RPS 限额的对冲） |
| 限流退避重试 | 3 次、2s→4s→8s | `OPENCODE_GATEWAY_MAX_RETRIES` / `OPENCODE_GATEWAY_BACKOFF_BASE` | **仅对瞬时限流**（403 反滥用/429/503）；400 token 类型、402 余额、模型不存在是确定性错误，不重试直接透出 |
| 错误透出 | — | — | 真实上游 message 进响应 content + 网关 stderr 日志（`[opencode-gateway] ...`） |

应用层还有第二层闸：nl2sql `QUERY_MAX_CONCURRENCY=1`（图执行串行，P1-5 LoadGuard）。两层叠加 = 请求在图层就排队，不会把并发压力传给网关。

### 9.4 使用技巧（checklist）

1. **永远串行**：并发请求免费层必挂；批量任务加 sleep ≥1s，日总量控制在 ~50 次内
2. **看错误文案分级**："Detect Abuse Traffic"=瞬时（等/重试）；"abusive traffic from this IP"=IP 封（停手数小时）
3. **报错先查模型 ID**：`opencode models` 确认；过期 ID 的报错是无信息量的 `Unexpected server error`
4. **403 不是账号问题**：官方文案明说 "isn't related to your account"——别反复换 key/重登
5. **LLM_TIMEOUT≥120s**：免费模型冷启动慢（原 60 会超时）；本机 Qwen3-8B 顺序多次调用单查询 ~83s
6. **embedding 与 LLM 分流**：embedding 走硅基（免费 bge-m3），LLM 走 opencode 或硅基免费 chat——两边的限额互不占用，且任一边被限不至于全瘫
7. **跑之前先 `curl` 一发**：确认通道活着再跑 E2E，省得 80s 后拿到一个限流错误

### 9.5 硅基流动 402 陷阱（今天误判的真相，高价值）

**现象**：`BAAI/bge-m3`（免费 embedding）返回 `402 {"code":30001,"message":"Sorry, your account balance is insufficient"}`。
**误判**：第一反应是"免费模型被收回"（社区确有 2026-08 免费档收缩的传闻）。
**真相**（同 key 对照实验）：

| 探针 | 结果 |
|------|------|
| 免费 chat `Qwen/Qwen3-8B` | ✅ 200（账户没欠费！） |
| 免费 embedding `BAAI/bge-m3` | ❌ 402 |
| 付费 `Pro/BAAI/bge-m3` | ❌ 402（当时） |
| **小额充值后**：免费 `BAAI/bge-m3` | ✅ 200 恢复 |
| **小额充值后**：付费 `Pro/BAAI/bge-m3` | ✅ 200（¥0.07/百万 token） |

**结论**：硅基的风控是**不对称**的——余额归零时免费 **chat** 池仍放行，免费 **embedding** 池先冻（报误导性的 "balance insufficient"）。这不是模型被收回，是账户余额见底。**遇到 402 先告知用户充值，别急着换模型**。充值后免费 ID 自动恢复，无需改任何配置。

### 9.6 模型策略与当前 dev 配置

**策略（用户 2026-10-18 定）**：只用免费模型；换任何付费模型（`Pro/BAAI/bge-m3`、OpenAI/Claude 系等）**须用户显式批准**。

当前 dev 配置（根 `.env`，gitignored）：

```
LLM_BASE_URL=https://api.siliconflow.cn/v1     # opencode IP 封禁期的临时路径
LLM_MODEL=Qwen/Qwen3-8B                         # 硅基免费 chat
EMBEDDING_MODEL=BAAI/bge-m3                     # 硅基免费 embedding（1024 维）
EMBEDDING_MODE=local                            # agent_server rag 走本地 sentence-transformers
RERANK_ENABLED=false                            # rerank 远程已死，显式关闭
QUERY_MAX_CONCURRENCY=1                         # 应用层串行
```

opencode IP 封禁恢复后切回（.env 内有注释标明）：`LLM_BASE_URL=http://127.0.0.1:8799/v1` + `LLM_MODEL=opencode/deepseek-v4.1-flash-free`，网关的闸/重试/透出全部仍然有效。

**全免费栈 E2E 已通过**（2026-10-18）：Qwen3-8B + bge-m3 + nl2sql 14 节点图 + 真 PG——问"已支付的订单有多少笔，总金额是多少" → 正确 SQL → 答案"4 笔、388.50 元"与 DW 真值逐位一致；语义召回前置验证过（不同表述查询正确命中，距离 0.16）。

---

## 6. 复跑指引

```bash
# 前置：pgvector 容器 + 网关已在跑（见 §1.1）
cd /workspace/agent-platform
.venv/bin/python scripts/smoke_query_real.py | tail -20
# 期望末尾出现：[PASS] 真实 LLM 往返 + checkpoint 写读恢复
```
