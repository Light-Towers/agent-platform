# Langfuse 观测面接线留证 — 2026-10-13

需求方拍板"接"（runbook §9 ⑰）。方案 `docs/plans/plan-langfuse-wiring-2026-10-13.md`。
**本轮未完成上线**：镜像重建被我自己中止，原因见 §6（这条最重要）。
线上现况读数在 §7——**运行态仍是 R1 的 `0425257`，没有被这轮改动影响**。

## 1. 动手前的三个只读门禁（实测）

| 门禁 | 读数 |
|---|---|
| G1 依赖可解 | 现网镜像内 `pip install --dry-run "langfuse>=4.0.0"` ⇒ `Would install backoff-2.2.1 langfuse-4.17.0 wrapt-2.5.0`，OTel 1.45.1 / pydantic 2.50.1 / langchain-core **零降级**，14.1s 无回溯。**但这条结论不完整，见 §5** |
| G2 现网无既有 Langfuse | `docker ps -a` 无 langfuse/clickhouse；`kubectl get pods -A` 无相关负载；126/125/241 三台 `:3000/api/public/health` 全不通 ⇒ 方案 A.2 里"内网那套早就在跑"是未证实假设，**必须自己起** |
| G3 通道与容量 | SWR mirror 可达（`valkey:8-alpine` 实拉成功）；PyPI 直连 200；`vda2` 余 22G→18G；内存 avail 11G；`ROTA=1` 单盘、无第二块盘 |

## 2. 起栈：四处现场与仓内假设不符

| # | 不符点 | 实测 | 处置 |
|---|---|---|---|
| 1 | 联邦那份 compose **起不来** | 它要发布宿主端口 9000/9091/6379，而这台机上 9000-9001 归 KS minio、9091 归 KS milvus、6379 已被占 ⇒ 六服务里三个撞端口；且 `langfuse-db` 写死 `POSTGRES_PASSWORD=langfuse` | 新增 `deploy/observability/docker-compose.langfuse.yml`：只发布 3000，其余留内网；密钥全 `${VAR:?}` fail-closed；版本 pin 与那份一致 |
| 2 | compose 命令名 | `docker compose` v2 **插件不存在**（`unknown command`），但 `/usr/local/bin/docker-compose` 是 **v2.40.2 独立二进制**（我先误判成 v1 并写进了脚本注释，按 `--version` 改正） | 脚本固定 `docker-compose` |
| 3 | `minio/minio:latest` 拉不到 | mirror 不代理可变 tag，直连 `registry-1.docker.io` 两次超时 | 改用盘上 `RELEASE.2024-01-16T16-07-38Z`，并**实测**其 `/usr/bin/mc` 在位、`mc ready local` 返回 OK（健康检查依赖这两件事） |
| 4 | 无头初始化是否真存在 | 不靠文档，在镜像里 grep：`/app/web/.next/server/chunks/*` 命中 11 个 `LANGFUSE_INIT_*`（含 ORG/PROJECT/PUBLIC_KEY/SECRET_KEY/USER_*） | 采用；且"只建 key 不建用户"不成立（key 属于 project，project 属于 org，org 要有成员），故 env 里保留 user 两键 |

## 3. 我自己的一个 bug（第一次起栈失败的真因）

`langfuse-worker` 用 YAML 锚点继承 `langfuse`，我**没显式覆盖 `image`** ⇒
worker 容器拿的是 web 镜像 ⇒ 两个进程同时对同一库跑 Prisma 迁移 ⇒

```
Applying migration `20240104210051_add_model_indices`
Error: P3018  Database error code: 40P01  ERROR: deadlock detected
DETAIL: Process 72 waits for ShareLock … Process 73 waits for ExclusiveLock on advisory lock
```

web/worker 双双 `Restarting`，`/api/public/health` 180s 不给 200。
清卷（只删我刚建的失败迁移，无业务数据）+ 显式 `image: langfuse/langfuse-worker:4` 后重起，
**第 9 次探测 health=200**，第二道判据 `GET /api/public/projects` 用项目 Basic 凭据返回 200
⇒ 无头初始化真建出了 org/project/key。`/api/public/health` 报 `version=4.57.0`。

