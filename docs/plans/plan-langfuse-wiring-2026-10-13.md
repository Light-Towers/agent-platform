# 方案：接上 Langfuse 观测面（D5.5 第二半）— 2026-10-13

> 需求方 2026-10-13 拍板：**接**（runbook §9 ⑰ 由此闭合）。
> 本文件是 AGENTS.md「所有代码优化/重构必须先制定方案」要求的那份方案，含目标/影响面/迁移策略/验收标准。
> 动手前已完成三个只读门禁（§1），三条都过才允许改代码。

## 0. 目标与非目标

**目标**：让"本次到底把什么原文推给了模型、逐次用量多少"这一层有第三方观测屏，
并把「客户端包没装导致静默不报」这个盲区从**结构上**消掉（不是靠记性）。

**非目标**：
- 不做 Langfuse 的告警/评分/数据集/实验面（那是 12-04 那一轮的事）。
- 不把 Langfuse 的估算金额接进平台页面（底线 5：平台只报用量，金额以模型平台账单为准）。
- **不做常驻服务**：取证完即停（理由见 §4 风险 R2）。

## 1. 动手前的三个只读门禁（2026-10-13 实测，全部已过）

| 门禁 | 判据 | 实测读数 |
|---|---|---|
| G1 依赖可解 | 现网镜像内 `pip install --dry-run "langfuse>=4"` **不得**降级任何现有包、不得回溯 | `Would install backoff-2.2.1 langfuse-4.17.0 wrapt-2.5.0`；OTel 1.45.1 / pydantic 2.50.1 / httpx 全 `already satisfied`；**14.1s 解析完成，零回溯** ⇒ 2026-09-29 那次"加 langfuse 后 pip 无限回溯"的根因（v2 锁 `langchain-core<0.4` vs `langgraph>=1.2.10`）确已由 S4（`a5fa9031`）迁 `langfuse.langchain` v3+/v4 契约终结 |
| G2 现网无既有 Langfuse | 不能凭"编排文件里写了"当作"内网有服务" | 126 `docker ps -a` 无任何 langfuse/clickhouse 容器；`kubectl get pods -A` 无相关负载；126/125/241 三台 `:3000/api/public/health` **全部不通** ⇒ **必须自己起**，方案 A.2 里"内网那套早就在跑"是未证实假设 |
| G3 拉取通道 | 镜像能进得来、盘装得下 | moby 配了华为云 SWR mirror，`docker pull valkey/valkey:8-alpine` 成功；PyPI 直连 200；`/` 与 `/data` 同一文件系统 `vda2`，**98G 用 72G 余 22G**；内存 15G（avail 11G） |

## 1.5 G1 的结论被 A1 证伪了一半（本方案最重要的一条）

第一版构建（rev `3cd5580`）出来后，在**镜像内**跑 A1：
`import langfuse, langfuse.langchain` → **`ModuleNotFoundError: Please install langchain to use the
Langfuse langchain integration`**。而 `pip list` 里 langfuse 4.17.0 明明在位。

根因（读 `.venv/.../langfuse/langchain/CallbackHandler.py:40-45`）：该模块开头是

```python
try:
    import langchain                       # ← 只为读 langchain.__version__ 选 v1/v0 分支
    if langchain.__version__.startswith("1"):
        from langchain_core.callbacks import BaseCallbackHandler   # 真正用的符号全在 core
```

⇒ **`langchain` 顶层包是 `langfuse.langchain` 的导入前置**，而我们只声明 `langchain-core`/
`langchain-openai`。缺它时 `tracing.py` 的 `except Exception` 会把它吞成空列表 ——
**"包装了但集成导不进来"与"包没装"在现场表现完全一样**，正是这次要消灭的静默失效。

所以 G1 那句"只新增 3 个包、零降级"**不足以支撑结论**：它只回答了"langfuse 本人与现有栈是否共存"，
没回答"装完之后集成到底能不能 import"。**教训：依赖门禁必须验到"目标 import 真成功"这一层，
不能停在解析器不报错。** 补法与影响：

- 三处声明位一起补 `langchain>=1,<2`：`agent-runtime[langfuse]`、`agent_federation[observability]`、
  `exhibition-agent[langfuse]`（只补一处，另外两侧照样静默不报）。
- lint **L-4 的跟踪包加 `langchain`**（`scripts/lint_architecture.py`），让"三处下界一致"由门禁而非
  记性保证 —— 这是 AGENTS.md「三层齐备」里缺的第三层。
- 镜像内重跑 `pip install --dry-run "langchain>=1,<2"`：**`Would install langchain-1.4.5`，其余全
  `already satisfied`，9.7s 零回溯**（langsmith/orjson/zstandard 等都已在位，因为它们是
  langchain-core 的传递依赖）。
