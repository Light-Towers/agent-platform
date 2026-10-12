# 上线留证 — 2026-10-12（agent-platform @ db1a8b8，126 k8s）

> 本文件是**事后证据**，每节带产生时间（+08:00）。判定口径来自 `docs/operations/minimal-release-runbook.md` §1 纪律 1：
> "读回的实际值 == 期望值"才算生效，apply/rollout 的退出码不算证据。
> 全文不含任何密钥值（只出现键名与长度口径）；抓取命令均可复跑。

## 1. 上线对象（09:56）

| 判据 | 读数 |
|---|---|
| 期望 rev | `db1a8b8477539af2af00e104e36317c159f19c39` |
| 126 构建源 HEAD | 同上（`build.sh` rev 门禁通过，`dirty=no`） |
| **Pod 内** `/srv/agent-platform/GIT_REV` | `db1a8b8477539af2af00e104e36317c159f19c39` ✅ |
| 镜像内依赖 | `find_spec('sentence_transformers')=True`、`torch=True` ✅ |
| 仓库本地 HEAD（**取证时刻**） | `7d00ab3`，比线上只多一个**文档**提交 ⇒ 代码面等价。（本文件写成之后 HEAD 又前进了文档提交，故"当前差集"请按 `git log --oneline db1a8b8..HEAD` 现查，别引用这一行） |
| 落点节点 | 第一版落 `ambari02`，重启后落 `ambari01`（两节点都需在位缓存与镜像） |

同步通道：`git bundle` → 126 `git fetch` + `checkout` → `build.sh` → `distribute.sh`（containerd 隔离实例，
显式 `--address`，两个 worker + 本机）→ 整模板 patch + apply → 滚动。**未用**本地 `docker run` 起服务冒充上线，
`docker run` 只出现在构建期自检（等价于 `build.sh` 里既有的 `cat GIT_REV` 回读）。

## 2. apply 冲突与解法（09:46 → 09:56）

第一次 `kubectl apply -f deploy/k8s/20-agent-platform.yaml` 被 API **整份拒绝**：

```
The Deployment "agent-platform" is invalid:
* spec.template.spec.containers[0].env[5].valueFrom: Invalid value: "": may not be specified when `value` is not empty
  ... env[6] env[7] env[17] env[18] env[19] env[20]
```

原因：线上 `LLM_BASE_URL/LLM_MODEL/LLM_FALLBACK_MODEL/OTEL_*` 是当年 `kubectl set env` 留下的**字面值**，
清单同项写 `valueFrom:` ⇒ 客户端三方合并把两者都留下。拒得完整 ⇒ **无半生效、无中断**（旧 Pod `de7e968` 继续服务）。

解法（已写进手册 §3.1）：`kubectl create --dry-run=client` 取清单真值 → `--type=json` 对 `/spec/template` 做一次
**原子 replace** → 再 apply 补齐其余。**只滚了一轮**（回读 ReplicaSet：仅 `agent-platform-867b47c89d` desired=1，
其余 desired=0）。

副产发现（值得记住的坑）：`kubectl apply --dry-run=client -o json` **不能**当"清单期望值"用——
它返回与线上合并后的对象，同一份清单实测 `apply` 回 10 项 env（线上现状）、`create` 回 21 项（清单真值）。

## 3. 预检读数（09:56，全部只读）

```
configmap agent-platform-config: ['EMBEDDING_MODEL','LLM_BASE_URL','LLM_FALLBACK_MODEL','LLM_MODEL',
                                  'OTEL_ENABLED','OTEL_ENDPOINT','OTEL_EXPORTER','OTEL_SERVICE_NAME']  缺失 无
secret agent-platform-secrets  : ['DATABASE_URL','POSTGRES_PASSWORD']  缺失 无
secret observability-keys      : ['API_KEY','LLM_API_KEY']              缺失 无
```

- 三节点 `/opt/ap-models/hf-cache` 在位；`125/241` 上 `uid10001_readable=yes`。
- 节点容量：`allocatable 16232772Ki`（≈15.9Gi）× 3 节点、8 CPU。**注意单位是大写 K**：
  按 `[kMGT]` 字符类解析会漏掉 `Ki`，容量预检因此抛过错——预检脚本算错比不算更糟。
