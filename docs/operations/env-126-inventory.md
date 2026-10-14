# 126 环境事实基线（env-126-inventory）

> 来源：2026-10-10 对 192.168.100.126（hostname ambari03）的**只读**盘点，含代码同步通道专轮、三次读数校准（e12/e13/e14/e16）与 §7 待查项逐条验证（e17–e25）。
> 目标：把"每次上 126 都要重新发现一遍"的环境事实固化成基线，每个结论都能指到具体读数与可原地复现的命令。
> 取证纪律：全程只读（不安装/不修改/不重启/不停止/不删除既有物）；脚本双端 MD5 一致 + `bash -n` 通过；输出落盘后全文取回阅读；结束即清理并宽口径复核零残留。
> 与既有文档分工：本文 = **环境事实基线**；[deploy/k8s/VERIFICATION.md](../../deploy/k8s/VERIFICATION.md) = 部署演练报告；[deploy/k8s/README.md](../../deploy/k8s/README.md) = 搭建步骤与踩坑表；[testing-playbook.md](testing-playbook.md) = 测试实跑流程。
> 对应长期记忆：126 代码同步通道、126 双容器运行时形态、126 宿主 Python 与 .venv 可用性（project_environment_configuration）；判定同步方式的只读取证判据（tool_experience）。
> **时区约定**：126 宿主为 +0800，docker/k8s 的 API 字段给 UTC（尾缀 `Z`）。本文所有换算已标注 +0800，读时勿混。

## 0. 取证脚本（可核对，产物已清理）

| 脚本 | 本机 MD5（与远端 `md5sum` 一致） | 输出行数 | 取到什么 |
|---|---|---|---|
| e7_sync.sh | 5e892fb6（短） | 256 | FETCH_HEAD = 本地 bundle 路径、logs/HEAD 7 条、pack 时间线 |
| e8_sync2.sh | 8b5fbab5（短） | 185 | /tmp 零残留、/root 脚本无同步关键字、last -F 来源 IP |
| e9_channel.sh | 1d381fad（短） | 303 | auth.log 98 次 publickey 同指纹、sshd -T、by push=0 |
| e10_cleanup.sh | 53b6b1ec（短） | — | 显式 LIST 删除 + 零残留复核 |
| e11_volprobe.sh | 9fa45ad4（短） | 103 | volumes 计数口径归因（metadata.db mtime） |
| e12_calib.sh | 32b5ef4c5d59e289310ee50df41755f0 | 142 | docker/compose 版本、容器名与镜像、卷、磁盘 |
| e13_gap.sh | dba9b17e95bf93a23659f2f090fe02e6 | 136 | kubectl 全量 pod、pod 重启详情、模型缓存定位、镜像计数口径 |
| e14_ctrl.sh | 3a05e8cec307823e886e4284f741d088 | 622 | rev 差值 548、ap-models 定位、控制面双采样定性 |
| e16_venv.sh | d880c9dcc9334ee4351dbcd51144854d | 136 | venv 断链真实目标、454 包完整度、基座镜像清单 |
| e17_gaps.sh | cf67793b739c50034c1a33a5b0d67193 | 174 | 宿主/KS/pod 三侧配置生效值、pod 内依赖有无、KS 容器代码布局、`docker system df` |
| e18_gaps2.sh | cc7c46fb5aef21dec4c28466f63d4656 | 141 | ConfigMap/Secret 键、KS 镜像依赖、milvus 停机取证、**236 个 .py 与仓库 md5 比对** |
| e19_close.sh | 28047855d3bc1933445bfb266acbd605 | 76 | milvus 停机前日志（etcd 超时）、全栈重启普查、pod imageID 闭合 G7、CM 死键判定 |
| e20_last2.sh | a5da34bd44ee27c5e86399d04f6e23da | 108 | etcd 慢日志窗口、milvus 15 次重启时间序列、manifest vs 线上 deployment、build cache 明细 |
| e21_upstream.sh | 82b035db857b5ef925f817c5e5a752bc | 47 | etcd `slow fdatasync` 计数（114 / 882）、三个 KS 镜像的 Created 与 labels |
| e22_hotedit.sh | 0483b968f16f85c4ec2fe0826ffb98af | 32 | 容器内 .py mtime 分布 ⇒ **8 个热改文件**逐个定位 |
| e23_upstream.sh | aefdb0e4188e0ae72c137335e736614a | 195 | G5 再上游（磁盘性质/PSI/cgroup IO 限制/slow fdatasync 按日分布/故障窗口宿主活动/dmesg）+ G2 指认（last-applied vs LIVE、apiserver 审计、history）|
| e24_hotedit_diff.sh | 3aca0fac231be2d50b7f7ee63b7a0982 | 117 | `docker diff` 权威热改清单 + 8 个热改文件三方判据（容器 blob 是否曾入库 / vs HEAD / vs 构建时点 rev）+ diff 正文 |
| e25_verify_gap.sh | c59f73261175677804d5ccacf11d8440 | 98 | 三 eval 文件容器 md5 双测法复验、`import_router.py` 正确路径补判、容器独有行抽样、可写层规模与第 9 个 .py 定性 |

## 1. 一句话环境形态

126 是**共用测试机**（不是专用部署机）：docker(moby) 栈与 kubeadm 控制面所用的**隔离第二实例** containerd-k8s 并存，两套镜像库互不可见；项目代码在宿主有两份 checkout，而**线上运行的代码在镜像里**，镜像内 rev 比宿主 checkout **落后 548 个提交**；代码进来的唯一通道是 `git bundle` + `scp`（**不是** git push）；宿主 Python 低于项目要求且没有 uv，所以**不能在宿主跑项目测试**；knowledge-service 侧存在**第二条不经 git 的代码通道**，是线上代码漂移的成因。另两条本轮验证补上的形态特征：**运行时配置已被运行时改写**（改 ConfigMap 的 LLM_* 不生效，见 §4.6），以及**该机的磁盘 IO 会拖垮 etcd 再连带拖垮 milvus**（依赖级联不是人为，见 §4.7）。

## 2. 代码同步通道（本机 → 126）

### 2.1 结论链条

```
本机(main @ <rev>) --git bundle create /tmp/ap-<rev>.bundle <旧rev>..HEAD-->
  scp/sftp over ssh:22 (root 公钥) --> 126:/tmp/
    --git fetch /tmp/ap-<rev>.bundle main--> FETCH_HEAD
      --git checkout <rev>--> detached HEAD @ <rev>  (/opt/agent-platform)
        --build.sh <full-sha>--> 镜像 agent-platform:dev（rev 门禁 + GIT_REV 双通道回读）
          --distribute.sh--> docker save|gzip → scp 125/241 → ctr -n k8s.io images import
```

判为 bundle 而非 push 的**决定性读数**：126 的 /opt/agent-platform/.git/FETCH_HEAD 内容为
`6cebaa56…<TAB>branch 'main' of /tmp/ap-6ce.bundle`，来源字段是**本地文件路径**。

### 2.2 "126 不是 push 目标"的四重证据

| 证据 | 读数 |
|---|---|
| reflog 动作词 | grep -ac 'by push' .git/logs/HEAD = **0**（push 进接收端必写 "update by push"） |
| 仓库形态 | core.bare = **false**；仓内**无 master 分支**（git reflog show master → unknown revision） |
| 接收策略 | receive.\* 与 push.\* **均未配置** ⇒ 默认拒绝推当前检出分支 |
| 部署 hook | .git/hooks **无自定义**（只有 .sample）⇒ 不存在"推送即部署"链路 |

补充：/opt/agent-platform 与 /opt/ap-iso 两个 worktree **均为 detached HEAD** ⇒ 同步语义是"按 rev 检出"，不是"按分支跟踪"。

### 2.3 时间线（epoch ↔ pack mtime ↔ auth.log 三方咬合）

| epoch | 北京时间 | .git/logs/HEAD 动作 | 目标 rev | 对应 pack mtime |
|---|---|---|---|---|
| 1790069331 | 2026-09-22 17:28:51 | clone: from https://github.com/Light-Towers/agent-platform.git | 0de90cb | 7f75aa25 (5,172,040) @ 09-22 17:28 |
| 1790070702 | 09-22 17:51:42 | pull origin v3: Fast-forward | d2b9e59 | — |
| 1790071567 | 09-22 18:06:07 | pull origin v3: Fast-forward | 031c89a | — |
| 1790732865 | 09-30 09:47:45 | checkout: v3 → FETCH_HEAD | a5fa903 | ec32ce38 (2,435,280) @ 09-30 09:47 |
| 1790735413 | 09-30 10:30:13 | checkout: a5fa903 → FETCH_HEAD | 30cbf25 | 16a6664c (15,433) @ 09-30 10:30 |
| 1790753577 | 09-30 15:32:57 | checkout: 30cbf25 → 626ec17 | 626ec17 | eb47a90e (665,604) @ 09-30 15:32 |
| 1791536173 | 10-09 16:56:13 | （仅 fetch，无 checkout） | — | 68628483 (3,566,286) @ 10-09 16:56 |
| 1791537113 | 10-09 17:11:53 | checkout: 626ec17 → **6cebaa5** | 6cebaa5 | 9e3d675b (2,664,065) @ 10-09 17:11 |

10-09 17:11:35 与 17:11:52 两次 `Accepted publickey … from 192.168.102.222` 与 checkout 时刻 17:11:53 逐秒对应；16:56:04/05 两次登录对应 16:56 的 pack。

**10-09 17:11 这轮同步只落代码、未产出运行制品**：pod 内 `/srv/agent-platform/GIT_REV` 实测仍是 `626ec1798354d42030ba8a4f6fdd04c1c1b37f86`（e13 [3]），即 09-30 那轮的 rev。⇒ 10-09 17:11 之后没有再走 build.sh/distribute.sh/rollout。

### 2.4 判"是 git checkout 而非逐文件覆盖"

工作区被 git 跟踪的文件 mtime **齐刷刷等于 checkout 时刻**（10-09 17:11），且 dirty = 0、.git/index 为 17:22。17:11 之后唯一变更是 __pycache__ 字节码（可再生，非源码）。逐文件 scp 覆盖会留下**分散的** mtime。

### 2.5 通道本身

| 维度 | 实测 |
|---|---|
| 本机出口 IP | 物理网卡 以太网 2 = 192.168.102.222；126 auth.log **所有** publickey 登录来源均为该 IP（窗口内 98 次） |
| 密钥 | 单一 RSA 公钥指纹 SHA256:SNluMwP3KVGO9xZZ2tCSJKA2U+nvihCsTU1K8VyJXgA |
| 认证方式 | pubkey 为主；窗口内两次 password 登录（10-09 16:39:10、10-10 09:12:10，对应 pts 交互会话） |
| 失败/暴破 | btmp 自 10-08 08:45 起为空；auth.log 中 Failed 计数 0 |
| 传输工具面 | /usr/bin/scp、/usr/lib/openssh/sftp-server（sshd 已开 subsystem sftp）；MaxStartups 10:30:100 |
| 是否脚本化 | **否**——/root 下 13 个 .sh 对 bundle/fetch/checkout/docker save/ctr import/rsync 命中全为空；无 .git/hooks、无相关 cron/systemd timer、无 lsyncd 类守护 ⇒ 手工命令行 |
| 残留 | /tmp 无 *.bundle / *.tar.gz / *.patch / 无 ap-* 条目 ⇒ bundle 用完即删 |
| ClientAliveInterval | 0（无服务端心跳）——长任务仍需"落盘 + 轮询尾部"，勿依赖前台连接存活 |

### 2.6 为什么只能走 bundle

本机 HEAD 6cebaa5 相对 origin/main 为 **ahead 1**，且 `git branch -r --contains 6cebaa5` 为空 ⇒ 该提交**未推送**到 GitHub，也未推送到 company remote（ssh://git@code.mingyang100.com:30001/techng/aimode/agent-platform.git，内网解析 192.168.100.132、30001 TCP 可达）。而 126 的 remote **只有 origin=GitHub**、无 company。**远端没有这个对象，126 无法 fetch ⇒ bundle 是物理上唯一可行通道**（与"126 有外网、curl github 得 200"并列，说明瓶颈不在网络）。

### 2.7 构建与分发的防错设计

- build.sh：`git rev-parse HEAD` 与入参 expected-rev 不等即 exit 2；构建后从镜像内 /srv/agent-platform/GIT_REV 文件 + OCI label **双通道回读**，防"假同步"。
- distribute.sh：`docker save | gzip` → scp 到 125/241（WORKER_USER=root）→ `ctr --address /run/containerd-k8s/containerd.sock -n k8s.io images import` → crictl 核对；126 本机也导入一次。**这解释了 agent-platform:dev 为何同时存在于 moby 与 k8s.io 两侧且同 ID（f37bcdb1ed7a）。**