## 4. 密钥面

项目 pk/sk 经 **stdin** 写入 `Secret/observability-keys`（`kubectl patch --patch-file /dev/stdin`），
值不进 argv、不落文件、不进聊天。回读只比键名与解码后长度：
`API_KEY / LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LLM_API_KEY` 四键，两个 LANGFUSE 键长度均 42。
栈侧 env 文件 `chmod 600 root:root`、18 个条目，全部只存在于 126。

## 5. A1 在镜像里失败：`包在位 ≠ 集成可用`（本轮真正的技术发现）

第一版镜像（rev `3cd5580`）内跑 A1：

```
ModuleNotFoundError: Please install langchain to use the Langfuse langchain integration
```

而 `pip list` 里 `langfuse 4.17.0` 确实在位。根因在 `langfuse/langchain/CallbackHandler.py:40-45`：

```python
try:
    import langchain                     # ← 只为读 __version__ 选 v1/v0 分支
    if langchain.__version__.startswith("1"):
        from langchain_core.callbacks import BaseCallbackHandler   # 真用的符号全在 core
except ImportError:
    raise ModuleNotFoundError(...)
```

⇒ `langchain` 顶层包是 `langfuse.langchain` 的**导入前置**。缺它时 `tracing.py` 的宽 except
把它吞成空列表，于是"**装了包但集成导不进来**"与"**没装包**"在现场表现完全一致——
正是这次要消灭的那个静默失效。补法：三处声明位（agent-runtime/federation/exhibition）一起
补 `langchain>=1,<2`，并把 `langchain` 纳入 **lint L-4** 的跟踪包（否则下次漏一处照样静默）。

**低成本复验**（不重跑整轮构建，避免 §6 的 IO 代价）：旧镜像起一次性容器、补装
`langchain>=1,<2`（约 10MB 写入）、跑真 import，随后删除：

```
A1 复验: import OK, langfuse 4.17.0 callbacks -> ['LangchainCallbackHandler']
```

⇒ rev `c63682d` 的修复方向成立。**注意本地 venv 一直装着 `langchain 1.4.3`，
所以"十 session 全绿"对这条缺陷毫无免疫力**——依赖类判据必须在镜像里验，不能在开发机验。

## 6. 中止构建的原因：镜像构建本身在伤害同机的 knowledge-service

计划里我把 IO 风险指向"Langfuse 栈是持续写的"，**实测打脸的是构建这一步**：
`docker build` 的 pip 层在 `ROTA=1` 单盘上铺上万个文件时——

| 指标 | 构建期间读数 |
|---|---|
| `/proc/pressure/io` | `some avg10=67.47%`（起栈一小时后也才 1.4%） |
| etcd 告警（近 5 分钟） | **41 条** `slow fdatasync` / `took too long` |
| milvus 累计重启 | **30 → 31**（又死一次；AGENTS.md 记的正是这条链） |
| KS web | `/health` 仍 200（当时还没打到用户可感知的程度） |

⇒ 我中止了构建。**中止方式本身也是我的错**：`pkill -f "docker build"` 的 pattern 匹配到
我自己那条 ssh 命令行，把自己的 shell 一起杀了（退出码 255），所以现场状态必须回读而不是相信命令输出。
构建被打断在 tag 之前，因此**没有产生半成品镜像被误用**：`agent-platform:dev` 仍指 `3cd5580`。

这条改变了 R2 的对策对象：常驻的 Langfuse 栈（六个容器空转一小时）实测 `avg10` 只有 1.4-1.9%，
**真正的 IO 大头是发布通道的镜像重建**。所以"取证完即停"这条约束留着，但排期上要把
**构建放在静默窗口**，而不是把注意力只放在观测栈上。

## 7. 现场状态（本轮结束时，全部回读而非推断）