- 镜像自检（Pod 的真实运行条件：uid 10001 + `:ro` bind + `HF_HUB_OFFLINE=1`）：
  `IMAGE_PREFLIGHT_OK uid=10001 dim=512 load_s=0.3`（冷缓存轮为 10.2s）。
  同轮伴随一条 `Ignoring corrupted tree cache file ... [Errno 13] Permission denied` ⇒ huggingface_hub
  自己降级处理，**不是失败**，`readOnly: true` 因此保留。

## 4. 反证清单（09:57–10:00，全部打实际返回值）

`/health`（经 `portforward.sh start` 后的 18000，等价于 Pod 内直读）：

```
status=healthy  storage=postgres  llm=true  search=false  sql_backend=none
embedding_backend=LocalEmbedder  embedding_real=true
guard_enabled=true  auth_enabled=true  identity_mode=single
otel=true  otel_status=ACTIVE  planner=deterministic
coordination=true  admission=false  revert=true  mcp=false
scheduler=false  control_plane=false  cost_governance=false  forensic=true
dependencies=[]   version=0.1.0
```

| 项 | 读数 | 判定 |
|---|---|---|
| 基线 1（要密钥） | `POST /query` 无密钥 **401**、错密钥 **401**、`GET /history` 无密钥 **401**；`/health` **200**、`/console.html` **200** 且 `Cache-Control: no-store` | ✅ |
| 环节 1-2（真问一次） | 事件序列 `route`→`evidence`→`status`→`answer`→`done` 各 1 次；重问同一句命中 `cache_hit`；`done.thread_id=tenant-default` | ✅ |
| 底线 3（真模型出话） | 空证据下回答：`提供的证据为"无"，因此无法根据现有证据回答…  证据不足，不能确定可靠来源` | ✅ 没编答案 |
| 底线 6（拦截走真路径） | `route{capability:blocked, reason:"被输入护栏拦截（injection）"}` → `answer{抱歉，您的输入包含不安全的内容，请重新描述。}` → `done`；**无 evidence、无 status** | ✅ |
| 服务端留痕 | `2026-10-12 01:59:11 WARNING [agent_core.guardrails.input_guard] Prompt injection 检测到: system\s*:\s*` | ✅（此前脚本 grep `blocked\|护栏` 恒 0 命中，是我 pattern 写错，不是没留痕） |
| 底线 7（PG 读回） | `/history?session_id=<乱填值>` → `thread_id=tenant-default count=4`，四条原文含被拦那句原话；`写入/读取线程历史失败\|HISTORY_READ_FAILED` **0 行** | ✅ |
| 基线 5（按编号追） | `e2e_traceparent.sh`：`/query 200`，`trace_id=0000000000000000025da991fd64f210`，Jaeger 查到 **8 个 span**（`POST /query` SERVER + `fastapi.endpoint` 等） | ✅ 单服务内链路，**不是**跨服务 |
| 基线 3（只到内网） | `type=ClusterIP`，`nodePort`/`externalIPs`/`loadBalancerIP` 全空；从 ambari02 curl `192.168.100.126:18000/health` **200**；集群内 ClusterIP 直连 **200** | ✅ 内网通。**公网侧不通未证**（本机就在内网里） |
| 基线 6（写接口拒） | 无密钥 `POST /import` **401**、`/sql/train` **401**、`/session/revert` **401** | ✅ |

## 5. 两盏生产开关（10:01–10:02）

**S1 身份守卫 fail-closed**——用**隔离探针 Pod**（同镜像、`DEPLOY_ENFORCE_IDENTITY=true`、给 `API_KEY`、
**故意不给 `SINGLE_TENANT`**），不碰线上端点。`phase=Failed exitCode=3`，12s 自行退出：

```
File ".../agent_server/main.py", line 214, in lifespan
    require_identity_startup_guard("agent_server")
RuntimeError: [identity] agent_server 启动被拒：多租户生产须配置 RS256 验签公钥或显式声明
SINGLE_TENANT=<tenant>（DEPLOY_ENFORCE_IDENTITY=true 已开启 fail-fast）。
见 docs/adr/0007-server-asserted-tenant-identity.md §4.1
ERROR: Application startup failed. Exiting.
```