### 2.8 本机侧通道可达性判据（2026-10-10 实踩，写下来是为了下次别当成"126 宕机"）

本机与 `192.168.100.0/24` **不同网段**（本机在 192.168.102.0/24），去 126 靠内网隧道；隧道一断，症状与"126 挂了"完全一样，所以按下面这套读，别凭一条命令下结论：

| 读数 | 含义 |
|---|---|
| `ssh root@192.168.100.126 hostname` → `connect … port 22: Connection timed out` | 唯一有决定性的"通道不可用"信号（这才是排期前置，见 AGENTS.md 六条差异第 1 条相关纪律） |
| `ipconfig` 里 `OpenVPN TAP-Windows6` / `OpenVPN Data Channel Offload` = **Media disconnected** | 本机侧隧道未连 ⇒ 断点大概率在我这边 |
| `tracert -h 6 192.168.100.126`：hop1 = 192.168.102.1 通，hop2 起全 `Request timed out` | 报文出不了本机所在 LAN 的路由器，**没有进入 100 网段** |
| `ping 192.168.100.1` 有回复（TTL=255、<1ms）而 `.125/.126` 100% loss | **红鲱鱼**：ARP 表无该条目、本机也无 100.x 接口 ⇒ 应答者是 LAN 路由器的另一侧地址，不代表 100 网段可达 |
| `Test-NetConnection -Port 22` = False | 只在你已经知道其它读数时才有意义；单独一条 False 与单独一条 True 都不含信息 |

**严谨边界**：从本机**无法区分**"我的路由/隧道断了"与"126 或整个集群真的停了"——两者的报文表现相同。要判开必须换一条不依赖该隧道的观察面（另一台已在 100 网段的机器、或集群侧带外）。恢复隧道属改用户本机网络，**不自动执行，先征询**。


## 3. 宿主解释器与工具链（决定"能在 126 上怎么测"）

| 项 | 实测（e12 [9] / e13 [11]） | 影响 |
|---|---|---|
| 宿主 Python | /usr/bin/python3 = **3.10.12**（/usr/bin 下只有 python3、python3.10、python3-config） | 低于全仓 requires-python >= 3.11 |
| python3.11 | **不存在**（command -v python3.11 → PY311_ABSENT） | 无法在宿主直接跑项目测试 |
| uv | **不存在**（command -v uv → UV_ABSENT；全盘 find -maxdepth 5 未命中；/root/.local/bin 为空目录、/root/.local/share 只有 2022 年的 virtualenv；PATH 不含 .local/bin；/usr/local/bin 只有 csctl/docker-compose/sctl） | Makefile 的 `uv run ...` 会话在 126 上**完全不可执行** |
| .venv × **2**（不是三份） | /opt/agent-platform/.venv **6.4G**（`uv = 0.12.23`、`version_info = 3.11.16`、`home = /usr/local/bin`，建于 10-09 17:15）与 /opt/ap-iso/.venv 250M（`uv = 0.12.19`，09-28）；**knowledge-service/.venv 不存在** | 两者 bin/python 均为指向 **/usr/local/bin/python3** 的 broken symlink（宿主执行 rc=127） |
| 断链根因 | venv 是在 `python:3.11-slim` / `ap-test-base` 容器内创建并 bind-mount 回宿主目录的——容器内 /usr/local/bin/python3 才是 3.11，容器退出后宿主无此路径 | ⇒ venv 不是“坏了”，而是**只对容器内解释器有意义** |
| **复用点（提速关键）** | 主 venv 的 lib/python3.11/site-packages = **454 个包目录 / 6.4G**，torch、sentence_transformers、fastapi、deepagents、langgraph 均在位；基座镜像 ap-test-base:1（7fbe0ac7db9c）/ :2（39b7a078b171）/ python:3.11-slim（274d131132db）全部在位 | **以容器 bind 该目录可直接跑，无需重装 6.4G 依赖**（历史测试容器 ap-iso-test 形态即 `Image=python:3.11-slim` + `Binds=[/opt/ap-iso:/w]`） |
| 宿主可用解释器 | /usr/bin/python3 -B（脚本首行 `export PYTHONDONTWRITEBYTECODE=1`） | 只读脚本/单文件语法检查可跑；需 3.11 等价性时按 [testing-playbook.md](testing-playbook.md) §2 第 4 层跑容器（路径见上“复用点”行） |
| git | 2.34.1 | bundle 协议正常可用 |

## 4. 容器运行时形态与运行对象清单

### 4.1 双 containerd 实例并存（互不可见）

| 运行时 | 实测 | 承载什么 |
|---|---|---|
| docker (moby) | Client/Server **29.1.3**（build `29.1.3-0ubuntu3~22.04.2`，Ubuntu apt 包）/ API **1.52** / amd64；`/usr/bin/dockerd -H fd:// --containerd=/run/containerd/containerd.sock`；storage **overlay2**，data-root **/data/docker** | KS 知识服务栈 6 + jaeger + ap-iso-pg + rageval-eval |
| containerd（默认实例） | socket /run/containerd/containerd.sock（存在，ctime Jun 26 08:22）；`namespace ls` 只有 **moby** | docker 的容器运行时 |
| containerd-k8s | systemctl **active**；socket /run/containerd-k8s/containerd.sock（Sep 29 15:00）；namespace **k8s.io** | kubeadm 集群所用的**隔离第二实例**（防打断他人 docker 容器，动因见 [deploy/k8s/README.md](README.md) 踩坑表） |

两套镜像库互不可见、**节点间也不共享**（Deployment `imagePullPolicy: IfNotPresent` 且集群内无 registry）⇒ 上节点前必须 distribute.sh 逐台导入。

**镜像计数（口径务必分清，否则会得到 14/21/40 三个"都对"的数）**：

| 口径 | 值 |
|---|---|
| moby 侧 `docker images -q` | **14** |
| k8s.io 侧 `crictl images`（镜像名+tag 视图） | **21** |
| k8s.io 侧 `ctr -n k8s.io images ls -q`（**含 digest 引用条目**） | **40** |

k8s.io 库内同时存在 `docker.io/library/agent-platform:dev` 与历史 `sha256:ab5fe54b6860…`（09-30 那轮）及当前 `sha256:f37bcdb1ed7a…`——旧镜像引用未清。

### 4.2 docker compose 入口（**只有一个**）

| 事实 | 实测 |
|---|---|
| `docker compose` 子命令 | **不存在**：`docker: unknown command: docker compose`，`docker plugin ls` 为空表头（插件未装） |
| 可用入口 | /usr/local/bin/docker-compose，**静态 ELF 二进制**（76,584,394 B，mtime Nov 25 2025），`Docker Compose version v2.40.2` |
| /opt/miniconda3/bin/docker-compose | **不存在**（`ls: cannot access`）——此前记为"v1.25.5 python shim"有误，已在本基线更正 |

KS 栈归属（容器 label 实测）：`com.docker.compose.project=knowledge-service`、`working_dir=/opt/agent-platform/applications/knowledge-service`、`config_files=/opt/agent-platform/applications/knowledge-service/docker-compose.yml`、`version=2.40.2` ⇒ 仓库内对应 `applications/knowledge-service/docker-compose.yml`。KS 侧另有 /root/redeploy.sh、/root/deploy.sh、/root/fix_docker.sh 等**运维脚本**（不在仓库内，见 §5）。

### 4.3 运行对象（2026-10-10 实取）

k8s：三节点均 Ready（v1.31.14，CONTAINER-RUNTIME containerd://2.2.1），`kubectl get pods -A` **共 15 个全 Running**。业务 2 个在 **namespace `agent-platform`**（不是 default）：

| Pod | 节点 | 关键读数 |
|---|---|---|
| agent-platform-5cd47d7c9b-ldhqn | ambari02 | IP 10.244.1.13，AGE 9d，**RESTARTS 3**：第 3 次容器 started=2026-10-09T11:04:15Z（=19:04 +0800），lastReason=Error，lastFinished=2026-10-09T10:59:14Z（=18:59），**exitCode=137**；spec image = agent-platform:dev |
| postgres-6ff4688bb8-vn7v6 | ambari03 | IP 10.244.0.2，AGE 10d，RESTARTS 0（VERIFICATION.md 里的 `postgres-574484c8c6-j7f5m` 是旧 ReplicaSet 名，已失效） |

docker 侧 **running 9 个 / 含停止共 14 个**：

| 容器 | 镜像 | 状态 |
|---|---|---|
| knowledge-service-web | knowledge-service-web（本地构建） | Up 2 weeks (healthy)，StartedAt 2026-09-22T11:20:18Z |
| knowledge-service-milvus | milvusdb/milvus:**v2.5.10** | Up 20h (healthy)，**StartedAt 2026-10-09T09:38:26Z（=10-09 17:38 +0800）**，RestartPolicy=unless-stopped，OOMKilled=false，ExitCode=0 ⇒ 10-09 傍晚被重启过一次，非 OOM |
| knowledge-service-minio | minio/minio:RELEASE.2024-01-16T16-07-38Z | Up 2 weeks |
| knowledge-service-neo4j | neo4j:5 | Up 2 weeks (healthy) |
| knowledge-service-etcd | quay.io/coreos/etcd:**v3.5.18** | Up 2 weeks (healthy) |
| knowledge-service-mongo | **mongo:7** | Up 2 weeks (healthy) |
| jaeger | jaegertracing/all-in-one:**latest** | Up 10 days |
| ap-iso-pg | **pgvector/pgvector:pg16** | Up 12 days |
| rageval-eval | knowledge-service-web | Up 11 days；**Cmd=[sleep infinity]**、WorkingDir=/app、Started 2026-09-29T01:03:07Z（=09-29 09:03）；bind mount /opt/agent-platform/applications/knowledge-service/models → /app/models ⇒ 用 KS web 镜像起的**评测驻留容器**。创建形态经 e19 核实：带 compose labels（project=knowledge-service / service=web / version=2.40.2）但 `RestartPolicy=no` 且 Cmd 被覆盖 ⇒ 是 **`docker compose run` 派生的一次性容器**，不是纯 `docker run`，也不是 compose 正常服务。 |

Exited 未清理 5 个：ap-id2 / ap-iso-lean / ap-iso-test(1) / ap-iso-test2(137) 均为 **python:3.11-slim**（隔离实验用），bold_swirles 为 **d1egoprog/webvowl:1.1.7**(143)。

> ⚠️ **两处误述的更正（含归因）**：(1) 容器名前缀是 **knowledge-service-**，不是 `ks-`；(2) 前轮把 9 个 running 描述为"KS 6 + jaeger + ap-iso-pg + **已停的 webvowl**"——webvowl 处于 Exited 不计入 running，第 9 个 running 容器是 **rageval-eval**。

### 4.4 控制面健康（一次"看起来像故障"的复采样定性）

10-10 13:56 首次采样见 kube-controller-manager **35 次重启（9m22s ago）**、kube-scheduler **36 次（9m17s ago）**、kube-apiserver 5 次（20h ago）。**20 秒后二次采样：35 → 35、36 → 36 计数未增长**（仅"多久前"随时间推移），events 显示约 10 分钟前一轮：apiserver liveness `HTTP 500` + CM/Scheduler `dial tcp 127.0.0.1:10257/10259: connection refused` → 容器重建 → `became leader` 重新选主成功；CM 当前日志（35.log）为正常 informer sync。**结论：一次短暂抖动后已自愈，不是持续 crash-loop**（单节点演练集群累计 35/36 次属既有形态）。三节点 Ready，`uptime` = up 19 days（与 dockerd 启动 Mon Sep 21 12:29:48 一致），内存 total **15G** / available 12G（此前"31G"读数作废，以 `free -g` 实测为准）。

### 4.5 持久资产