- 本地 venv 早就装着 `langchain 1.4.3`（langchain-core 的邻居），**所以十 session 全绿这件事
  对这条缺陷毫无免疫力**——这就是为什么 A1 必须在镜像里跑，不能在开发机跑。

## 2. 影响面（六处，逐处标"改/不改"）

| # | 面 | 改什么 | 为什么必须改在这里 |
|---|---|---|---|
| 1 | `Dockerfile` pip 安装行 | `./packages/agent-runtime` ⇒ `./packages/agent-runtime[langfuse]` | extras 声明位归一在 agent-runtime（lint L-4 监控）；根包无 langfuse extra，写成 `.[langfuse]` 会被 pip **只告警不报错**地丢掉（memory-embed-local 那颗雷，2026-10-10 实踩） |
| 2 | `/health` 新灯 | 加 `langfuse_enabled`（三键齐）**与** `langfuse_importable`（包真在位）两个布尔位，**不回显任何值** | 现契约的 `llm: true` 已被证明"配置项非空 ≠ 可用"。只报前者就还是"关了和坏了分不清"；两个位分开才第一次能回答"到底是没配还是没装" |
| 3 | `deploy/k8s/20-agent-platform.yaml` | `LANGFUSE_HOST` 走 ConfigMap；`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` 走 `Secret observability-keys` 的 `secretKeyRef` | 与 `LLM_*`（CM）/ 密钥（Secret）现有分工一致；**清单里只写引用名，不写值** |
| 4 | 126 侧观测栈 | **改用新增的 `deploy/observability/docker-compose.langfuse.yml`**（只发布 web 的 3000，其余留在 compose 内网；密钥全部 `${VAR:?}` fail-closed）。**原方案"复用联邦那份"已被现场实测推翻**，见下方 §2.4a | 联邦那份要发布 9000/9091/6379 三个宿主端口，而这台机上它们分别归 knowledge-service-minio、knowledge-service-milvus 与另一进程 ⇒ 六服务里三个起不来；且那份的 `langfuse-db` 写死 `POSTGRES_PASSWORD=langfuse`，弱默认值在共享主机上不可接受。**两份的分工写在文件头**：版本真值在联邦那份，本文件是 126 的运维形态 |
| 5 | 项目凭据 | **新建一套**（旧键对曾随提交进过仓库历史，不能复用）；经 `LANGFUSE_INIT_*` 无头初始化注入，值只在 126 的 env 与 k8s Secret 里流动 | 任务书硬口径："密钥与配置只写从哪个配置项注入，不把真实值落任何文件"；今日刚在 §4.10 第 13 行登记过我自己违反它的后果 |
| 6 | 文档 | runbook §6.2 第 11 条由"未接"改"已接 + 怎么停"；§9 ⑰ 闭合；`env-126-inventory` 补栈的真实读数 | 观测面是"三层各自能讲到哪一句"的中间层，写错就直接违反底线 5 |

### 2.4a 现场推翻原方案的那次实测（为什么不能复用联邦那份编排）

| 宿主端口 | 现在被谁占着（`docker ps` 实读） | 联邦那份要什么 |
|---|---|---|
| `9000-9001` | knowledge-service-minio | clickhouse 要发布 `9000:9000` ⇒ **撞** |
| `9091` | knowledge-service-milvus | minio 要发布 `9091:9001` ⇒ **撞** |
| `6379` | 已有进程监听（`ss` 实读 `0.0.0.0:6379`） | valkey 要发布 `6379:6379` ⇒ **撞** |
| `3000` / `5432` / `8123` | 空闲 | langfuse web 需要 3000 ⇒ 唯一必须对宿主暴露的端口 |

另两条通道事实：**126 没有 `docker compose` v2 插件**（`docker: unknown command: docker compose`），
但 `/usr/local/bin/docker-compose` 是 **Compose v2.40.2 的独立二进制**（我先把它当成 v1 写进了脚本注释，
按 `docker-compose --version` 实测改正）⇒ 脚本用 `docker-compose` 命令名，不能写成 `docker compose`。
`langfuse-db` 在那份里写死 `POSTGRES_PASSWORD=langfuse`，且 web 的 `DATABASE_URL` 把同一个弱值拼进连接串。

**不改的东西（刻意列出防误伤）**：`agent/llm.py` 的回调装配点（构造期挂 primary+fallback，已正确）、
`agent_runtime/tracing.py` 的三态软导入（凭据缺→[]、导入失败→[]+warning、齐→挂 handler，由 `test_tracing.py` 钉住）、
`config.py:53-55` 三个键名。**代码侧一行都不用动**——这正是方案 A.2 那句"填上三个配置就亮"的真实含义，
它缺的只是"镜像里得有包"和"清单里得有引用"这两件分发侧的事。