探针 `guard-probe-identity` 验完即删，`/tmp` 脚本属本轮自建产物。

**S2 删除线上 Pod → 自愈 + 历史仍在**（底线 7 只能在真 Pod 上证）：

| 判据 | 读数 |
|---|---|
| 自愈用时 | **15s**（10:02:14 删除 → 10:02:30 Ready） |
| 新 Pod | `agent-platform-867b47c89d-4sfdt`，node=ambari01，`restartCount=0` |
| 重启后 `/history` | `count=6`，四条旧原文 + `e2e取证-…` 一轮，**读得回来**（PG 持久，非进程内存） |
| PG 静默失败 | 0 行 |
| 137 是否复型 | **未复型**：Warning 级 `Killing/OOMKilling/Evicted` 事件 **0 条**（2 条 `Killing` 是滚动用的 Normal 事件）；本轮 OTLP 指向宿主 Jaeger 且宽限期 60s ⇒ 优雅关闭走完 |
| 未拿到的判据 | 旧 Pod 的 `lastState`——对象随删除即消失。下次重启须在删除**前**抓 `logs --previous` + `lastState`，否则这条只能靠事件面旁证 |

## 6. 资源实测（10:03，LocalEmbedder 常驻、无并发）

| 口径 | 读数 |
|---|---|
| cgroup `memory.max` | 2147483648 ⇒ **limits 2Gi 真生效**（不是被裁剪掉的空话） |
| cgroup `memory.current` | 463994880（442Mi） |
| `kubectl top pod` | 441Mi，CPU 3m |
| pid1 `VmRSS`（uvicorn） | 565960 kB（553Mi） |
| 结论 | `requests.memory: 1Gi` 相对 441–553Mi 基线有余量；此前"应用单独基线 RSS 未实测"一项**已闭合** |

## 7. 今天仍然没证的事（不得被上面任何一节顺手盖过去）

> **本节写于 10:00 左右**。其中第 1、2 条已被同日 11:55–12:10 的 **§9 闭合**（`chunks` 0→93、问数已接并逐行对账）。
> 原文保留不删，是为了让"当时真实是什么状态"可查——**留档不是留给赢家看的**，改了才算撒谎。

1. ~~**底线 4 未满足**：`chunks=0`~~ ⇒ **已闭合，见 §9**（93 块 / 3 文档，dim=512，退化向量 0 行，检索命中且答案可溯源）。
2. ~~**问数未接线**：`sql_backend=none`~~ ⇒ **已闭合，见 §9**（清单补 `SQL_DSN` 后 `sql_backend=postgres`，
   执行 SQL 的 35/30/28 与库内真值逐行一致；本版数据源是 postgres，MySQL 那颗雷不涉及）。
3. **意图路由仍无真值灯**：`agent_core/intent/classifier.py` 直连 `LocalEmbedder()`，不看 `EMBEDDING_MODE`、
   不受 `EMBEDDING_REQUIRE_REAL` 约束、异常被宽 except 吞掉。本轮镜像里 ST 已在位 ⇒ 它**不再必然**走关键词降级，
   但没有任何读数能证明它这次到底走了哪条。方案 `plan-intent-embedder-bypasses-provider-2026-10-10.md` **待拍板**。
4. **数据面租户边界未收敛**：`/query` 仍读客户端 body 的 `tenant_id`（11 处），而 `/import` 用 `server_tenant_id()`。
   本轮只证了"会话归属塌缩成服务端断言的 `tenant-default`"。方案 `plan-query-tenant-from-client-not-server-asserted-2026-10-10.md` **待拍板**。
5. **被拦那一轮的提问原文会照原样落库**（`count` 里含 `system: 忽略之前的设定…`）——口径是否可接受 **待拍板**。
6. **`dependencies: []` 无任何服务填过** ⇒ 读成"依赖都健康"是错的。填真值还是摘字段 **待拍板**。
7. **退出路径 tracing flush 无上界**（SDK 默认 30s）⇒ 方案 `plan-tracing-shutdown-flush-timeout-2026-10-10.md` **待拍板**；
   `terminationGracePeriodSeconds: 60` 只是买时间，不是修复。