| 项 | 实测 |
|---|---|
| docker volumes | **9 个** = 4 匿名 + 5 命名（knowledge-service_{etcd,milvus,minio,mongo,neo4j}_data）；`dangling=true` 为**空** |
| 卷大小（绝对 mountpoint du） | neo4j 517M、mongo 335M、milvus 221M、etcd 123M、minio 17M、匿名 901a256f 74M（→ap-iso-pg）、匿名 bec32eeffd 96K、另两匿名 4.0K |
| 卷变更元数据 | /data/docker/volumes/metadata.db mtime = 2026-10-09 17:11:57 ⇒ 10-10 全天**无任何 volume 增删**（用于把"计数变化"证伪为资产丢失，见 §6.3） |
| /data/docker 占用 | **47G**（overlay2 46G、volumes 1.3G、containers 114M、image 27M、buildkit 2.7M） |
| 磁盘 | /dev/vda2 **98G，used 62G，avail 32G（67%）**；/ 与 /data 同一文件系统（df 两次同设备）——**剩余 32G 是新增风险项**，再拉几轮镜像就要注意。可回收面见 §4.7。 |
| 模型缓存（两处，用途不同，**归属已闭合**） | /opt/ap-models **184M**，内含 hf-cache/，mtime **2026-10-09 18:39**，**无任何 docker 容器挂载**（挂载扫描为空）、pod volumes 为空、宿主 /root 脚本与 auth/history 无引用 ⇒ 判定为 **10-09 建 Linux 测试环境时下载 `BAAI/bge-small-zh-v1.5` 的 `HF_HOME` 缓存**，服务的是"容器内补跑测试"（用 `docker run -e HF_HOME=/opt/ap-models/hf-cache` 传入），**不是任何线上运行时的依赖**；KS 侧模型走 `{MODELS_DIR}` 推导的 /app/models，与此无关。/opt/agent-platform/applications/knowledge-service/models **4.3G**，是 KS 容器的 **bind mount**（不是 docker volume）。 |

> ⚠️ 模型缓存路径勘误的**归因更正**：本文初稿写的 /data/ap-models 不存在（`du: cannot access`），真实路径为 **/opt/ap-models**（内含 hf-cache/）。该错值**不是来自既有记录**——仓库长期记忆早就写对了 `/opt/ap-models/hf-cache`（含 BGE 模型资产与 HF_HOME 配方），错在本次续写会话引用了有损上下文摘要。⇒ 纪律：**数值要入库，来源必须是本轮 stdout，不能是摘要**。/data 下只有 docker、exhibition-skill-loader、k8s-demo、opt 四项；KS 的 4.3G 模型也不是 volume。

### 4.6 运行时配置来源与生效值（G1/G2/G3 验证结果）

三侧配置**互不相通**，且有一处会让"改了 ConfigMap 为什么不生效"必坑：

| 层 | 来源 | 实测生效值（白名单变量） |
|---|---|---|
| k8s agent-platform pod | Deployment env：`EMBEDDING_MODEL`←ConfigMap，`DATABASE_URL`←secret，**LLM_* 为字面值** | `EMBEDDING_MODEL=bge-small-zh`；`LLM_BASE_URL=https://api-inference.modelscope.cn/v1`；`LLM_MODEL`/`LLM_FALLBACK_MODEL=deepseek-ai/DeepSeek-V4.1-Flash`；`OTEL_ENDPOINT=http://192.168.100.126:4318/v1/traces`。**无 `EMBEDDING_MODE`** |
| ConfigMap `agent-platform-config` | 4 个键：`EMBEDDING_MODEL` / `LLM_BASE_URL` / `LLM_MODEL` / `LLM_FALLBACK_MODEL` | 只有 `EMBEDDING_MODEL=bge-small-zh` **被引用**；其余三个是**死键**（值停留在 `api.openai.com` / `gpt-4o-mini`） |
| Secret | `agent-platform-secrets`={DATABASE_URL, POSTGRES_PASSWORD}、`observability-keys`={LLM_API_KEY} | **无 EMBEDDING_API_KEY** |
| 宿主 .env | /opt/agent-platform/.env **不存在**；KS 侧 .env 存在 | KS：`EMBEDDING_MODE=api`、`RERANK_MODE=api`、`MODELS_DIR=./models` |
| KS 容器 | 由 .env / env_file 注入（**不烧进镜像**：e21 证三个 KS 镜像的 `Config.Env` 均无这些键） | web：`EMBEDDING_MODE=api`、`RERANK_MODE=api`；rageval-eval：**`EMBEDDING_MODE=local`** + `BGE_M3_PATH=/app/models/bge-m3` |

- ⇒ **平台侧确定在跑 MockEmbedder**（三处同时无 `EMBEDDING_MODE`/`EMBEDDING_API_KEY`，按仓库 `.env.example` 的 `auto` 语义即回退到内置确定性 mock）；且 pod 内 `importlib.util.find_spec` 实测 `torch/sentence_transformers/transformers/huggingface_hub` **全为 False**（python 3.11.16），故 `EMBEDDING_MODE=local` 在该镜像必报 ModuleNotFoundError。
- ⇒ **但这条限制不适用于 KS 镜像**：`knowledge-service-web` 内上述四件 + `FlagEmbedding` **全为 True**。即"local 不可用"是 **agent-platform:dev 镜像的裁剪问题**，不是环境缺失。
- ⇒ **同一个 KS 镜像跑着两种 mode**（web=api，rageval-eval=local）：前者是在线服务、后者是评测驻留容器，排查时不能拿一个的 env 推另一个。
- ⚠️ **死键陷阱，但成因已指认（不是第三方偷改）**：仓库 manifest（`deploy/k8s/20-agent-platform.yaml`）在 **HEAD 6cebaa5 与运行 rev 626ec17 两个版本里 LLM_* 都是 `configMapKeyRef`**，线上却是字面值 ⇒ **改 ConfigMap 的 LLM_* 不会生效**。e23[7] 进一步指出了**改写路径**：deployment 的 `kubectl.kubernetes.io/last-applied-configuration` 注解里 LLM_* **仍是 `configMapKeyRef`**，而 LIVE `.spec...containers[0].env` 是 `value:` ⇒ **不是 `kubectl apply` 干的**（apply 会把注解一起更新），是 `kubectl set env` / `edit` 类就地改写。而这两类命令**本仓库自己就入库记录着**——[deploy/k8s/VERIFICATION.md](../../deploy/k8s/VERIFICATION.md) §C 与 [deploy/k8s/README.md](../../deploy/k8s/README.md) 的"OTel env（一次性，已现场生效）"段明写了 `kubectl set env deploy/agent-platform …` 以及**同样的** `LLM_BASE_URL=https://api-inference.modelscope.cn/v1` / `LLM_MODEL=deepseek-ai/DeepSeek-V4.1-Flash`。⇒ **重定性：本项目部署演练时"有意的一次性覆盖 + 忘记回写 manifest"**。（严谨边界：该段**未逐字写出设置 LLM_* 的那条命令本体**，只写了同形的 `kubectl set env … OTEL_*` 与同样的 LLM 取值；故"LLM_* 具体是哪一条命令写进去"仍是**推断**，但"它是就地 set-env 类改写而非 apply"这一条是注解对比直接证实的。）
- `deployment.kubernetes.io/revision=9` ⇒ 该对象被变更过 **9 轮**（每次 `set env` 滚一轮），与"CM 里的值一直停在旧 openai 值"互相印证。
- 仍然**硬指不出来**的只有"敲那条命令的会话本身"：`/root/.bash_history`（mtime 09-30 10:45）里 `kubectl apply|patch|edit|set|replace|delete|scale` **0 命中**，`/etc/kubernetes/manifests/kube-apiserver.yaml`（121 行）**无 `--audit-log-path`** ⇒ 服务端审计未开，主体与时刻无从回查。最可能是**非交互 `ssh 126 "kubectl …"`**（bash_history 不记非交互调用）——此为**推断**，已如此标注。
- `managedFields` 为空（仅 `creationTimestamp=2026-09-29T07:26:38Z` = 09-29 15:26 +0800），故不能用 field-manager 判来源；**判来源靠 last-applied 与 LIVE 的差**。

### 4.7 两条故障因果链与可回收面（G5/G6/G8 验证结果）

**链一：宿主磁盘 IO → etcd 超时 → milvus 自退（非人为）**

- milvus `RestartCount=15`，而同一 compose 栈的 web/minio/neo4j/etcd/mongo + jaeger + ap-iso-pg **全部 rc=0** ⇒ 不是 `docker compose restart` / `service docker restart` 这类栈级操作。
- 停机前日志（e19，均为 UTC）：`09:37:45`→`09:38:13` 连续 `failed to update tso … etcdserver: request timed out`（每 7s）→ `09:38:18` 七个角色全部 `session key is deleted, exit...` → `09:38:19.590` `fail to retry keepAliveOnce … requested lease not found` + `Query Node disconnected from etcd, process will exit`。
- 同窗口 etcd 日志（e21）：`slow fdatasync` took=**3.71s**/2.03s/1.16s（期望 1s）、`waiting for ReadIndex response took too long`、`apply request took too long` 1.17s（期望 100ms）；慢日志计数 10-09 17:30–17:40 窗口 **114 条**，10-08 08:44–09:00 窗口 **882 条**。
- milvus 被拉起的 16 次时刻（journald `Deactivated`）：Sep 29 17:32；Sep 30 10:31/20:08/20:12/20:13；**Oct 08 08:45–08:59 连续 8 次**；Oct 09 08:17、17:38——与 etcd 慢日志峰完全咬合。
- ⇒ **结论：`ExitCode=0` + `OOMKilled=false` 不等于人为 `docker stop`**；这里是应用检测到 etcd lease 丢失后的**自主优雅退出**，根因在**宿主磁盘 fdatasync 慢**（/data 与 / 同一 vda2、已用 67%）。业务表现 = 知识检索链路会随磁盘压力周期性掉线（与 §4.4 控制面抖动不同时段，不相干）。
- ⇒ **再上游（e23 补验，G5 的"etcd 为何慢"已闭合到可行动作）**：
  - **基线条件 = 介质本身**：`lsblk -d` 全盘只有一块 `vda` **100G、ROTA=1**，`/sys/block/vda/queue/rotational = 1`（virtio 盘在内核侧被当**旋转介质**对待，队列按慢盘策略合并）；`dmesg -T` **无** `blocked for more than` / `I/O error` / `EXT4-fs error` ⇒ 不是设备故障或文件系统损坏，就是**慢**。
  - **压力是常态、不是事件**：`/proc/pressure/io` 在 e23 执行时 `some avg10=46.01 avg60=12.54 avg300=7.20 total=23330950931`（累计 ≈6.5h IO stall）、`vmstat 1 2` 第二行 **wa=25**；`slow fdatasync` 自 09-20 起共 **953 条且一天不落**（09-22 62 / 09-23 52 / 09-24 43 / 09-28 75 / 09-29 146 / **09-30 305** / 10-08 156 / 10-09 77 / 10-10 37），最近两条的时刻为 `06:51:58Z`、`06:53:50Z`，而 e23 自打的宿主时刻为 `14:53:49 +0800`（= `06:53:49Z`）⇒ 慢日志是**执行当下**发生、非历史回查，因此**按"某次故障"查是查不出来的，要按长期容量/调度问题治**。
  - **放大器 = Ubuntu 默认定时器**：`systemctl list-timers --all` 显示 `apt-daily` / `apt-daily-upgrade` / `dpkg-db-backup` / `motd-news` / `ua-timer` / `logrotate` / `man-db` / `fwupd-refresh` 的 LAST **全为 10-10 08:23:56**（开机后统一补偿），`e2scrub_all.timer` 的 LAST = **10-08 08:44:30**；而 journald 同一分钟里正是 `08:44:30 Starting Daily apt download activities / Daily dpkg database backup service / Update APT News` + `08:49:22 Starting Daily apt upgrade and clean activities`（apt-daily 单项 `Consumed 34.010s CPU`），与 **milvus 10-08 08:45–08:59 连续 8 次重启**逐条吻合（该窗口里反复 `Deactivated` 的 `docker-f558459e9d83….scope` 已单独回查确认就是 `/knowledge-service-milvus`，`RestartCount=15`、最后 `StartedAt=2026-10-09T09:38:26Z` = 17:38:26 +0800，与 `Up 21 hours` 互相咬合 ⇒ 不是拿无名 scope 臆断归属）。ext4 journal 的 e2scrub 打在已用 67% 的 /dev/vda2 上尤其重。
  - **不是限流**：`docker inspect` 实测 `knowledge-service-etcd` **`blkioWeight=0`、`BlkioDeviceReadBps=[]`、`Memory=0`（无限制）**，`knowledge-service-milvus` 仅 `Memory=4G/Swap=8G`；宿主 15G 内存 available 12G、loadavg 0.98 ⇒ 排除内存与 cgroup 限流两个候选，etcd 与所有维护任务**平权抢 IO**。
  - **反例校核（防过度归因）**：10-09 17:30–17:40 窗口内**没有** timer 活动（只有常规容器 scope 起停），该轮 milvus 照样退出 ⇒ 慢 fdatasync **不需要外部触发者**，介质长尾本身就够；定时器只是把它推过阈值。同窗口还看到 `kubelet … Server rejected event … Timeout: request did not complete within requested timeout`（指向同一 etcd /apiserver 超时面）。
  - ⇒ 处置候选（**均属待拍板，本轮一项未动**）：错峰或关掉 `apt-daily*` / `apt-daily-upgrade` / `e2scrub_all` 定时器；给 etcd 独占数据盘或提高其 IO 权重；把 PSI `io avg10` 纳入监控做阈值告警；先落 §4.7 的 ≈13.75GB 回收以降低 used%（67%→~53%）。

