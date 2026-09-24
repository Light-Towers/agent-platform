# 容量模型与瓶颈定位（M7，方案 §10.5 / §10.6）

> 本文是压测的「怎么加压、卡在哪、怎么缓解」决策手册。**所有实测数字一律回填
> 空模板/结论列，禁止预填**（方案 §13）。

## 1. 容量模型（为什么 `--workers 1`）

| 部署形态 | worker 数依据 | 说明 |
|---|---|---|
| CPU-only reranker | `min(CPU核数, 可用内存 / 单模型内存)` | 内存是硬约束，不是 CPU |
| GPU reranker | **workers=1~2**，靠 Semaphore + batch 提吞吐 | 多进程抢同一张卡是负优化 |
| 多 replica 横向扩 | 每 replica worker 数按上表，**replica 数由 LB 扩** | 优先横向扩 replica，而非纵向堆 worker |

**核心结论**：reranker / embedding 模型在**进程内加载**，`--workers N` = N 份模型副本
（内存/显存线性放大）。因此 M6 compose 已显式 `--workers 1`；需要更大吞吐时
**加 replica**（每份只多一份模型副本），而不是在同一进程内堆 worker。
`docker-compose.yml` 中 `deploy.replicas` 注释仅作示范（K8s / 真实编排生效）。

## 2. 瓶颈定位决策树

QPS 上不去时，**按以下顺序**排查（每节点给「症状 → 排查命令 → 缓解手段」）。
定位口径：配合 M4 OTel（Jaeger 看 span 时长）与 M6 Semaphore/超时隔离。

```
QPS 上不去 / P95 高
 ├─ 1. reranker（最大嫌疑：torch 同步推理）
 │    症状：ranking.rerank span 时长占比高、Semaphore 排队（CPU 打满 / GPU 利用率低）
 │    排查：日志看 "Step 2: 正在计算相关性得分..." 耗时；nvidia-smi 看显存/利用率
 │    缓解：调 rerank.yaml max_concurrency（默认 8）压到显存容量内；
 │          CPU 换 GPU（BGE_RERANKER_DEVICE）；batch inference（P2）；
 │          确认 fallback_used=false（未误入降级原序）
 ├─ 2. LLM 生成（/query 档硬天花板）
 │    症状：llm.generate span 占比高、外部 API 429/超时；/retrieve 档 QPS 正常但 /query 低
 │    排查：日志看 LLM 调用耗时与出站滑窗限流命中；压测分 /retrieve 与 /query 两档对比
 │    缓解：**不承诺端到端 100 QPS**（外部限流是硬天花板）；streaming 降 TTFT；
 │          出站限流器调大窗口（app/utils/rate_limit_utils.py）；降 max_tokens/上下文
 ├─ 3. Milvus 查询（检索主依赖）
 │    症状：retrieval.embedding span 时长高、Milvus 连接池耗尽、QPS 见顶
 │    排查：milvus 日志 / 监控；`hybrid_search` 调用耗时；连接池复用情况
 │    缓解：索引参数（HNSW ef/search_list）；升级 Milvus 资源（compose limits 4G）；
 │          确认 client 单例复用（勿每请求新建）
 ├─ 4. Neo4j（KG 路，当前为占位实现）
 │    症状：retrieval.kg span 时长 / entities_n=0（占位实现不产生真实查询）
 │    排查：node_query_kg 是否真实接 Neo4j（当前 sleep(1) 占位）
 │    缓解：接真实 Neo4j 查询 + 逐路超时已由 M6 fanout 兜底（kg timeout 1.0s）
 └─ 5. web 路 MCP 联网搜索（外部依赖）
      症状：retrieval.web span outcome=timeout（3s 截断）、web_search_docs 为空
      排查：MCP 服务可用性；channels.web.timeout_s（retrieval.yaml）
      缓解：调大 channels.web.timeout_s；MCP 侧配额；该路失败已由 fanout 降级为空列表
```

## 3. 压测达标判据（空表，实测后填写）

| 场景 | 目标 | 实测值 | run_id / 日期 | 机器规格 |
|---|---|---|---|---|
| /retrieve | QPS ≥ 100 | | | |
| /retrieve | P95 < 3s | | | |
| /retrieve | 错误率 < 1% | | | |
| /query 端到端 | QPS 由外部 LLM 配额决定 | | | |
| /query 端到端 | TTFT / total 分档（streaming 后必测） | | | |
| /query 端到端 | 错误率 < 1% | | | |

> 瓶颈定位结论回填到 §2 决策树各节点的「实测结论」列（如"reranker 为瓶颈，Semaphore 8
> 打满，建议 max_concurrency=4 + GPU"）。

## 4. 压测目标合理性（为什么 /retrieve 可以承诺，/query 不承诺）

- `/retrieve` 全部为**自有组件**（Milvus + 自有融合/重排逻辑），目标 QPS ≥ 100 / P95 < 3s
  是合理工程目标（方案 §10.6）。
- `/query` 端到端受**外部 LLM API 限流**约束（出站滑窗限流 + 厂商配额），把 100 QPS 作为
  端到端目标不现实（方案 §10.6 分档理由）；只报实测值并标注外部瓶颈。