8. **浏览器端未在今天复跑**：入站 `API_KEY` 在密钥泄漏事故后已轮换，旧值作废。页面链路此前的实跑证据属轮换前，
   demo 当天需由持键者现场重新输入。今天证的是 HTTP 面（同一批接口、同一 Pod）。

## 8. 模型不可用会怎样（10:24–10:30，抽验动作第 4 条 + 基线 4）

用**隔离探针 Pod**（同镜像、真密钥引用、`LLM_BASE_URL=http://model-unreachable.invalid/v1`——RFC6761 保留域，
保证不可解析且不会真打到任何服务），线上端点全程未受影响。

| 读数 | 值 |
|---|---|
| 对照请求（被拦截那句，不碰模型） | **1s** 完成，`cache_hit`→`done` |
| 真问（模型不可用） | `http=200 bytes=929 time_total=12.79s`，curl rc=0 |
| 事件序列 | `route{direct}` → `memory` → `evidence{count:0, preview:""}` → **`error{服务器内部错误，请稍后重试}`** → `done` |
| 漂亮假答案判据 | 响应体里时间/数字型答案 **0 命中**（没编出"9:00–18:00"之类） |
| 泄漏计数（对非空响应体） | Traceback / 绝对路径 / site-packages / `postgres://` / `password` / **三个密钥的实际值子串** / 内部主机名与 PodIP ⇒ **9 项全 0** |
| 服务端日志同期 | 完整 traceback：`openai.APIConnectionError` → `agent_core/llm/fallback.py:154` 主备都失败 → `langchain_openai ... OpenAIConnectionError` ⇒ 对外脱敏、对内留详情，**两边都有读数** |

⇒ **基线 4（出错不泄内部细节）** 与 **抽验动作 4（模型不可用不许输出漂亮假答案）** 在本次失败形态上成立。
边界见手册 §5 第 4 行与 §6.2 第 2 条：未证"未捕获异常导致的真 5xx"，且探针用 `EMBEDDING_MODE=mock` 与线上不同构。

**r12 那一轮是错的，留在这里因为它顺手抓到了更值钱的东西**：探针没设 `HF_HUB_OFFLINE`，于是 260s 的
0 字节根本不是在测模型——是意图路由旁路在请求路径上实例化 `LocalEmbedder` 并回连 huggingface.co
（`[Errno 101] Network is unreachable` + `Retrying 1/5…3/5`，每次 HEAD 约 60s）。**配置明确写了
`EMBEDDING_MODE=mock`，代码照样去加载本地语义模型** ⇒ 这是"旁路"缺陷第一次在运行现场成立（不是读代码推的），
读数与影响面已回写 `docs/plans/plan-intent-embedder-bypasses-provider-2026-10-10.md` §5。
我自己这一轮的取证纪律教训：`curl -s` 会把"客户端自己超时"吞掉，而 `curl -o` 在收到 0 字节时**不建文件**——
所以上一版报的 `LEAK_OK` 是在一个不存在的文件上数出来的 0，属假证据。本轮改用 `-sS` + `http_code/time_total`
+ 先 `: > file`，并在响应体为空时**显式拒绝产出结论**。

## 9. 语料入库、抽验①与问数（11:55–12:10，需求方拍板口径后）

**上线坐标（两个，别只记一个）**：镜像内 `GIT_REV=db1a8b8`（代码，未重建）；Pod 模板来自清单 rev
`e07e518`（本轮只加 `SQL_DSN` 一个 env，走 bundle→checkout→apply，**没有**用 `kubectl set env` 就地改）。