**链二：pod 那次 137 = 外部依赖断连 + 优雅关闭超时被 SIGKILL（非应用崩溃）**

- `kubectl logs --previous`（e17）尾部：`/health` 连续 200 → `10:58:29Z` OTLP export timeout → `10:58:43Z` **`failed to resolve host 'postgres'` (Temporary failure in name resolution)** → `INFO: Shutting down` → `Waiting for background tasks to complete` → `10:59:07Z` **`No route to host` 到 192.168.100.126:4318** → `10:59:13Z` failed。
- ⇒ 137 = 128+9（SIGKILL）：进程在等后台任务收尾时被 kubelet 的 terminationGracePeriod 到点杀掉。**上游是集群网络/DNS 扰动**（postgres Service 解不了 + 126 的 OTLP 端口不可达），不是代码异常。
- pod 在 **ambari02**，126 上的 dmesg/OOM 记录与该 pod 无关（不要拿 control-plane 节点的 OOM 日志归因 worker 上的 pod）。

**可回收面（G8 的决策依据，本轮只列不删）**

| 项 | 实测 | 判定 |
|---|---|---|
| `docker system df` | Images 22/10 active、26.81GB、**RECLAIMABLE 13GB (48%)**；Containers 1.79GB、reclaimable 1.386GB (77%)；Volumes 9/9 active、0；Build Cache 29、20.66GB、reclaimable 仅 3.057MB | — |
| 两个 dangling KS 镜像 | `2e4603edf525` unique **6.879GB**、`77163877e720` unique **6.879GB** ⇒ 13GB 可回收基本全在这 | Created 分别为 **09-22 18:02:10 / 18:16:42 +0800**，现役 `8fe43ec2877f` = **18:32:59** ⇒ 三个是**同一晚相隔 30 分钟内的三连构建**，不是旧版本代码 ⇒ 删掉不损失回滚能力 |
| 五个 ~390MB 的 `<none>` agent-platform 镜像 | unique **0B**（层全共享） | 删了不省空间 |
| Build Cache 20.66GB | 单项 `8kzpciilrfz6` regular **6.88GB** 是主体，余下多为 0B/KB；`/data/docker/buildkit` 仅 **2.7M** ⇒ 实体在 overlay2 内不可分离；df 判"不可回收"是因为被现有镜像引用 | 低收益高代价，不建议动 |
| ⇒ 实际可回收 | **≈ 13.75GB**（两个 dangling KS 镜像 13.758GB + 5 个已停容器 1.386GB 中的独占部分）→ avail 32G 可回到 ~45G | 与 §4.7 链一的磁盘 IO 抖动直接相关，清理不只是容量问题 |

> ⚠️ 工具子命令缺失（同一根因：apt 版 docker CLI 只带最小子命令集）：`docker compose`、`docker builder du`、`docker buildx` **均不存在**；看构建缓存只能用 `docker system df -v` 的 Build cache 段。另 etcd 官方镜像**无 `sh`**，`docker exec knowledge-service-etcd sh -c …` 会直接 `executable file not found`。

### 4.8 2026-10-12 复测读数（模型可用了、通道回来了，两条旧结论要改口径）

| # | 读数 | 对旧结论的修正 |
|---|---|---|
| 1 | 用 Pod 内既有密钥真打 `POST /v1/chat/completions` → **HTTP 200**，`content` 有正常中文回答，`usage` 有 token 计量 | 2026-10-10 的 Gate 1 失败（403 要求邮箱验证）已解除 |
| 2 | 响应 `message` 的键是 `['content','function_calls','reasoning_content','role','tool_calls']`，其中 **`reasoning_content` 长 219 字、`content` 长 52 字** ⇒ 这是推理型模型。**小预算下 `content` 会是空串**：`max_tokens=16` 时 HTTP 200、`completion_tokens=16`、`content=''`（16 个 token 全被推理吃掉） | 平台侧**没有**设 `max_tokens`（`agent/llm.py` 只设 `timeout`），所以链路本身不会撞上；但任何人给它加 token 上限都会静默得到空回答 ⇒ 记进运维手册 |
| 3 | **exitCode 137 会复发**：Pod `Restart Count=1`，`Last State: Terminated 18:29:21 +0800`，`--previous` 尾部又是同一序列 —— `Failed to export spans batch due to timeout` → `failed to resolve host 'postgres'` → `Waiting for background tasks to complete` → 再次 export timeout | §4.7/G6 那条"已定性"从**一次性现象**升级为**周期性复发**（诱因是集群 DNS/网络抖动）。直接支撑 `plan-tracing-shutdown-flush-timeout-2026-10-10.md` 的选项 A：上界必须由代码给 |
| 4 | 权重缓存分布：ambari03(126) `/opt/ap-models` = 184M 在位；**ambari02(125) 与 ambari01(241) 原为 CACHE_MISSING**，本轮已铺（同 184M、`chmod a+rX`） | 印证"本地语义模型的前提是缓存存在于 Pod 实际落到的节点"——Pod 当时在 ambari01 |
| 5 | 三节点 `allocatable.memory` 均约 16Gi / 8 CPU ⇒ 新 `requests 1Gi / limits 2Gi` 放得下 | 消掉"上调到 2Gi 可能调度不开"的疑虑 |
| 6 | `observability-keys` 现有两键：`LLM_API_KEY`(len=39) 与新增 `API_KEY`(len=32)；用 `kubectl patch --type merge --patch-file /dev/stdin` 补的单个键，**merge 后 LLM_API_KEY 完好** | 实证 `00-config.yaml` 里那条警告：整对象 apply 是覆盖，补键必须走 merge patch / 单键 apply |
| 7 | `semantic_cache` 已有 2 行（v11 之前写的，`tenant_id` 由默认值补成 `''`）、`chunks=0`、`memories=0` | 资料尚未入库（底线 4 未达），缓存里是历史试跑留下的行 |

**取证时的密钥卫生（本轮我自己踩了两次）**：`kubectl get secret -o custom-columns=KEYS:.data` 与
`-o jsonpath='{.data}' | tr ... | sed 's/=.*//'` 都会把 **base64 值整片打到终端**（后者因 JSON 形制没被剥掉），
等于把密钥写进会话记录。只取键名的正确姿势：

```bash
kubectl -n agent-platform get secret observability-keys -o json | python3 -c 'import json,sys; print(sorted(json.load(sys.stdin)["data"]))'
# 需要确认值在不在位时只量长度，不回显：
kubectl -n agent-platform get secret observability-keys -o jsonpath='{.data.LLM_API_KEY}' | base64 -d | wc -c
```

处置：那次外泄的 `LLM_API_KEY` 建议按正常密钥轮换流程作废；本轮生成的入站 `API_KEY` 第一把已作废并重生成（32 字节，未回显）。

### 4.9 2026-10-12 上线生效后的环境读数（新清单第一次真跑）

线上 Pod 模板第一次按清单生效（`GIT_REV=db1a8b8`，Pod 内回读）。完整业务反证在
`docs/operations/evidence/2026-10-12-release/readings.md`，这里只留**环境侧**事实：

| # | 读数 | 这条改变了什么判断 |
|---|---|---|
| 1 | Pod 落点在两次重启间移动：`ambari01` → `ambari02` → `ambari01` | "**三节点都要有权重缓存 + 都要导入镜像**"是承载性前提，不是保险。少铺一个节点，`hostPath type: Directory` 会让 Pod 在该节点 Pending（这是好事：失败在调度期而不是首次推理） |
| 2 | 本轮删除 Pod 后 Warning 级 `Killing/OOMKilling/Evicted` 事件 **0 条**，自愈 15s；`otel_status=ACTIVE` 且 Jaeger 查到 8 span | §4.8 第 3 条的 137 复发诱因（OTLP 不可达 + DNS 断连拖住优雅关闭）在"Jaeger 在位 + 宽限期 60s"下**本轮未复现**。⚠️ 这是**一次观测**，不是"已修"——真修是给出网时的 flush 上界（`plan-tracing-shutdown-flush-timeout-2026-10-10.md`，待拍板）。旧 Pod 的 `lastState` 没抓到（对象随删除消失），下次须在删除前抓 |
| 3 | `allocatable.memory = 16232772Ki`（**大写 K**），三节点约 15.9Gi / 8 CPU | 解析 k8s 资源量时 `[kMGT]` 字符类漏 `K` 会直接抛错；我本轮的容量预检就这么失败过一次。`Ki` 与 `k` 是两个不同单位（1024 vs 1000） |
| 4 | LocalEmbedder 常驻、无并发时 `memory.current=442Mi`、`kubectl top=441Mi`、`pid1 VmRSS=553Mi`；`cgroup memory.max=2147483648` | `requests 1Gi / limits 2Gi` 有实测依据（此前只有 CUDA 轮经验值），且限额真落到 cgroup |
| 5 | `kubectl apply -f 20-agent-platform.yaml` 第一次被整份拒绝：`env[N].valueFrom: Invalid value: "": may not be specified when value is not empty` | 线上字面值 + 清单 `valueFrom` 的三方合并冲突。**拒得完整 ⇒ 无半生效、无中断**。解法（整 Pod 模板原子 replace）与前置闸见 `deploy/k8s/README.md` §6.1 与运维手册 §3.1 |
| 6 | `kubectl apply --dry-run=client -o json` 对同一份清单返回 **10 项 env**（线上现状），`kubectl create --dry-run=client -o json` 返回 **21 项**（清单真值） | **`apply --dry-run` 不能当"期望值"来源**：它会与线上对象合并。预检脚本一旦拿它派生期望态，就会自己骗过自己 |
| 7 | 12:10 收盘库里真值：`chunks` **93 行 / 3 文档**（35+30+28，`vector_dims=512`，退化向量 0 行）、`semantic_cache` 只留最新问答、`memories` 为当日测试产物 | §4.8 第 7 条那条 `chunks=0` 到此翻页：**pgvector 表真的有内容、真的被查得到**。问答链路用的就是这张表，不是 Milvus（见本节第 4 条与手册 §5） |
| 8 | 磁盘从 `73% used（68G/26G avail）` 回到 `72%（67G/27G）` | 三个节点上本轮共产出的 451M×3 镜像 tarball 与 `/tmp` 自建脚本已清；改动前的 Deployment 对象**没有**当垃圾删，移到 `/root/ap-release-backup-20261012/`（回滚位不是垃圾） |

### 4.10 2026-10-13 业务语料入库后的读数（今天没发新 rev，只动数据）

