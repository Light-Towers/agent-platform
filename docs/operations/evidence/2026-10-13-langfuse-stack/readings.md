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