## 3. 迁移与顺序（每步都带"读不到即未生效"的回查）1. **栈先起，应用后动**：`docker compose up` 六服务 → 回查 `GET /api/public/health` 返回 200 且版本可读。**栈不通就不碰镜像**（否则新 Pod 带着凭据反复重试外连）。
2. **凭据落地**：无头初始化建 org/project/API keys → 用 `kubectl patch secret --patch-file -`（**stdin，不进 argv**）写入两个键 → `kubectl create configmap --from-literal=LANGFUSE_HOST=…`。回查只比**长度**与键名，不打印值。
3. **镜像**：改 Dockerfile → `make ci` 本地全绿（含新灯用例）→ git bundle → 126 `fetch/checkout` → `build.sh <rev>`（rev 门禁）→ `distribute.sh` → `apply` + `rollout` → `verify.sh`。
4. **回查生效**（不看 apply 退出码）：Pod 内 `GIT_REV` == 期望 rev；`python -c "import langfuse"` 成功；`/health` 两盏灯均为 true。
5. **取证（唯一验收动作）**：清 4 个回放源后发**一条**带唯一标记的 `/query` → 用项目凭据查 `GET /api/public/traces`，断言该 trace 存在、且其 LLM span 的 input 里**能看到本次检索出来的资料片段原文**、output 是模型答话、usage 两个数非空。截图 + API 读数入库留证。
6. **停栈**：`docker compose down`（数据卷保留在 126，不带进任何提交）。演示当天按 runbook 重新 `up` 一次即可。

## 4. 验收标准（四条，缺一条即宣称未接上）

| # | 标准 | 判据（可复现命令） |
|---|---|---|
| A1 | 包真在镜像里 | Pod 内 `python -c "import langfuse, langfuse.langchain; print(langfuse.__version__)"` 成功；`/health` 报 `langfuse_importable=true` |
| A2 | 配置真进容器 | Pod 内 `env` 中三个键**非空**（只比长度）；`/health` 报 `langfuse_enabled=true` |
| A3 | **trace 真落在 Langfuse 里**（唯一算数的判据） | `deploy/observability/langfuse_proof.py` 退出码 0：按注入的 trace id 在 `GET /api/public/v2/observations?fields=io,usage` 查到 GENERATION，其 input 含检索片段原文、usageDetails 双值非零。（原写法 `curl /api/public/traces` 作废——v4 `events_only` 撤了该端点，见 §7 顺带修正） |
| A4 | 主链路不因观测中断 | 把 `LANGFUSE_HOST` 指向 `.invalid` 重启一次应用，`/query` 仍完整返回事件序列（软降级必须是 fail-open，由 `test_tracing.py` + 现网各证一次） |

> **不得凭 A1/A2 宣称"接上了"**——A.2 原文写得很清楚：客户端包没装时平台只记一行日志就静默不报，
> 配了环境变量 ≠ 接上。**只有 A3 是验收判据**，A1/A2 是它的前置。

## 5. 风险与对策| 风险 | 具体 | 对策 |
|---|---|---|
| **R2 IO 放大**（本机最真实的风险，**但对策对象被我搞错了一次**） | 原判断是"ClickHouse + MinIO 持续写会压垮 `ROTA=1` 单盘"。实测相反：六个容器空转一小时 `/proc/pressure/io` 仅 `avg10=1.4-1.9%`；**真正的大头是发布通道的 `docker build`**——pip 层铺上万个文件时 `avg10=67.47%`、同机 etcd 近 5 分钟 41 条 `slow fdatasync/took too long`、milvus 累计重启 30→31（又是 AGENTS.md 记的那条链） | ① **构建排到静默窗口**，且构建期间持续回读 `pressure/io` 与 milvus 重启计数，越线即中止（本轮我就是这样中止的）；② 观测栈仍按需起停（成本低、留作纪律）；③ 只喂**一条**取证提问，不做压测；④ 依赖类判据用一次性容器低成本复验（`langchain` 那条只花 ~10MB 写入），不要为验证而重建 |
| **R6 依赖门禁验错层**（本轮新增） | G1 只验了"解析器不报错、无降级"，结果镜像里 `import langfuse.langchain` 仍失败——它的前置是顶层 `langchain` 包 | 依赖类验收判据必须是"**目标 import 真成功**"，且在**镜像内**跑（本地 venv 带着 `langchain 1.4.3`，十 session 全绿对这条缺陷零免疫力）。已把 `langchain` 纳入 lint L-4 跟踪包 |
| R3 盘满 | 栈镜像 + 数据卷吃 22G 余量 | 每步 `df -h /` 回读；余量低于 12G 即停止并如实报告，不硬塞 |
| R4 新灯被误读成能力位 | `langfuse_enabled=true` 只代表"三键非空" | 页脚与 runbook §3 的"两处别读错的字段"里并列写清；判据只认 A3 |
| R5 密钥面 | 项目 sk 一旦进过 argv 就等于对全主机公开 | 全程 stdin/env，值不进 argv、不落文件、不进聊天；留证只记长度与指纹前缀 |