| # | 实测 | 口径影响 |
|---|---|---|
| 1 | Pod 内 `GIT_REV=db1a8b8477539af2af00e104e36317c159f19c39`，与 10-12 上线对象同一枚；今天**未** build/distribute/apply | "同步了≠上线了"反过来也成立：**没上线就别写上线读数**。今天所有读数都属于 `db1a8b8` |
| 2 | `chunks` **303 行 / 7 文档**（业务 4 份 = 210 块，ADR 3 份 = 93 块），`vector_dims` 单一 `512`，范数 min=max=`1.0000`，近零向量 0 | 语料换成真实业务文档；维度没混 ⇒ 索引不会静默降级 |
| 3 | `count(DISTINCT embedding::text)` = **301/303**，差值定性为 3 块内容都是 `---`（markdown 分隔线）共享 1 个向量 | **不是退化向量复现，是切块器把分隔线与页码行留成正文块**（另有 1 块仅 19 字符的"页码 + 目录行"）。只定性，未修 |
| 4 | 含 `[已脱敏` 标记的块 **13** | 进库的确实是脱敏版，不是只改了本地原件 |
| 5 | `/import` 单份墙钟：19KB→8.5s、18KB→6.8s、14KB→5.9s、**93KB→31.8s（133 块）** | 冷权重已由 lifespan 预热摊掉；入库耗时主要是 LocalEmbedder 逐块编码，**没有并发**（见手册 §6.2 未测项） |
| 6 | **`/health` 的 `llm=true` 与"路由可用"无关**：`router.py:87` 的 `with_structured_output` 被上游拒 `<400> InternalError.Algo.InvalidParameter: This response_format type is unavailable now`，我发起的 16 次 `/query` 次次回退词表；单发因果核对告警计数 16→17（增量 1） | 本部署**没有 LLM 路由**，`route_hints.json` 那张词表就是主路由器 ⇒ 关键词闸门从"兜底路径缺陷"升级为"主路径行为"，见 `plan-router-keyword-gate-hides-corpus-2026-10-12.md` §7 |
| 7 | 回放源是 **4 类不是 2 类**：`semantic_cache` / `memories` / `episodic_memories`+`procedural_memories`（今日恒 0）/ **LangGraph `checkpoints`+`checkpoint_blobs`+`checkpoint_writes`**（今日 1 个 thread `tenant-default`、33 个 blob） | 消融/抽验只清前两类会得出假结论：`evidence count=0` 却答对，靠的是 checkpoint 里的会话历史。**清它 = 清空控制台历史面板** |
| 8 | `data/corpus/` 已入 `.gitignore`（规则 `data/corpus/`）；126 侧副本在 `/tmp/corpus/`，tar 在 `/tmp/corpus-20261013.tgz` | 脱敏只覆盖手机/邮箱，正文仍是未公开业务口径 ⇒ 整目录不入库，而不是只挡 `.pdf` 原件 |
| 9 | 宿主侧跑 `/query` 探针：密钥经 **env** 传入（`env AP_KEY="$KEY" python3 -`），**不走 argv** | `ps aux` 对全主机可见 argv；env 只 root/属主可读。这是今天定下的口径 |
| 10 | psycopg 默认不开 autocommit：一条语句失败后同一连接内后续读数全变 `InFailedSqlTransaction`；本库 `l2_norm(vector)` 有重名歧义，改用 `sqrt(-(embedding <#> embedding))`（pgvector 的 `<#>` 是**负**内积） | "5 项读数同时报错"看着像数据坏了，其实是读法问题 ⇒ 逐条 autocommit 才算独立读数 |
| 11 | **AGENTS.md 第 5 条已过时并在今日修正**：deployment 的 `LLM_BASE_URL/LLM_MODEL/LLM_FALLBACK_MODEL` 现为 `configMapKeyRef`（不是字面值），且 **CM 值 == Pod 内生效值**（实测三行逐字相等）；`EMBEDDING_MODE=local` 也已显式注入 | 10-12 那次"整 Pod 模板原子替换"顺带把 10-09 之前 `kubectl set env` 留下的死键**修好了**。⇒ 现在改 CM + 滚动**会**生效；"CM 里这三个是死键"这句以后会误导人，已按实测改写。判 literal/ref 的口径：`last-applied-configuration` 注解 vs LIVE，期望态一律用 `kubectl create --dry-run=client -o json` 取 |
| 12 | 本机**没有** `.env`（只有 `.env.example`，`.gitignore:2` 忽略 `.env`）；`config.py:13` 的 `env_file=".env"` 说明它就是设计好的本地注入口 | 三家 provider 的**密钥不落任何文件**（任务书硬口径）。现网唯一在用的那把在 `Secret observability-keys/LLM_API_KEY`；本轮需求方在对话里贴过的两把（硅基流动 / OpenRouter）**除对话外不存在于任何地方**，故已建议轮换 |
| 13 | 2026-10-13 扫 `/tmp` 明文密钥残留：91 个条目中 **1 个命中** `/tmp/_inject_llm.sh`（`-rw-r--r-- root:root`，mtime **2026-09-29 17:24**，内含 `kubectl create secret … --from-literal=<值>` 两行） ⇒ 已 `shred -u`，复扫 0 命中 | 那是"密钥经 env 不走 argv"这条口径**定下之前**我自己留下的取证脚本。两条要点：① **`--from-literal` 会把明文留在脚本文件里**，`/tmp` + `644` 在同主机上等于对全部用户公开 ⇒ 建 Secret 只能走 `--from-file`（stdin）或 `env` 注入，不得把值写进任何落盘命令；② 该 LLM 键已在世界可读位置存在约 **2 周** ⇒ **建议轮换**（决定权与执行都不在我） |

## 5. 三份代码副本与运行 rev（最易踩的坑）



| 位置 | rev | 角色 | 工作区 |
|---|---|---|---|
| 宿主 /opt/agent-platform | **6cebaa5**（detached HEAD） | 同步落点，**不是运行源** | **干净**（dirty=0，三次复测一致） |
| 镜像 agent-platform:dev 内 /srv/agent-platform | **626ec1798354…** | **线上运行源**（e13 进 pod `cat GIT_REV` 实取） | — |
| /opt/ap-iso（worktree of 主仓） | **d96799f** | 隔离实验区，**非运行源** | 5 项改动（M scripts/audit_tenant_access.py、M uv.lock、?? audit_err.txt、?? audit_report.md、?? audit_stdout.json） |
| knowledge-service-web:latest 镜像内 /app | **不可考（镜像无 GIT_REV）** | **KS 在线服务的运行源** | 镜像 Created 09-22 18:32:59 +0800；236 个 .py 中 8 个 mtime 晚于构建（事后热改），详见 §5 末尾 |

- **宿主 HEAD 比运行 rev 领先 `git rev-list --count` = 548 个提交**（前轮"新 4 个提交"的说法作废）。改完代码若忘记重走 build/distribute，126 上"看到的代码"与"跑着的代码"必然不一致，且差距可以极大。
- d96799f 与 626ec17 均为 HEAD 的**祖先**（`git merge-base --is-ancestor` 双重 YES）⇒ 不构成额外分支来源，只是落后快照。
- **线上代码漂移逐项定量（G4，"17 项"读数作废）**：以 KS 容器 `/app` 为对象、与宿主 checkout @6cebaa5 做逐文件 md5 比对（e18）：容器内 **236 个 .py**（已排除 .venv/__pycache__/site-packages/models/data/output/logs）中 **SAME=162 / DIFF=74 / 仓库无对应文件=0**（⇒ 没有"只存在于线上、未入库的野文件"）。
  - ⚠️ 但这 74 项**不能直接当"热改"**：KS 镜像建于 **09-22 18:32**（无 `GIT_REV` 标记，镜像内 `/app/pyproject.toml` mtime 09-22 09:28），而宿主是 10-09 的 6cebaa5，两者相隔 **548 个提交** ⇒ 74 = 版本差 + 真热改 的混合。
  - ✅ 用 mtime 把两者分开（e22，以镜像 Created 为阈）：**228 个文件 mtime ≤ 构建时刻，8 个晚于构建 ⇒ 这 8 个才是确证的事后热改**：
    - `eval/ablation.py`、`eval/seed_synthetic_corpus.py`、`eval/run_route_ablation.py`（容器内 mtime 09-28）
    - `knowledge_service/import_process/agent/nodes/node_import_milvus.py`、`…/node_bge_embedding.py`、`import_process/agent/state.py`、`knowledge_service/api/import_router.py`、`query_process/agent/nodes/node_search_embedding.py`（容器内 mtime 09-22，最后一个与 web 容器启动时刻仅差 3 秒 ⇒ 典型的"构建完就 `docker cp` 覆盖再重启"）
  - ⇒ 处置范围从"74 项待定"缩小到 **这 8 个文件的逐个 diff**；属"先方案后代码"范围，禁止直接动容器内文件。
  - ⚠️ 成因通道仍在：KS 侧 /root/redeploy.sh 一类 `docker cp` + `docker exec sed -i` 直接覆盖容器内文件，**不经过 git**。
  - ⚠️ **三源不一致，无处是权威**（补测，命令见 §6.9）：`eval/ablation.py` 容器=`271b715b` / 仓库@6cebaa5=`57f93721`（12757B）/ /tmp 副本=`d99e533b`（10942B，mtime 09-29 09:10），**三份 md5 与大小互不相同**；`run_route_ablation.py`、`seed_synthetic_corpus.py` 同样三处各异。且容器内 mtime（09-28 17:53 +0800）**早于** /tmp 副本（09-29）⇒ **/tmp 里那份不是热改的来源**，而是同批脚本的更晚编辑。结论：这些评测脚本在容器/宿主/临时目录三处各留一个版本，**没有任何一处是权威**，回填前必须先定基线。
  - ⚠️ 另注意：宿主 `eval/ablation.py` 的 mtime 是 **09-30 09:47** 而不是 10-09 17:11（checkout 时刻）——`git checkout` 只重写两 rev 间有差异的文件，内容未变的文件**保留旧 mtime**。⇒ 判"宿主工作区是否被手改"只能看 `git status --porcelain`（=0），**不能拿 mtime 不齐当证据**。
- ✅ **语义 diff 已取（e24/e25，全程只读），结论与本节原先的猜测相反**。判据换了两条硬工具就够：`docker diff` 给"容器可写层 vs 镜像层"的**权威热改清单**（不需靠 mtime 推断），`git hash-object`（不带 `-w`，不写对象库）+ `git cat-file -e` + `git log --find-object` 判"容器这份字节形态是否曾入库"。8 个文件分两类，**没有一类需要手工救回代码**：
  - **A 类 5 个 = 容器内容就是某个已入库 commit 的字节**（blob OID 在对象库命中）：`node_import_milvus.py`、`node_bge_embedding.py`、`state.py` **与 HEAD 完全相同**（`vs HEAD hunks=0`）；它们容器内 mtime 为 09-22 **19:12–19:20 +0800**，而 `34f68ed`（"fix(ks): 通用知识库导入链路修复——enable_item_name_recognition=false 全链路打通"）提交在 **19:25:40** ⇒ 时间线闭合：**先 `docker cp` 现场验证、5 分钟后提交入库**；且 `web_started=09-22T11:20:18Z` 与 `node_import_milvus.py` 的 mtime `11:20:15Z` 只差 3 秒、`RestartCount=0` ⇒ cp 完立即重启、此后未再动。`import_router.py` 容器版命中 `34f68ed`、`node_search_embedding.py` 命中 `04b08cf`（D2 阈值外部化）⇒ 只是镜像比仓库旧。
  - **B 类 3 个 eval 脚本 = 字节形态从未入库的草稿，但知识没丢**：容器版 blob 不在对象库（`cat-file` 报 `could not get object info`），而 HEAD 版**更大且含全部关键概念**——`ROUTE_CONFIGS`/`ROUTE_ORDER`/`LEXICAL_WEIGHT_SCAN`（五档权重 `1.0/0.0`、`0.8/0.2`、`0.5/0.5`、`0.2/0.8`、`0.0/1.0` 与容器草稿**逐字相同**）、`EVAL_COLLECTION_NAME = "eval_rag_routes"` 及其"避免 `node_import_milvus` 同 item_name 幂等清理误删真实语料"的理由注释、`kg::{item}::{name}` 命名空间告警全在；容器独有的那 8 行（内联拼 `sources` 列表）在 HEAD 里被 `active_route_channels()` 取代。三处版本恰好构成演进链：**容器 09-28 草稿 → `/tmp` 09-29 中间稿 → HEAD 正式形态**（后者还多出 `source_adapter.py`、`analysis.py` 两个模块与配对 bootstrap CI）。
  - ⚠️ **⇒ G4 的真实债务不是"热改未回写"，而是"线上缺 3 项已入库修复"**：容器版 `import_router.py` 相对 HEAD 少 `resolve_server_tenant`（ADR-0006 T11 租户服务端注入，**安全相关**）、少 `asyncio.to_thread`（整文件落盘阻塞事件循环，大文件并发上传会饿死其它请求）、少 MinIO retry + fail-fast（P2-7，失败即拒收避免孤儿数据）。处置动作因此从"逐个 diff 决定回写"改为**"重新构建并分发 KS 镜像"**——一次解决，无需手工救代码。
  - ✅ `docker diff` 与 mtime 法**双向吻合**（可写层 9 个 .py = 8 个代码文件 + `/tmp/_dl_bgem3.py`），删除项 **D=0**；可写层总量仅 **444K**（`/app` 304K + `/tmp` 108K + `/root` 28K），`/root/.cache/modelscope` 在可写层只占 **8K**（全是 `.lock`）⇒ **模型缓存不在容器可写层，删容器不丢模型**；`rageval-eval`/`agentscope` 两容器 `py_changes=0` ⇒ 热改只发生在 web 一个容器。`/tmp/_dl_bgem3.py` 是 3 行 `snapshot_download("BAAI/bge-m3", local_dir="/app/models/bge-m3")`，未入库、无救回价值，但它是 `local` 模式下模型落点的直接证据。
  - ⚠️ **一处续作快照错值已纠**：上下文摘要记 `run_route_ablation.py` 容器 md5 = `a9dc7335`，e24/e25 用两种测法（容器内 `md5sum` 与 `cat` 管道）实测均为 `9f1e1c36e3aa…`，且该文件 ctime 停在 09-28 10:18 ⇒ **不存在"有人正在改容器"**，纯属摘要读数失真。本文档正文原先未写该值，未被污染（再次印证：只有本轮 stdout 算数）。