| 项 | 读数 |
|---|---|
| 线上 Pod | `agent-platform-7d7944fdfc-hp9p8`，`GIT_REV=0425257…`（**仍是 R1，本轮未 apply**） |
| 本地 moby tag | `agent-platform:dev` → revision label `3cd5580…`（A1 失败的那版，**不可分发**） |
| 仓库 HEAD | `c63682d`（含 langchain 修复 + 控制台新灯） |
| 观测栈 | 六个 `lf-*` 容器 Up 约 1 小时，依赖四个 healthy；数据卷保留 |
| 集群 Secret | 四键齐（两个 LANGFUSE 键长度 42） |
| 清单差集 | live env 名 vs 期望 env 名：**只多 `LANGFUSE_HOST/PUBLIC_KEY/SECRET_KEY` 三项**，无其他漂移 |
| 126 工作区 | `/opt/agent-platform` 已 checkout 到 `c63682d`（干净，无未提交改动） |

## 8. 还差什么才算"接上了"

1. 在**静默窗口**重跑 `build.sh c63682d…` → 镜像内复验 A1（`import langfuse.langchain` 成功）。
2. `distribute.sh` → `apply` → `rollout` → `verify.sh`（port-forward 无 restart 子命令，须 stop+start）。
3. 回读新 Pod：`GIT_REV`、`/health` 的 `langfuse_enabled/ready` 两盏灯。
4. **A3（唯一算数的判据）**：`deploy/observability/langfuse_proof.py` 打一次带 marker 的真提问，
   在 Langfuse 里查到该 trace，且 GENERATION 的 input 含本次原文、usage 双值齐。
   它不把判据压在"Langfuse trace id == W3C trace id"上（本 app 不回写 traceparent 响应头，
   id 映射关系作为**读数**打印）。
5. 取证完 `langfuse.sh stop`（保留卷），并回写 runbook §6.2 第 11 条与 §9 ⑰。

## 9. 完成段（同日稍后）：A3 真通过，以及接上之后才发现的 D-LF-1

§7/§8 是当时的快照，**已被本节取代**。线上对象 = rev `6ac466af`，Pod `agent-platform-85794678c-9hjg4`，
node **ambari01(241)**，imageID `c18dc76a93f8f`，restarts 0。

### 9.1 六步通道跑通的两处非显然事实

- **构建换机后必须补一次"本节点 containerd-k8s 导入"**：`distribute.sh` 的目标列表只覆盖*其余*节点，
  构建机自己的 moby 与 containerd-k8s 又是两套库。本次三节点 CRI 回读一度是
  `125=c18dc76a / 126=c18dc76a / 241=ff65490f(旧)` ⇒ 而新 Pod **恰好调度到 241**。
  可变 tag + `IfNotPresent` 下这不是 `ErrImagePull` 而是**静默跑旧代码**，比报错更坏。补导入后三节点一致。
- **`verify.sh` 原先用 `docker run` 读镜像内 GIT_REV，读的是 moby 库里那次中止构建的残留**
  （`3cd5580`，created=2 hours ago），同期 Pod 内是 `c01e9cf` ⇒ 报出假 FAIL。改为 `kubectl exec` 读
  跑着的 Pod 内那份，并列打印 node/imageID/restarts（`0e0f6e5`）。

### 9.2 A3 读数（v4 真实取数面）

`GET /api/public/v2/observations?fromStartTime=&traceId=&fields=io,usage`，一次 rag 问答 **2 条 GENERATION**：

| 观测 | name | usage in/out | latency | input 含 marker | input 含 `[来源:` |
|---|---|---|---|---|---|
| 答案生成 | ChatOpenAI | 1403 / 1547 | 16.568s | HIT | **HIT**（摊平后 2356 字符） |
| 路由决策 | ChatOpenAI | 475 / 164 | 4.117s | HIT | miss（路由本来不看证据，正常） |

trace id `a748c6fcaa7c418c92e274c89814338b` **== 注入的 W3C id**（作为读数记录，不是前提）。

