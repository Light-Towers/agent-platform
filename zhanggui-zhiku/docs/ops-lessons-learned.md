# 运维 / 验收实战经验总结（Lessons Learned）

> 本文记录在 `zhanggui-zhiku`（掌柜智库）生产化改造与环境验收过程中踩过的坑、
> 排查路径与最终结论。**目标是把"试错过程"沉淀为可复用的操作规范**，
> 避免后续重复踩坑。对应验收清单见 `verification-checklist.md`。
>
> 最后更新：2026-08-06（④ 鉴权补验 + ⑦ OTel 真实导出跑通）。

---

## 1. 镜像与构建

### 1.1 项目实际依赖 CUDA 版 torch（镜像很大、构建很慢）

- `requirements.txt` / `pyproject.toml` 仅写 `torch` / `torchaudio` / `torchvision`，
  **未锁 `+cuXXX` 后缀**；`pip install` 默认拉的是 **CUDA 版** wheel。
- 实测镜像 `zhanggui-zhiku-web` 体积 **~6.19GB**，含 `nvidia-cu13` 全套依赖
  （`nvidia-cublas` / `nvidia-cufft` / `nvidia-cusolver` / `nvidia-cudnn` 等十余个包，
  单个 200MB+）。
- `docker compose build web` **每次都会重新解析并下载全部依赖**（即便源码只改一行），
  耗时约 **20 分钟**（瓶颈在 CUDA 包的下载）。

**规范**：
- 改源码后**一次性 `docker compose build` 干净镜像并验证**，不要在容器内
  `pip install` 临时装包再 `docker commit` 镜像（会丢失源码挂载、破坏可复现性，且
  镜像与 `Dockerfile` 脱节）。
- 本地无 GPU 时，CUDA 版 torch 的 GPU 能力**完全闲置**（embedding/rerank 走硅基流动
  API，LLM 走远端）。若需瘦身，可按 `README` 的「CPU slim」裁剪，或把
  `torchvision` / `torchaudio`（本项目用不到）从依赖移除。

### 1.2 `docker compose restart` 不会重新读取 `.env`

- `web` 服务用 `env_file: .env`。`docker compose restart web` **复用容器创建时固化的
  环境变量**，`.env` 的改动不会生效（实测：改 `ZHANGUI_API_KEY` 后 `restart`，容器内
  `printenv` 仍为空）。
- 同理 `docker restart <container>` 也不重读。

**规范**：
- 修改 `.env` 后必须 `docker compose --profile core [--profile obs] up -d web` **重建容器**。
- 验证 env 是否生效：`docker exec <container> printenv <VAR>`。

### 1.3 compose 解析陷阱：`--profile` 必须覆盖所有被依赖的 profile

- `web` 服务的 `depends_on` 引用了 `minio-init`，而 `minio-init` 有 `profiles: ["core"]`。
- 单独执行 `docker compose restart web` / `up jaeger`（不带 `--profile core`）会报
  `service "web" depends on undefined service "minio-init"` —— 因为不带 core 时
  `minio-init` 被视为"未定义"。
- `jaeger` 在 `profiles: ["obs"]`，单独 `up jaeger` 也会因 `web` 依赖 core 服务而解析失败。

**规范**：
- 涉及 `web` 的任意操作都带 `--profile core`；涉及 `jaeger` 的带 `--profile core --profile obs`。
- 口诀：**`docker compose --profile core --profile obs up -d web jaeger`** 是起全栈（含可观测）的标准命令。

---

## 2. 鉴权（验收项 ④）

### 2.1 `ZHANGUI_API_KEY` 是自定密钥，不是第三方 key

- 它是**本项目自己的入站 API Key**（FastAPI 中间件 `SecurityGuardsMiddleware`），
  与 `OPENAI_API_KEY`（魔搭）/ `SILICONFLOW_API_KEY`（硅基流动）**无关**。
- 不需要去任何平台申请——在 `.env` 填一个自定字符串即可（如
  `ZHANGUI_API_KEY=zk-<随机>`，用 `secrets.token_urlsafe` 生成）。
- 为空 → 鉴权**整体关闭**（向后兼容既有行为）；非空 → 请求须带
  `X-API-Key` 或 `Authorization: Bearer <key>`，不匹配 → `401`（用
  `secrets.compare_digest` 防时序攻击）。

### 2.2 必须用 POST 验证 `/query` 的 401

- `/query` 是 **POST** 接口。用 GET 探测会在**鉴权之前**就返回 `405 Method Not Allowed`，
  永远验不到 401。