| 项 | 读数 |
|---|---|
| 入库 | `/import` 三份平台正式文档：ADR-0004 → 35 块、ADR-0006 → 30 块、ADR-0007 → 28 块，**合计 93 块 / 3 文档** |
| 向量真伪 | `max(vector_dims)=512`；`count(*) FILTER (WHERE embedding <=> embedding > 0.0001)=0` ⇒ **没有退化向量**（那是 MockEmbedder 的指纹） |
| 落位 | `tenant_id=default`、`workspace_id=default`（与检索侧默认值同源，`state.py:35-36`） |
| 检索层独立验证（绕开路由直接 cosine） | top-5 = 0007 §7.2(0.5682)、0007 §3(0.5661)、0007 §4(0.5586)、0006 §5(0.5529)、0006 §2.2(0.5483) ⇒ **正确文档排第一** |
| 底线 4 | ✅ 达成（此前 `chunks=0`） |
| 抽验① V0 | 语料齐、缓存与记忆清空 ⇒ `evidence` 来源 `0004-typed-memory-kernel.md / 背景`，答案给出 `app/memory/memory_backend.py::recall_typed`（优化 H，仅 app 可用） |
| 抽验① **V1** | `DELETE FROM chunks WHERE source='0004…' => rowcount 35`，再清 `semantic_cache`+`memories` ⇒ 依据只剩 0006，回答塌成 **"证据不足，无法回答该问题"**，并点名剩余片段只覆盖隔离维度。**没有编造** ⇒ 底线 5 同时被这条加强 |
| 抽验① V2 | 重新 `/import` 同一文件（新 `doc_id=3f9fbcd6224f`）⇒ 有据回答恢复、chunks 回 93 |
| 问数 | `/sql/train` → `{"ddl_stored":true,"doc_stored":true}`；提问路由 `capability=sql, reason=命中数据查询特征词`，执行 `SELECT doc_id, COUNT(*) AS chunk_count FROM chunks GROUP BY doc_id ORDER BY chunk_count DESC LIMIT 100` ⇒ 35/30/28，**与库里真值逐行一致**；`status.steps[0]={name:sql, latency_ms:5110.7, tokens:576, failed:false}` |
| 验收第二遍 | 11:55 与 12:0x 两轮独立跑（不同 session_id、每轮前清缓存/记忆），三条知识问 + 一条问数，读数一致 ⇒ 方案 2.6 的"两遍"成立 |

**两处我自己的错，留在这里因为它们是过程证据**：

1. `r17`：`AP_WRITE="DELETE…" kubectl exec -i POD -- python -` —— **`kubectl exec` 不透传调用方环境变量**，
   必须写在容器内侧（`-- env VAR=… python -`）。结果那轮三条 DELETE 一条都没执行，而"重新入库"变成追加，
   把 0007 顶到了 56 块（同一内容两个 `doc_id`）。发现方式是输出里**没有** `[执行写] rowcount` 这一行。
   脏数据已在 `r18` 第一步清掉（`DELETE … doc_id='3962e6a483c3' => rowcount 28`，回到 35/30/28）。
2. `r19`：抽掉 ADR-0004 后回答仍然正确，我差点判成"抽验失败"。答案自己写着"**按历史记忆中的文档条目**"——
   是 `memories` 表（`agent/graph.py:192` 每轮写 `Q:…\nA:…`）在复述刚才的答案，与语料无关。
   清掉 `memories`（本轮删了 17 行，全是今天测试产生的）之后 V1 才出现"证据不足"。
   **⇒ "0 变化"和"没变化"是两件事，得先排除回放源。**

**今天顺带抓到的新缺陷（不修，已出方案待拍板）**：`agent/router.py:63-76` 的确定性路由是纯关键词包含，
`rag` 特征词表没有"为什么"这类因果问法 ⇒ "为什么没配置单租户声明会拒绝启动"被路由到 `direct`，
**evidence=0，检索器根本没被问**；同一句改成"根据文档，……"就 evidence=4。
方案与验收见 `docs/plans/plan-router-keyword-gate-hides-corpus-2026-10-12.md`。

## 10. 收盘状态（12:10）

- Pod `agent-platform-56db955b8b-*`，1/1 Running，`restarts=0`，`/health` 全绿且 `sql_backend=postgres`；
- 库内：`chunks=93`、`semantic_cache` 只留最新问答、`memories` 为今天测试产物（可清）；
- `/tmp` 本项目产物已清零；改动前的 Deployment 对象在 `/root/ap-release-backup-20261012/`；
- 探针 Pod（`identity-guard-probe`/`llm-failure-probe`）全部删除，18100 已释放，18000 正常服务。