三条读数纪律（都是本轮踩出来的，写探针的人必看）：
1. **v4 `events_only` 撤了 v1 读数 API**：`/api/public/traces|observations|sessions|metrics` 全 404，
   body 明写原因；可用的是 `v2/observations`。`/api/public/v2/traces` 不存在（404 返回 HTML 页面）。
2. **`fields=` 与默认投影互斥**：`fields=io,usage` 里 `name/modelId` 被挤成 null，默认投影里没有 input/output；
   ⇒ 要"原文+用量+名字"得两次取按 id 合并。`modelId` **在两种投影里都是 null**（模型名在库内 `model` 列、
   UI 可见）⇒ 不得声称"哪个模型"是 API 可读列。猜错 fields 名时响应"键不存在"，与"真的没有内容"长得一样。
3. **载荷是多层 JSON 编码的 `\uXXXX` 字面量**：`ensure_ascii=False` 只能解自己那一层 ⇒ ASCII marker 照常命中、
   中文 needle（`[来源:`）恒 miss。必须先 `_flatten()` 再匹配。
   另外 **SSE 事件帧是平铺的**（`_sse` 把 `payload.type` 提成事件名），按 `d["payload"]` 读恒得 `{}`
   ——上一轮据此差点误报"没接上"。

### 9.3 D-LF-1：接上 Langfuse 把 Jaeger 面顶掉了

现象（rev `c01e9cf`）：`/health` 报 `otel_status=ACTIVE`，但同窗口一次 `GET /health` + 一次 `POST /query`
在 Jaeger 里 `rowcount=0`；Jaeger 收到的最后一条 span = 旧 Pod 优雅关闭那一刻。三台机器时钟差 ≤1s（已量），
Jaeger 容器 Up 13 days、`/api/services` 200、Pod 内到 `4318` 通（GET 得 405 = OTLP 端点正常拒绝 GET）。

根因在 Pod 内用**假凭据**复现（不是推断）：`get_langfuse_callbacks()` 构造 Langfuse 客户端时把全局
TracerProvider 换成自己那份（processors=`['LangfuseSpanProcessor']`），随后 kernel `init_tracing` 走
"复用已存在 provider"分支，按"宿主自带 exporter"的前提**什么都不挂**。反序实验：先 init 再构造 Langfuse ⇒
provider 是我们的，Langfuse **复用并追加**自己的 processor = `['BatchSpanProcessor','LangfuseSpanProcessor']`，
callback 不受影响。附带发现第二半：注入 exporter 的分支把 processor 挂在随后被丢弃的自建 provider 上（孤儿）。

修法三层（`e919caa`）：装配顺序上移 + 复用分支"探不到就补挂"（探测读私有结构失败一律当作"没有"，
宁多挂少判）+ `tests/observability/test_provider_reuse_otlp.py` 三条钉不变量。
本地验证：`--extra otel` 18 passed、agent-core 349 passed/8 skipped、agent_server 90 passed、
ruff + lint_architecture + check_doc_sync 全绿。
**修后现网复验（同一个新 Pod）**：`e2e_traceparent.sh` → `span 数=8`、含 `POST /query`、trace id==注入 id、rc=0；
`langfuse_proof.py` → A3 PASS。两个判据同时为真才算接完。

顺带修的两条取证脚本缺陷（都是"看着跑了、其实什么都没发生"那一族）：
- `e2e_traceparent.sh`：`SPANS=$(curl -sf ... | grep -c ...)` 在 `set -e pipefail` 下于 404 时**直接终止脚本**，
  解释原因的 FAIL 行永远打不出来 ⇒ 改为先落盘再判，并写清"404/连不通/服务名不符"三种情形怎么分。
- `langfuse_proof.py`：命中语义缓存时图不跑、模型不调用 ⇒ 原来按"查不到=没接上"报 P1 FAIL 是**假阴性**。
  现在候选问题轮转 + 退出码 4 专指"取证不成立但平台没错"，并加只读复核模式（不重发提问、不白污染缓存、
  且不再要求 API_KEY）。marker 后缀**不改变语义**，查重按向量相似度 ⇒ 改几个字符没用。