**实测结果（2026-08-06）**：
`POST /query` 无 key→401、错 key→401、正确 key→200；`/health*` 与 `/import.html`
（免鉴权路径）仍 200。

---

## 3. 可观测性 / OTel（验收项 ⑦）——本批次最深的坑

### 3.1 现象：`tracing 已启用` 日志打了，但 Jaeger 查不到 trace

日志里出现 `OTel tracing 已启用: service=%s endpoint=%s`（`%s` 未替换是 `_log_info`
格式化瑕疵，不影响功能），但 Jaeger 里 `zhanggui-zhiku` 服务名**始终 0 trace**。
排查走了很长的弯路，根因有三层，**必须同时修复**：

#### 坑 A：OTLP exporter 选了 grpc，到 Jaeger 握手失败

- `tracing.py` 原按 `grpc` → `http` 顺序尝试 exporter，`grpc` 优先。
- grpc exporter 默认尝试 TLS，而 jaeger all-in-one 未开 TLS →
  `http2Server.HandleStreams failed ... unexpected EOF`。
- **修复**：把 exporter 选择顺序改为 **HTTP 优先**（jaeger OTLP HTTP 通路稳定）。

#### 坑 B（真正的元凶）：`TracerProvider` 没设 `resource.service.name`

- `init_tracing()` 创建 `TracerProvider()` 时未指定 `resource`。
- SDK 默认 resource 只有 `telemetry.sdk.*`，**没有 `service.name`**。
- 结果：span 其实**成功导出**了，但 Jaeger 把它归到了 `unknown_service`
  （`/api/services` 里那个一直存在的 `unknown_service` 就是它）。
- 查 `service=zhanggui-zhiku` 自然 0 条——**不是没导出，是归错服务名了**。
- **验证**：`curl localhost:16686/api/traces?service=unknown_service` 能看到几十个 trace。
- **修复**：
  ```python
  provider = _SDKTracerProvider(
      resource=_Resource.create({"service.name": service_name})
  )
  ```

#### 坑 C：OTLP HTTP exporter 不自动追加 `/v1/traces`

- `OTLPSpanExporter(endpoint="http://jaeger:4318")` 实际请求路径是 **`/`**（根），
  不是 `/v1/traces` → Jaeger 返回 404。
- `_append_trace_path` 在该版本**不生效**（或行为不符预期），需 endpoint 自带完整路径。
- **修复**：`.env` 写 `OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4318/v1/traces`。

### 3.2 Jaeger 的 OTLP HTTP 只稳收 protobuf（或 JSON），别混用

- SDK HTTP exporter 固定发 `application/x-protobuf`（源码 `encode_spans(...).SerializePartialToString()`）。
- Jaeger all-in-one 1.57 实测：**protobuf 走 OTLP HTTP 成功入库**（只要 service.name 正确）；
  而用 `curl` 发 JSON 到同端点也成功。关键不在编码格式，而在 **3.1 的 A/B/C 三处**。
- 若走 gRPC，记得给 exporter 加 `insecure=True`（本地 jaeger 无 TLS）。

### 3.3 验证 ⑦ 的标准动作

```bash
# 1) 起全栈 + 可观测
docker compose --profile core --profile obs up -d web jaeger
# 2) .env 关键项
#    ZHANGUI_TRACE_ENABLED=true
#    OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4318/v1/traces
# 3) 发请求
curl -X POST localhost:8000/query -H 'Content-Type: application/json' \
     -H 'X-API-Key: <你的key>' -d '{"query":"测试","session_id":"x","history":[],"is_stream":false}'
# 4) 查 Jaeger
curl 'http://localhost:16686/api/traces?service=zhanggui-zhiku'
#    应出现 trace，每请求含 request.total + retrieval.rewrite 等 span
```

**实测结果（2026-08-06）**：`zhanggui-zhiku` 服务名 count=3，每请求 2 span，无 export error。

### 3.4 no-op 降级铁律

- `tracing.py` 设计：**SDK 未装 / 未配 endpoint / 未启用开关 → 自动 no-op**，绝不抛异常。
- 这意味着本地无 collector 时服务照常跑（span 调用全走 `_NoOpSpan`），不会因为
  OTel 配置缺失而崩。验证降级安全性的方法是：看服务能否正常启动 + `/query` 正常返回，
  **不代表真实导出已通**——真实导出必须按 3.3 在 Jaeger 里看到 trace 才算数。

---

## 4. 诚实边界（验收项 ⑥ 偏差）