- **可观测性缺口（建议项，非现状描述）**：`agent-platform:dev` 镜像有 `GIT_REV`，**KS 镜像没有** ⇒ "线上代码属于哪个 rev"对 KS 侧根本不可答，这也是"漂移到底算多少项"一值多错的根因。建议 KS 构建同样烧入 rev 标记。

## 6. 可复核的取证命令（全部只读，可原地复现）

### 6.1 判定同步方式

```bash
cd /opt/agent-platform
cat .git/FETCH_HEAD                              # 来源若是本地路径 => bundle；若是 URL => fetch/pull
git config --get core.bare
git config --get-regexp '^(receive|remote|branch)\.'
grep -ac 'by push' .git/logs/HEAD                # 0 => 从未被推送过
cat .git/logs/HEAD                               # 全部动作词 + epoch（比 reflog --date=iso 精确）
ls -la --time-style=long-iso .git/objects/pack/*.pack   # 每次同步落一个 pack
ls -la .git/hooks | grep -v '\.sample$'          # 有无 post-receive（推送即部署）
git worktree list
```

### 6.2 判定宿主能否跑项目测试

```bash
ls -l /usr/bin/python3*; /usr/bin/python3 -V
command -v python3.11 uv
find /opt -maxdepth 4 -name pyvenv.cfg -not -path '*/node_modules/*' -exec sh -c 'echo "CFG: $1"; grep -E "uv|version_info" "$1"' _ {} \;
ls -la /root/.local/share/uv 2>&1 || echo UV_STORE_ABSENT
```

### 6.3 判定"计数变化"是否等于资产丢失

不要只比两轮的 `ls | wc -l`（find 配 `-printf '%f\n'` 会把根目录自身也输出一行，易造成 ±1 假象）。正确做法：

```bash
docker volume ls -q | wc -l
docker volume ls -f dangling=true                       # 空 => 无孤儿卷，非"丢了"
stat -c '%n mtime=%y' /data/docker/volumes /data/docker/volumes/metadata.db   # 变更元数据时间
docker events --since <上轮时间> --filter type=volume    # 有 create/destroy 才算真变更
```

### 6.4 判定运行 rev 与线上代码一致性

```bash
git -C /opt/agent-platform rev-parse HEAD
git -C /opt/agent-platform rev-list --count <运行rev>..HEAD    # 领先多少提交
kubectl get pods -A --no-headers | awk '$2 ~ /agent-platform/ {print $1" "$2}'   # NS + POD（勿假设 default）
kubectl exec -n <NS> <POD> -- cat /srv/agent-platform/GIT_REV # 运行源才是事实（只读取一个文件）
```

### 6.5 判定同步通道与登录来源

```bash
last -F | head -12                       # 来源 IP 列
ls -la /var/log/auth.log*                # 先确认覆盖窗口
grep -aE 'Accepted publickey' /var/log/auth.log | grep -oE 'from [0-9.]+' | sort | uniq -c
sshd -T | grep -E '^(permitrootlogin|pubkeyauthentication|passwordauthentication|subsystem|clientalive|maxstartups)'
ssh-keygen -lf /root/.ssh/authorized_keys    # 只要指纹，勿打印密钥本体
```

### 6.6 判定"重启计数"是抖动还是持续故障（§4.4 的方法）

单次 `kubectl get pods` 的 `RESTARTS N (Xm ago)` **不足以判故障**——`ago` 会自己长大，看起来像在恶化。必须**间隔采样看 N 是否增长**，再配 `kubectl get events --sort-by=.lastTimestamp` 与 `/var/log/pods/<ns>_<pod>_*/*/N.log` 尾行确认是否已重新选主/恢复正常。

### 6.7 判定配置到底哪层生效（§4.6 的方法）

先问"变量到底从哪层注入"，三层各自取一次，不要只看 .env：

```bash
# 1) Deployment 声明了什么（区分 valueFrom vs 字面值）
kubectl get deploy -n agent-platform agent-platform \
  -o jsonpath='{range .spec.template.spec.containers[*]}ENV={.env}{"\n"}ENVFROM={.envFrom}{"\n"}VOLMOUNTS={.volumeMounts}{"\n"}{end}'
# 2) ConfigMap 哪些键真被引用（死键靠这段抓）
kubectl get cm -n agent-platform -o json | /usr/bin/python3 -B -c 'import json,sys
for it in json.load(sys.stdin)["items"]:
    print(it["metadata"]["name"], sorted((it.get("data") or {}).keys()))'
# 3) 进程实际看到的（只取白名单，勿整表打印以免外泄密钥）
kubectl exec -n <NS> <POD> -- sh -c env | grep -E '^(EMBEDDING_MODE|EMBEDDING_MODEL|RERANK_MODE|HF_HOME)='
docker exec <container> sh -c env | grep -E '^(EMBEDDING_MODE|RERANK_MODE|MODELS_DIR)='
```

发一轮 live-vs-manifest 对比时记得**同时在运行 rev 上取同一文件**（`git -C /opt/agent-platform show <rev>:<path>`），否则无法区分"版本差"与"运行时被改"。

### 6.8 分离"镜像自带"与"事后热改"（§5 的方法）

md5 比对只能给"差异数"，**区分不了成因**。能区分成因的是 mtime（以镜像 `Created` 为阈）：

```bash
BUILD=$(date -d '2026-09-22 18:32:59' +%s)      # 镜像 Created（宿主 TZ）
docker exec knowledge-service-web sh -c 'cd /app && find . -name "*.py" \
  -not -path "*__pycache__*" -not -path "./models/*" -not -path "./data/*" \
  -printf "%T@\t%TY-%Tm-%Td %TH:%TM\t%p\n"' \
  | awk -F'\t' -v b="$BUILD" '$1+0 > b+60' | sort -rn
```

> ⚠️ **比较只能用 `%T@`（epoch）**：`%TH:%TM` 走**容器 TZ**（KS 镜像是 UTC），与宿主 +0800 差 8 小时；拿可读时间去比构建时刻会把 8 个热改判成 0 个或反之。另外 docker 镜像层会**保留源文件 mtime**，所以未热改文件的 mtime 看起来是"宿主 checkout 时刻"而非构建时刻，属正常。

### 6.9 三源版本对齐检查（§5 "无处是权威"的方法）

同一个逻辑文件可能同时存在于**容器内 / 宿主仓库 / 126 /tmp** 三处且内容互不相同，逐处取 md5 才能判有没有权威版：

```bash
# 容器侧
docker exec knowledge-service-web md5sum /app/eval/ablation.py
# 宿主仓库侧（10-09 checkout）
cd /opt/agent-platform/applications/knowledge-service && md5sum eval/ablation.py
# 临时目录里可能还留着当轮的手工副本（不要删，它是取证对象）
ls -la --time-style=long-iso /tmp/ablation.py /tmp/run_route_ablation.py /tmp/seed_synthetic_corpus.py
md5sum /tmp/ablation.py /tmp/run_route_ablation.py /tmp/seed_synthetic_corpus.py
```

两个角度互证：**mtime 序**（容器 09-28 早于 /tmp 09-29 ⇒ /tmp 不是 cp 源）+ **md5 三元不同** ⇒ 只能先定基线再回填，不得直接拿任一份覆盖。

### 6.10 把"磁盘慢"查到根 + 把"deployment 被谁改"判到路径（§4.6 / §4.7 的方法）

```bash
# A) 介质与压力（PSI 比事后日志强：avg10 就是"此刻"的 IO stall%）
lsblk -d -o NAME,ROTA,MODEL,SIZE,TRAN
cat /sys/block/vda/queue/rotational
cat /proc/pressure/io
vmstat 1 2                                  # 看最后一列的 wa（iostat/mpstat/smartctl 本机未装）
# B) 排除限流候选
docker inspect -f '{{.HostConfig.BlkioWeight}} {{.HostConfig.BlkioDeviceReadBps}} {{.HostConfig.Memory}}' knowledge-service-etcd
# C) 把"事件"与"常态"分开：按天计数
docker logs --since 2026-09-20T00:00:00 knowledge-service-etcd 2>&1 | grep 'slow fdatasync' \
  | grep -o '"ts":"[0-9-]*' | sed 's/.*":"//' | sort | uniq -c
# D) 找放大器与反例（先记宿主时刻，list-timers 的 LAST/PASSED 依赖它）
date '+%F %T %z'
systemctl list-timers --all --no-pager | grep -iE 'apt|e2scrub|dpkg|logrotate|ua-timer'
journalctl --since "2026-10-08 08:40:00" --until "2026-10-08 09:05:00" --no-pager | grep -iE 'apt|backup'   # 有触发者
dmesg -T | grep -iE 'blocked for more than|I/O error|EXT4-fs error'                                        # 空 = 非设备故障
# E) deployment 被改：last-applied vs LIVE 的差能区分 apply / set-env 两条路径
kubectl -n agent-platform get deploy agent-platform -o jsonpath='{.metadata.annotations}' | tr ',' '\n' | grep -E 'revision|last-applied'
kubectl -n agent-platform get deploy agent-platform -o jsonpath='{.metadata.annotations.kubectl\.kubernetes\.io/last-applied-configuration}' | grep -o '"name":"LLM_[A-Z_]*"[^}]*'
kubectl -n agent-platform get deploy agent-platform -o jsonpath='{.spec.template.spec.containers[0].env}' | tr '{' '\n{' | grep -A2 'LLM_'
grep -iE 'audit' /etc/kubernetes/manifests/kube-apiserver.yaml     # 空 = 审计未开，操作者无从回查
grep -cE 'kubectl +(apply|patch|edit|set|replace|delete|scale)' /root/.bash_history   # 0 + 非交互 ssh ⇒ 不矛盾
```

> 判据：`last-applied-configuration` 里仍是 `configMapKeyRef` 而 LIVE 变成 `value:` ⇒ **走过 `kubectl set env`/`edit`**（apply 会把注解一起更新）。遇到"线上与 manifest 不一致但注解一致"时，先查仓库自己的部署记录（本例的 `deploy/k8s/VERIFICATION.md` §C）再怀疑外部偷改。

### 6.11 判"线上热改要不要救回"的三步硬判据（§5 G4 结论的方法）

md5 只能给"差异数"，mtime 只能猜"成因"，**两者都答不了"这份内容丢了吗"**。能答的是下面三步（全只读）：

```bash
# 1) 权威热改清单：容器可写层 vs 镜像层（无需靠 mtime 推断，也不会漏非 .py 与删除项）
docker diff knowledge-service-web | grep -E '^[ACD] .*\.py$' | grep -v __pycache__
docker diff knowledge-service-web | awk '{print $1}' | sort | uniq -c    # A/C/D 计数，D>0 要单独看
docker inspect -f '{{.GraphDriver.Data.UpperDir}}' knowledge-service-web  # 可写层实体位置，du 判规模

# 2) 取两个基线：镜像无 GIT_REV 时，用"构建时刻之前最后一个提交"作最佳估计
git -C /opt/agent-platform rev-list -1 --before="2026-09-22 18:32:59" HEAD

# 3) 决定性一问：容器这份字节形态是否曾在仓库出现过
docker exec knowledge-service-web cat /app/eval/ablation.py </dev/null > /tmp/x.py
git -C /opt/agent-platform hash-object /tmp/x.py        # 不带 -w：只算 OID，不往对象库写东西
git -C /opt/agent-platform cat-file -t <OID>            # blob ⇒ 曾入库；could not get object info ⇒ 从未入库
git -C /opt/agent-platform log --all --format='%h %ad %s' --date=iso --find-object=<OID> -- <repo_path>
git -C /opt/agent-platform show HEAD:<repo_path> > /tmp/h.py   # 再 diff：+ 只在容器，- 只在仓库
```