## 6. 回退

镜像可回退（`agent-platform:dev` 是可变 tag，`rollout undo` 回不了内容——这是已登记的通道缺陷 #7）：
回退方式 = 把 Dockerfile 改回无 extra 的 rev 再走一次六步通道。
配置面回退 = 从 deployment 摘掉三个 env 引用并滚动，`/health` 两盏灯回落 false，主链路不受影响（软降级）。
栈回退 = `docker compose down`，卷保留或删除均可，平台侧无状态依赖。

## 7. 上线后实测出的缺陷 D-LF-1：两个观测面互相顶掉（装配顺序决定谁活着）

**现象**（2026-10-13，rev `c01e9cf`，Pod 在 <internal-host>）：Langfuse 面 A3 通过（原文 + 用量可查），
但 **Jaeger 面对 `/query` 彻底静默**——同窗口内一次 `GET /health` + 一次 `POST /query`，
Jaeger 按服务查近 10 分钟 `rowcount=0`，注入的 traceparent id 直查 404；而 `/health` 报
`otel_status=ACTIVE`。即"一盏说活着、一盏其实瞎"。

**根因**（在 Pod 内用假凭据复现，非推断）：`build_chat_model()`（`main.py:226`）内的
`get_langfuse_callbacks()` 会构造 Langfuse 客户端，**该构造把全局 TracerProvider 换成它自己的**
`opentelemetry.sdk.trace.TracerProvider`，processors 只有 `['LangfuseSpanProcessor']`。
随后 `init_tracing()`（`main.py:282/291`）走到 `agent_core/tracing.py:430-438` 的"复用已存在的
全局 provider"分支——该分支的前提是"宿主 provider 自带 exporter，不必白挂"，**这个前提对
Langfuse 的 provider 不成立**：它只导给 Langfuse，不导 OTLP。于是本平台的 OTLP 导出器**从未挂上**，
Jaeger 收到的最后一条 span 时间戳 = Pod 启动那一刻（旧 Pod 优雅关闭前的最后一批）。

**为什么反序是对的**（同实验）：先 `init_tracing()` 再构造 Langfuse ⇒ 全局 provider 是我们建的
（带本服务的 resource 与 sampler），Langfuse **复用**它并把 `LangfuseSpanProcessor` **追加**进去，
最终 processors = `['BatchSpanProcessor', 'LangfuseSpanProcessor']`——一棵 span 树、两个后端，
这正是 OTel 的标准扇出形态。callback 侧不受影响（callbacks=1）。

**修复（三层，缺一层就还是靠自觉）**：
1. **装配层**（`applications/agent_server/main.py`）：把 OTel 接线整块移到 `build_chat_model()` **之前**。
   判据不是"能跑"，而是"全局 provider 由本平台创建"。
2. **单一实现层**（`packages/agent-core/agent_core/tracing.py` 复用分支）：复用宿主 provider 时
   **best-effort 探测其是否已有指向同一 endpoint 的 OTLP 导出**；探不到就挂上自己的 BatchSpanProcessor，
   并且**只有确认存在 OTLP 出口才报 ACTIVE**，否则 `DEGRADED/foreign_provider_no_otlp_exporter`。
   把"静默瞎掉"变成"灯说真话"（R5 同源）。
3. **门禁层**：内核用例固定这条不变量——宿主 provider 先存在时，`init_tracing` 之后该 provider 上
   必须有 OTLP 出口；`agent_federation`（`api/server.py:61` 早于模型构建）本来就是正确顺序，
   作为对照不参与改动。

**影响面**：`agent_core/tracing.py` 复用分支、`agent_server/main.py` 启动顺序、新增内核用例。
不改对外契约、不动事件帧、不动清单。**验收**：`e2e_traceparent.sh` 退出码 0 且注入 id 在 Jaeger 命中；
`langfuse_proof.py` 仍 A3 PASS（两盏灯不能互相顶掉，必须同时真）；`/health` 的 `otel_status` 与
Jaeger 实际可查性一致。

**顺带修正本方案 §4 A3 的取数方式**：v4 `events_only` 部署下 `/api/public/traces` 已撤销（404），
算数判据改用 `GET /api/public/v2/observations?fromStartTime=&traceId=&fields=io,usage`。