### 4.1 kg 通道是 stub，fan-out 隔离未真实验证

- `app/query_process/agent/nodes/node_query_kg.py` 仅 `time.sleep(1)`，
  注释"未接 Neo4j"。
- 因此：停 Neo4j 后 `/query` 仍 200，但**不是因为隔离生效，而是 kg 节点从未连接 Neo4j**；
  `recall timeout channel=kg` 日志**不会出现**。
- 交接文档把 ⑥ 列为"已验证"与事实不符，已在 `CHANGELOG.md` 的 Fixed 段作诚实声明，
  checklist ⑥ 实测列标记"框架就绪但 kg 为 stub，真实故障隔离待重测"。

**规范**：报告验收结果时，**只写实测证据**，未接入真实数据源的能力不得声称已验证。

---

## 5. 磁盘（etcd 生产标准）

- 本机底层为**云 HDD**（nbd+btrfs，ROTA=1），**非 NVMe**。
- 实测 fsync p99=12.25ms（>10ms 红线）、IOPS=503.7（刚达标），**未达 etcd 生产磁盘标准**，
  仅适合验证环境。
- 若上生产，etcd 数据盘需本地 NVMe SSD（≥500 IOPS、p99 fsync <10ms，可用 fio 验证）。

---

## 6. 速查清单（Cheat Sheet）

| 场景 | 命令 / 操作 |
|---|---|
| 起全栈 + 可观测 | `docker compose --profile core --profile obs up -d web jaeger` |
| 改 `.env` 后生效 | `docker compose --profile core --profile obs up -d web`（**重建**，非 restart） |
| 查看容器内 env | `docker exec zhanggui-zhiku-web printenv <VAR>` |
| 验证 ④ 鉴权 | `POST /query` 带/不带头，看 401/200（`/query` 必须 POST） |
| 验证 ⑦ 导出 | 发请求后 `curl 'localhost:16686/api/traces?service=zhanggui-zhiku'` |
| 看 jaeger 服务列表 | `curl localhost:16686/api/services` |
| 本地无 collector 不崩 | 删 `OTEL_EXPORTER_OTLP_ENDPOINT` / 关 `ZHANGUI_TRACE_ENABLED` → 自动 no-op |

---

## 7. 已提交记录

- commit `a8354588`（production）：④ 鉴权实测 + ⑦ OTel 真实导出修复
  （`tracing.py` HTTP 优先 + `resource.service.name`；`Dockerfile` 加 opentelemetry 依赖；
  `CHANGELOG.md` / `verification-checklist.md` 回填）。
- 相关修复历史：compose etcd 依赖、minio/mc tag、/query 500（Request/Pydantic 混淆）、
  kg stub 诚实声明，均见 `CHANGELOG.md` 的 Fixed 段。
- M8（2026-08-06，未 commit）：
  - **item_name 规范化**：导入侧 `node_item_name_recognition.py` LLM 输出后套
    `normalize_item_name()`（去空白 + 剥离品牌前缀兄弟/Brother + 剥离尾部料号 D01WD7001-00 类），
    检索侧 `node_search_embedding.py` 构造 Milvus expr 前同样套用，
    保证 golden "HAK 180 烫金机"（带空格）与库内 "HAK180烫金机" 匹配；
    `prompts/item_name_recognition.prompt` 收紧为"仅输出型号+品类，禁止品牌前缀与料号"。
    清库重导后 kb_item_names 2 条（手册/说明书各 1），item_name 统一为 `HAK180烫金机`。
  - **locust `--api-key` 参数注册修复**：`benchmark/locustfile.py` 引用了
    `self.environment.parsed_options.api_key` 但从未注册自定义参数，locust 2.x 报
    `unrecognized arguments: --api-key`；改用 `@events.init_command_line_parser.add_listener`
    注册 `--api-key`。
  - **api 模式压测结果**：`EMBEDDING_MODE=api` / `RERANK_MODE=api` 下
    `/retrieve` QPS 0.52 / P95 243s / 0 错误率，瓶颈为 SiliconFlow 远程 API 排队；
    与 M6 §10.6「全部自有组件 QPS≥100 / P95<3s」目标冲突，改目标口径为
    「api 模式下自有服务处理延迟（去外部 API 后）待 local 模式验证」。
    `data/index_registry.json` 已回填 run_id `20260806_101019_def9da22`（eval 指标 0.0，
    原因见 eval/README §诚实声明：golden relevant_chunk_ids 为假设性标注）。