> 三步怎么读：`cat-file -t` 命中 ⇒ 容器内容等于某个入库版 ⇒ **只是镜像旧**，重建即对齐，不需救代码（本例 5 个）。
> 未命中 ⇒ 再看 `diff` 的两个方向：若"只在容器"的行在 HEAD 里能找到同名概念（本例 `ROUTE_CONFIGS`、`LEXICAL_WEIGHT_SCAN` 五档权重逐字相同），
> 则容器版只是**被取代的早期草稿**，知识未丢；只有"HEAD 里找不到对应概念"才是真丢失，才需要救回（本例 0 个）。
> 反过来说，若 `vs HEAD` 的 `-` 侧是已入库的修复（本例 `resolve_server_tenant`/`asyncio.to_thread`/MinIO fail-fast），
> 那真正的风险是**线上缺修复**，而不是"线上有野代码"——两者的处置完全不同，必须先分清楚。

### 6.12 把"0 命中"当成证据之前，先证明被测请求真的跑到了那里（2026-10-12 实踩）

同一轮里我连着造了两个**假绿灯**，形状值得记：

```bash
# 反例（上一版探针的写法）：报 LEAK_OK，其实数的是不存在的文件
curl -s -N --max-time 150 -o /tmp/body.txt ... POST /query
grep -c Traceback /tmp/body.txt        # → "grep: 没有那个文件"，被 tail 吞掉
python3 -c 'print(len(open("/tmp/body.txt").read()))'  # 空体上任何计数都是 0
```

| 坑 | 为什么会骗人 | 正确写法 |
|---|---|---|
| `curl -s` | 把"我自己 `--max-time` 超时了"(rc=28) 和"服务端返回空"压成同一个观感 | 用 `-sS` 或 `-w 'http=%{http_code} bytes=%{size_download} time_total=%{time_total}'`，**先确认请求真的完成了** |
| `curl -o f` 收 0 字节 | **不创建目标文件** ⇒ 下游 grep/python 的 0 命中是"文件不存在"而不是"没内容" | 先 `: > f`；并在读取处显式判空 ⇒ 空体**拒绝产出结论**，而不是报 OK |
| 探针与线上不同构 | 我漏了 `HF_HUB_OFFLINE`，260s 全被 huggingface.co 的重试预算吃掉，测的根本不是模型 | 探针要复刻线上开关集合；差异项（如 `EMBEDDING_MODE`）**写进结论的边界**而不是留成隐含变量 |
| 退出码只看最后一个命令 | `bash -c` 串里前面失败会被后面的成功盖掉 | 关键步骤各自 `rc=$?` 记录并打印 |

顺带这条才是本轮最值钱的收获：**探针规格写错并没有让结论变错，而是让结论变得没测到东西**——
分辨这两种失败的唯一办法，是把服务端日志与客户端读数**同时**抓（`kubectl logs -f` 早于提问启动，
探针删除即不可恢复）。

## 7. 待查项验证结果（原待拍板清单）

| # | 原问题 | 结果 | 关键证据 | 剩余边界 |
|---|---|---|---|---|
| G1 | /opt/ap-models 到底服务谁 | ✅ **已闭合**：10-09 建测试环境时的 `HF_HOME` 缓存，服务容器内补跑测试，**不服务任何线上运行时** | e17：pod `volumeMounts`/`volumes` 均空、hostPath 仅见于 postgres；/root 脚本与 .bash_history、/opt/ap-s7logs 均无 `ap-models`/`HF_HOME` 引用 | 写入者当时的完整命令无痕迹（history 未落盘），不影响定性 |
| G2 | INTENT_EMBEDDING_MODEL 口径（宿主 vs 容器） | ✅ **已闭合，且死键成因已指认**：平台侧根本未注入 `EMBEDDING_MODE`；**ConfigMap 的 3 个 LLM_* 是死键**，而改写路径已判明为**本项目自己的部署演练**（`kubectl set env` 类就地改写，命令形制已入库） | e17[4] pod env 只有 `EMBEDDING_MODEL=bge-small-zh`；e19[4] CM keys vs `configMapKeyRef` 引用集，差集={LLM_BASE_URL, LLM_MODEL, LLM_FALLBACK_MODEL}；e19[1b]/e20[1b] 两 rev 的 manifest 均为 CM 引用；**e23[7] last-applied 仍为 configMapKeyRef 而 LIVE 为 value ⇒ 非 apply 类就地改写；仓库 `deploy/k8s/VERIFICATION.md` §C / `README.md` 明写该命令与同样的 modelScope/DeepSeek 字面值；`revision=9`** | 服务端审计未开（e23[8] apiserver manifest 无 `--audit-log-path`）+ 非交互 ssh 不落 history ⇒ **那次会话的发起点无法硬证**（推断为本机经 ssh 执行）；**是否把线上改回 CM 引用 = 待拍板** |
| G3 | mock 相关取值各环境取何值 | ✅ **已闭合**：平台侧确定跑 **MockEmbedder**；`local` 不可用仅限于 `agent-platform:dev` 镜像，**KS 镜像支持 local** | e18[1] Secret 键集无 EMBEDDING_API_KEY；e17[5] pod 内 `find_spec` 四件全 False；e18[3] KS 镜像内四件 + FlagEmbedding 全 True；e18[6] KS 容器 EMBEDDING_MODE（web=api / rageval=local） | 无 |
| G4 | 17 项线上代码漂移如何处置 | ✅ **已闭合（语义 diff 已取，结论与原假设相反）**：8 个热改文件 = **5 个容器内容即已入库 commit** + **3 个从未入库的 eval 草稿但 HEAD 已含全部关键概念** ⇒ **无需手工救回任何代码**；真实债务是**线上 `import_router.py` 缺 3 项已入库修复**（租户注入 / `asyncio.to_thread` / MinIO fail-fast），处置 = 重新构建并分发 KS 镜像 | e24[1] `docker diff` 可写层 9 个 .py、D=0；e24[2] 逐文件 blob OID + `cat-file -t` + `--find-object`（A 类命中 `34f68ed`/`04b08cf`，3 个 `vs HEAD hunks=0`）；e25[3] 容器独有行抽样 + 本机 HEAD grep（`ROUTE_CONFIGS`/`EVAL_COLLECTION_NAME`/五档权重均在）；e25[4] 可写层仅 444K | **是否重新构建镜像并分发 = 待拍板**（属运行环境变更，本轮未动）；`B_rev` 仅为"构建时点最佳估计"而非硬证（KS 镜像无 `GIT_REV`），但不影响结论——A 类靠对象库命中、B 类靠 HEAD 内容包含 |
| G5 | milvus 10-09 17:38 重启是否人为 | ❌ **非人为（上游也已闭合）**：etcd lease 丢失触发的应用**自主退出**；再上游 = **vda ROTA=1 的慢 fdatasync（953 条且每天都有）+ Ubuntu 维护定时器放大 + etcd 无 IO 隔离** | e19[1] 停机前链；e20[1] 16 次拉起；e21[1] 114/882 条；e19[1] 全栈 rc 普查；**e23[1] lsblk ROTA=1 + dmesg 无 IO 错误、e23[2] PSI avg10=46 + wa=25、e23[3] blkio=0/Mem=0、e23[4] 953 条按日分布（最后一条距脚本自打时刻仅 1 秒 = 执行当下）、e23[6] 08:44:30 apt-daily 群 + e2scrub_all 与 8 次重启吻合** | 后端存储真实形态（网络盘/云盘）126 上不可见，`smartctl`/`iostat`/`mpstat` 未装 ⇒ 无法区分"介质慢"与"后端抖动"；**处置（错峰 timer / 独占盘 / PSI 监控）= 待拍板** |
| G6 | pod exitCode=137 根因 | ✅ **定性完成**：非应用崩溃——外部依赖断连（postgres DNS + OTLP no route）+ 优雅关闭未完成的 terminationGracePeriod 被 SIGKILL | e17[8] `kubectl logs --previous` 尾部序列（含 `failed to resolve host 'postgres'`、`No route to host` 192.168.100.126:4318） | 上游网络扰动的诱因属集群层，126 上无更详细记录；pod 在 ambari02，需该节点侧日志才能双向印证 |
| G7 | distribute.sh 是否真把镜像送到了 worker | ✅ **逻辑闭合，无需连 125**：pod 正在 ambari02 跑该 imageID，而集群无 registry 且 `IfNotPresent` ⇒ 镜像必然是导入到该节点的 | e19[2] pod `imageID=sha256:f37bcdb1ed7a…`与 moby/k8s.io 侧 `f37bcdb1ed7a` 咬合；manifest `image: agent-platform:dev` 无 registry 前缀；126 本机 k8s.io 也有同镜像 | "由 distribute.sh 还是手工命令执行"指名不了（bash_history 零命中）；若需硬证据仍需连 125 |
| G8 | 磁盘 avail 32G 是否需清理 | ✅ **有数可依**：真正可回收 ≈ **13.75GB**（两个 dangling KS 镜像各 unique 6.879GB），且二者与现役镜像同日相隔 30 分钟构建 ⇒ **删了不损失回滚能力**；Build Cache 20.66GB 实测不可回收（仅 3MB） | e17[10] `docker system df`；e18[9] `df -v` 镜像明细；e21[2] 三个 KS 镜像 Created/labels；e20[2] build cache 单项 6.88GB 与 `/data/docker/buildkit` 仅 2.7M；**e25[4] 热改证据在容器可写层（444K）而不在这两个镜像里 ⇒ 清理不影响 §5 取证** | **是否执行清理 = 待拍板**（本轮只列不改）；清理与 G5 磁盘抖动相关，不只是容量问题 |

## 8. 本基线的可靠性边界

- 硬件规格沿用 [deploy/k8s/VERIFICATION.md](../../deploy/k8s/VERIFICATION.md) 节点表，但**内存已按 `free -g` 实测更正为 15G**（原记 31G 作废）。
- auth.log 当前+轮转文件仅覆盖 2026-09-28 之后，**更早的 bundle 传输无登录证据**（09-22 那次仅有 clone 动作词与 pack mtime）。
- bundle 的精确构造命令与 rev 区间无法回查（包已删，无 `git bundle list-heads` 对象）；09-28/09-30 各轮的 bundle 名称不可回查（FETCH_HEAD 会被覆盖，git 不记历史）。
- 本机 Windows 的 `Find-NetRoute` 在 Clash TUN（接口 Meta，198.18.0.1，默认路由经 198.18.0.2）存在时会指向虚拟接口，**不能用于判定实际出口**；出口以 126 侧 auth.log 来源 IP 为准。`TcpTestSucceeded=True` 在本机不含信息（已记录于 CHANGELOG）。
- 本轮唯一一次进入运行制品的操作是 `kubectl exec ... cat /srv/agent-platform/GIT_REV`（只读单文件，未写、未装、未改）。
- **验证轮（e17–e25）的只读边界**：为闭合 §7 使用了 `docker exec`（仅 `env` / `python -c importlib.util.find_spec` / `find` / `md5sum` / `ls` / `cat` / `wc` / `stat` / `head`）、`kubectl exec`（仅 `env` / `python -V` / `cat`）、`kubectl logs --previous`、`docker logs --since/--until`、`git show <rev>:<path>`、`git rev-list --before`、`git cat-file -e/-t`、`git log --find-object`、`git hash-object`（**不带 `-w`，故不往对象库写任何内容**）、`docker diff`（仅比对可写层与镜像层，不写容器）、`docker inspect -f '{{.GraphDriver.Data.UpperDir}}'` + `du`——**全部为读操作，未写容器内任何文件、未装包、未改配置**；唯一写入位置是 126 的 /tmp 下本轮自建的脚本、输出与临时工作目录（e24/e25 各自建 `e24w`/`e25w` 并在脚本末尾 `rm -rf`），结束即按显式 LIST 删除。
- 验证轮复测的不变量（执行前后均一致）：`HEAD=6cebaa5 dirty=0 logs=7`、`running=9 volumes=9 pods=15`、`pycache=46`、`venv_dirs=2`、`images_moby=14`。
- §5 的三源比对与 §6.9 是用**单条内联 ssh 只读命令**取回的（`ls -la` / `md5sum` / `docker exec md5sum`），无脚本产物、不入 §0 表；/tmp 下那三个同名副本**属他人/历史文件，本轮未删未改**。
- 同上形式，e23 后另补了两条**内联只读命令**：一为了确认故障窗口里反复 `Deactivated` 的 scope 到底属于哪个容器（`docker inspect -f '{{.Name}} restart={{.RestartCount}} started={{.State.StartedAt}} f558459e9d83` ⇒ `/knowledge-service-milvus`），一为了列 KS 栈的 `docker ps -a --format` 状态。均无产物。e23 的远端产物（`/tmp/e23_upstream.sh`、`/tmp/e23_out.txt`）已按显式 LIST 删除，宽口径复核 `ls -1 /tmp | grep -Ec '^(e[0-9]+_|ap_|evidence)' = 0`，**/tmp 下其余文件（与本组证据无关的历史脚本与日志）未删未改**。
- §4/§5 读数取自 13:15–13:57 三次采样；§4.6/§4.7 与 §5 的校准值来自 e17–e22（同日更晚时点，脚本未单独打印宿主时钟）。AGE/"ago" 类字段随时间漂移，绝对时间戳与计数（14/21/40、548、9/15、236/74/8）为该时点事实。
- e23 的宿主时钟**已显式打印**：`2026-10-10 14:53:49 +0800`（故 PSI 46%、slow fdatasync 最新条 `06:53:50Z` = 14:53:50 +0800 是**执行当下**而非历史）。本轮脚本 MD5（双端一致）：e23_upstream.sh = `aefdb0e4188e0ae72c137335e736614a`（5700B，CR=0，`bash -n` SYNTAX_OK），输出 e23_out.txt = `6dc100a431afb8736f1a71f02497f8fb`（195 行）。
- e24/e25 的宿主时钟：`16:26:13 +0800` / `16:29:22 +0800`（后者仅比前者晚 3 分钟，故两轮的容器读数可直接互校）。双端 MD5 一致：e24_hotedit_diff.sh = `3aca0fac231be2d50b7f7ee63b7a0982`（6279B，CR=0，117 行）、e25_verify_gap.sh = `c59f73261175677804d5ccacf11d8440`（6381B，CR=0，98 行）。
- §5 的 G4 结论里，"容器内容是否曾入库"靠**对象库命中**判定，与 `B_rev` 无关；而"HEAD 已含全部关键概念"是靠**本机仓库工作区 grep**（`git status --porcelain`=0 且与 HEAD 同内容）而非远端读数，两者属不同机器，核对时需区分。
- **e23 新增的只读工具面与边界**：`lsblk` / `cat /sys/block/*` / `/proc/pressure/io` / `vmstat 1 2` / `docker inspect` / `docker logs --since` / `dmesg -T` / `journalctl [-k] --since --until` / `systemctl list-timers --all`（只列不改）/ `kubectl get -o jsonpath` / `grep /etc/kubernetes/manifests` / `grep /root/.bash_history`。**未执行任何 `systemctl stop/disable/mask`、未动 timer、未动 deployment、未动容器**；`crictl ps -n k8s.io | grep -c kube-apiserver` 返回 0 **未作解读**（crictl 未显式指定 runtime endpoint，不能据此判 apiserver 在否）。

