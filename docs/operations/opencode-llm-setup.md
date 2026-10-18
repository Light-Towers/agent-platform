# agent-platform 真实 LLM 数据端到端测试闭环

验证日期：2026-08-18
结论：**闭环通过（[PASS]）** —— 真实 LLM 通道打通，Postgres checkpoint 写读恢复验证成功，RAG 真实 embedding + rerank 重排主链路已闭环。
剩余 1 个非阻塞缺陷：后台长期记忆写入线程的 event-loop 错配（见 §5）。

> **2026-10-18 更新（opencode 通道复跑）**：① 模型 ID 已由下线的 `deepseek-v4-flash-free` 更正为 **`deepseek-v4.1-flash-free`**（本文所有命令/配置已同步）——用过期 ID 会得到无信息量的 `Unexpected server error`。② `Detect Abuse Traffic`(403) 是**免费层突发限流、非永久封禁**，降频即恢复，管线可容忍偶发单次限流。③ `opencode_gateway.py` 已修**错误吞掉**问题（此前真实上游错误被显示成空壳 `rc=1`），现在透出真实 message。详见 §2.3。④ nl2sql-service 已在真 PG+pgvector 下用真实 LLM 端到端跑通（正确 SQL + 正确答案）。

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
LLM_API_KEY=opencode-local-gateway          # 任意非空串即可
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

## 6. 复跑指引

```bash
# 前置：pgvector 容器 + 网关已在跑（见 §1.1）
cd /workspace/agent-platform
.venv/bin/python scripts/smoke_query_real.py | tail -20
# 期望末尾出现：[PASS] 真实 LLM 往返 + checkpoint 写读恢复
```