### 6.13 判"路由到底谁在做"与"消融是否有效"（2026-10-13 实跑配方）

这两件事都不能靠读答案判断，各自有可复核的取证面。

```bash
NS=agent-platform
POD=$(kubectl -n $NS get pod -l app=agent-platform -o jsonpath='{.items[0].metadata.name}')
KEY=$(kubectl -n $NS get secret observability-keys -o jsonpath='{.data.API_KEY}' | base64 -d)

# A) 路由器到底是谁：数告警 + 因果核对（一发一问，计数必须 +1）
b=$(kubectl -n $NS logs $POD | grep -c 'This response_format type is unavailable')
env AP_KEY="$KEY" AP_Q="根据文档，<唯一标记防缓存>" python3 - < /tmp/r30q.py
a=$(kubectl -n $NS logs $POD | grep -c 'This response_format type is unavailable')
echo "增量=$((a-b))"          # =1 ⇒ 这一问确实走了"结构化失败→回退词表"

# B) 回放源全集（四类，缺一个都可能把"没检索"读成"检索成功"）
kubectl -n $NS exec -i $POD -- python - counts < /tmp/r30db.py
#   semantic_cache / memories / episodic_memories / procedural_memories
#   / checkpoints / checkpoint_blobs / checkpoint_writes   ← LangGraph 会话状态，最容易漏

# C) 消融前"自变量是否成立"三查（缺一即整轮作废）
kubectl -n $NS exec -i $POD -- python - probe '报馆图纸' < /tmp/r30db.py
#   ① 谓词必须是 LIKE '%短语%'（写成 '短语%' 是前缀匹配，会命中 0 块而不报错）
#   ② 命中必须唯一：'截止日期' 在库里命中 11 块，拿它当谓词删不干净 ⇒ 换更特定的短语
#   ③ 提问必须带 rag 特征词且首读 route=rag + evidence count>0，否则删没删块结果都一样
```

> 为什么 C③ 值得单列：2026-10-13 的 r30 整轮就是这么废的——问句"特装展台报馆的电子文件要压缩成哪几个文件包？"
> 一字不含特征词 ⇒ 消融前/后/还原后**三次全部 `route=direct`、`evidence count=0`、答案全部"无法确定"**。
> 三次读数高度"一致"，看着像实验很稳，实际是自变量从没生效。改带"根据文档"重跑（r31）才拿到有效对照。

### 4.11 2026-10-13 观测面接线后的部署快照（rev `6ac466af`）

> **这张表描述到取证时刻为止，滚动一次即失效**（§2 的教训：读数必须绑定 rev，别引用表、要复算命令）。
> 取证时刻：2026-10-13 08:0x UTC（三节点 `date -u +%s` 互差 ≤1s，已量）。

| 项 | 值 |
|---|---|
| namespace / 工作负载 | `agent-platform` / `deploy/agent-platform`，`replicas=1` |
| Pod | `agent-platform-85794678c-9hjg4`，node **ambari01(241)**，Pod IP 10.244.2.15，restarts **0**，Ready 1/1 |
| 镜像 | tag `agent-platform:dev`（可变），Pod `imageID=sha256:c18dc76a93f8fb55fbd5297f1a642d8f116894230b647beb32d401ff34819736` |
| Pod 内 `GIT_REV` | `6ac466af2ebf2d6d9f09b1fb181525a72268bdc3`（`verify.sh` 回读，rc=0） |
| 三节点 containerd-k8s | 125 / 126 / 241 全部 = **`c18dc76a93f8f`**（1.68GB）。241 是**补了一次本地导入**才齐的（见坑档 §4） |
| 宿主 moby 库（126） | `agent-platform:dev` = `9d72645cbafc`，内含 `GIT_REV=3cd5580` —— **中止构建的残留，不是线上对象**，别拿它做证明 |
| `/health` 生效值 | `storage=postgres` `sql_backend=postgres` `embedding_backend=LocalEmbedder` `embedding_real=true` `llm=true` `otel=true/otel_status=ACTIVE` `langfuse_enabled=true` `langfuse_ready=true` `forensic=true` `guard_enabled=true` `auth_enabled=true` `identity_mode=single` `planner=deterministic`；`search/mcp/scheduler/control_plane/cost_governance/admission=false` |
| 依赖 Pod | `postgres-6ff4688bb8-vn7v6` @ ambari03(126)（被 `nodeSelector` 钉住），14d，restarts 0 |
| Jaeger（观测面 A） | **126 的 moby 容器** `jaeger`，Up 13 days，`4317/4318→host`、`16686→host`；OTLP 端点由 CM 注入 `OTEL_ENDPOINT=http://192.168.100.126:4318/v1/traces`。**服务本身活着**：10-13 从 Pod 内查 `/api/services`、`/api/traces?operation=POST /query` 全部正常应答（所以"收得到 span"与"UI 打不开"是两件事，别混着讲）。UI 从办公网**当前不可达**，见手册 §9 ㉑ |
| Langfuse（观测面 B） | **241 的 moby 栈** `lf-langfuse`/`lf-langfuse-worker`/`lf-clickhouse`/`lf-langfuse-db`/`lf-valkey`/`lf-minio`（6 个，均 healthy），只有 web 发布 `3000`；`LANGFUSE_HOST=http://192.168.100.241:3000`。**演示期暂常驻**（实测 PSI `avg10=3.59%`、241 磁盘余 25G、内存 avail 11G；冷启动需等 ~300s，故不停） |
| port-forward | 126 `:18000 → svc/agent-platform:8000`；`portforward.sh` **无 restart 子命令**，换 Pod 要 stop+start。⚠️ 10-13 收盘前：**办公网侧 126:18000 与 126:16686 均无应答**（curl `HTTP 000`），而同刻 241:3000 → 200 ⇒ 观测/控制台入口别压在 126 上，两候选成因与判据见手册 §9 ㉑ |
| 密钥落点 | `secret/observability-keys` 内 `API_KEY` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`（+ `LLM_API_KEY`）——**只记键名与注入路径，值不落任何文件** |
| 库内数据态（**10:27 UTC 复算**） | `chunks` 303 行 / 7 文档、`semantic_cache` 残留 0、**`checkpoints`/`checkpoint_blobs`/`checkpoint_writes` 三表 0 行**：演示前按拍板把取证残留句整桶清掉（备份在 `126:/tmp/ckpt-backup-host/*.csv`，0600，宿主 `/tmp` ⇒ 重启即失）。本节早前那句"今日 1 个 thread、33 个 blob"到此失效，别引用 |

| 代码漂移复查（**2026-10-14 只读实测**） | ①**需同步回仓库的代码＝0 项**：`git -C /opt/agent-platform status --porcelain` 在 **241 与 126 都为空**；241 HEAD=`6ac466af…`（**等于线上镜像 `GIT_REV`**），126 HEAD=`c01e9cf…`（旧一档，若从 126 构建会被 `build.sh` 的 rev 门禁拦下）。②**本周无人热改容器代码**：`docker diff knowledge-service-web` 共 68 项、`.py` 9 个，mtime 全落在 **09-22 / 09-28**（无一在 10 月）。③KS 侧既有漂移的定性沿用 10-10 的 blob 判定（无一需救回），**真正的债仍是"KS 镜像重建+分发"**（线上 `import_router.py` 缺 3 项已入库修复）。④清桶备份**在位**且字节数与台账逐一对上：`126:/tmp/ckpt-backup-host/{checkpoints 472B, checkpoint_blobs 289052B, checkpoint_writes 79B}`，权限 `drw-------` root-only（⚠️ 内含会话原文，能上机读 root 的人读得到——与 ㉓ 同族，等级低）。⑤**残留待清**：126 `/tmp` 11 个探针脚本（10-13 的 `wipe.py`/`keys.py`/`r30db.py`/`r30q.py` + 9 月的 `ablation.py`/`probe.py`/`kgprobe.py`/`run_route_ablation.py`/`seed_synthetic_corpus.py`/`_patch_126.py`/`_dl_bgem3.py`）、241 `/tmp/ch_check.py`。`keys.py` 已确认**不含任何密钥值**（只打印 Secret 的键名，密钥特征计数 0） |

**本轮在这套现场跑通的判据**（都是回读，不是推断）：

```bash
# 1) 聚合取证（读**跑着的 Pod 内** rev，不再 docker run）
bash deploy/k8s/scripts/verify.sh <expected-rev>          # rc=0：L0 三节点 Ready / Pod Ready /
                                                          # /health 200 + otel_status / rev 相等
# 2) Jaeger 面（单服务）
API_KEY=... bash deploy/k8s/scripts/e2e_traceparent.sh     # rc=0：span 数=8、含 "POST /query"
                                                          #       trace id == 注入的 W3C id
# 3) Langfuse 面（唯一算数判据 A3）
API_KEY=... LF_PK=... LF_SK=... LF_HOST=http://192.168.100.241:3000 \
  python deploy/observability/langfuse_proof.py            # exit 0：2 条 GENERATION，
  #  答案生成 in=1403/out=1547、input 摊平后含 "[来源: …]"；路由决策 in=475/out=164；
  #  trace id == 注入 id。exit 4 = 取证不成立但平台没错（全部命中语义缓存）
```

**边界（不得当成已具备的能力）**：
- 跨服务链路追踪（联邦网关→子服务）**仍未证过** ⇒ 只能说"单服务内一条请求链路"。
- "哪个模型/prompt 版本"在 Langfuse v4 的 `v2/observations` 投影里是 `modelId=null`，UI 与库内 `model` 列才可见 ⇒ 不得声称是 API 可读列。
- 不声明逐次调用成本（per-query cost）。
- 演示侧仍欠：D7 录播、D8 整场彩排 + 六环节留证、浏览器面实拍（需持键者）、`demo-questions.md` §7 判定列。
