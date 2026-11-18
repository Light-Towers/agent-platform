# 内网部署与真环境验证：耗时卡点清单（换个 agent 也能照做）

> 来源：2026-11-18 DocumentStore 协议统一的真环境端到端验证。那次部署+验证因环境/工具问题耗时约 1 个工作日，其中绝大多数不是产品 bug，而是**可预见的卡点**。本文把每个卡点写成「现象 → 根因 → 下次提前做什么」，让接手者（哪怕是完全新的 agent）在动手前就避开。**基础服务（milvus/postgres/etcd/镜像源）通常不频繁变动，本文的命令大多只在首次或换环境时需要复取。**

## 0. 开工前 10 分钟检查（能省掉后面几小时）

按顺序确认，任一不满足就先解决再动代码/部署：

| 检查 | 命令/判据 | 不满足的后果 |
|---|---|---|
| VPN/控制面可达 | `Test-NetConnection <控制面> -Port 22` = True；`ssh root@<控制面> 'command -v kubectl'` 通 | 后面全部白搭 |
| 工作日 | 周末服务器常不可达，先 `Get-Date` 看星期 | 连不上还以为配置错 |
| 磁盘水位 | 构建机 `df -h /` 可用 > 20G（守卫门限 15G 是下限，不是余量） | 构建中途被门禁中止 / kubelet DiskPressure 驱逐 Pod |
| 两侧配置对齐 | 见 §2 配置对齐矩阵——集合名 / 维度 / 租户 / 依赖包，逐项实读 | 验证时逐个暴雷，每次都要 rollout+等 50s |
| 凭据就位 | 需要的 secret（如 embedding API key）在哪、能不能安全复制 | 维度不匹配等降级 |

> **最重要的纪律：先对齐配置，再部署验证。** 这次的顺序错了——先部署，然后在对话检索时逐个发现 pymilvus 缺失、维度不匹配、租户域不一致，每个都要「改配置 → rollout → 等 50s → 重跑」，重复 5 轮。正确做法是部署前把 §2 矩阵全部实读一遍。

## 1. 构建期：pip 下载慢（最大卡点，这次耗约 1.5 小时 + 3 次失败）

**现象**：docker build 卡在 `pip install`，大包 18–80 kB/s，`scipy 35MB` 下了 10 分钟，反复 `ReadTimeoutError: files.pythonhosted.org`。三次失败：① `timeout` 30min 强杀 ② 磁盘门禁 14G<15G 中止 ③ ReadTimeout 一次超时整体失败。

**根因**：根 Dockerfile 的 pip 层没有国内源，wheel 从官方 CDN 国际链路下载。而且 `ENV PIP_INDEX_URL` 对 **editable 安装的 build isolation 子进程不生效**——这是关键陷阱，只设 ENV 没用。

**下次一次做对**（已固化到本仓两个 Dockerfile，无需再做；换仓库时照抄）：
1. `RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple` + `global.trusted-host` —— 写进 `/etc/pip.conf`，**所有 pip 子进程都读**（含 build isolation）。这是核心，仅 ENV 不够。
2. `ENV PIP_TIMEOUT=120 PIP_RETRIES=15` —— 读超时自动重试，不因一次抖动整体失败。
3. torch 这类显式 `--index-url download.pytorch.org/cpu` 的命令不受 pip.conf 影响，但它本身快（15MB/s），不用动。
4. `--network=host` 给 docker build（可选，减少网络栈开销）。

**缓存**：`Build cache usage: 0B` 意味着每次从头下。清悬空层用 `docker image prune -f`（只删无容器引用的层），**别 prune build cache**。这次修好 pip 源后，增量加一个 pymilvus 只花 2 分钟——前提是缓存命中。

**构建守卫不可关**：241 单盘同机跑 Langfuse 观测栈，关 IO 守卫会把验收载体自己打死。用 `IO_LIMIT=80 IO_STRIKES=6` 放宽判定口径（torch 铺大包天然顶 70%+），不是关守卫。详见 AGENTS.md「内网环境」第 7 条 + `docs/operations/nl2sql-release-checklist.md` §3。

## 2. 配置对齐矩阵（部署前逐项实读，避免验证期逐个暴雷）

这次在对话检索阶段才发现并逐个修复 5 项，每项都伴随一次 rollout（约 50s 等待）。下次部署前一次性核对：

| 形状 | 谁提供 | 必须与谁一致 | 这次踩的值 |
|---|---|---|---|
| `DOC_BACKEND` | 平台 deploy env | 决定上传/检索同后端 | milvus（默认） |
| `DOC_MILVUS_URI` | 平台 ConfigMap + deploy env valueFrom | 非空，指向 milvus service | `http://milvus:19530` |
| `DOC_EMBED_*`（KEY/BASE/MODEL/DIM） | 平台 secret + env | 与集合写入 embedder 同模型同维度 | siliconflow / bge-m3 / 1024 |
| 集合 dense_vector 维度 | Milvus schema | == DOC_EMBED_DIM | 1024 |
| `KNOWLEDGE_DEFAULT_TENANT_ID`（KS）| KS ConfigMap | == 平台 `SINGLE_TENANT` | default |
| `CHUNKS_COLLECTION`（KS）| KS ConfigMap | == 平台 `DOC_MILVUS_COLLECTION` | platform_doc_v2_bge_m3 |
| 依赖包 | 镜像 | Milvus 实现需 pymilvus | 平台补 `pymilvus==3.0.3`（与 KS 对齐）|

**关键教训**：
- **tenant 域不一致最隐蔽**：文档写的是 tenant=exhibition，平台用户令牌是 default，租户隔离正确拦截导致"搜不到"——看起来像 bug，其实是安全机制生效。对齐 `KNOWLEDGE_DEFAULT_TENANT_ID` 与 `SINGLE_TENANT`。
- **维度不匹配**：平台没配 DOC_EMBED_API_KEY 时回退主 embedder（bge-small-zh 512 维），但集合是 bge-m3 1024 维 → 检索降级。密钥在 KS 的 secret 里，复制时走管道（`kubectl get secret -o jsonpath | base64 -d | wc -c` 只验长度），**不落盘、不进 argv**。
- **依赖缺失**：平台镜像若只装 `agent-core[memory-embed-local]`，Milvus 实现需要的 pymilvus 不在其中 → `No module named 'pymilvus'`。加依赖时版本与 KS 对齐（3.0.3）。

**ConfigMap 改键后必须做两件事**：① `kubectl patch cm ... --type merge`（整对象 apply 会覆盖其他键）② **deployment env 是显式列表时不走 envFrom，必须在 deploy env 里加一条 valueFrom configMapKeyRef**，否则改了 ConfigMap Pod 里也读不到。这是这次卡住的一个点。用 `kubectl -n <ns> set env deploy/<name> --from=configmap/<cm> --keys=<key>`。

## 3. 分发期：registry 通道 > scp tarball > build.sh 自带分发

**现象**：`distribute.sh` 的 scp 477MB tarball 到 125/126 时 `lost connection` / `client_loop: send disconnect`，失败。

**根因**：大 tarball 走 ssh 不稳；且 `build_with_io_guard.sh` 自带的 `distribute.sh` 默认 `WORKERS=125 241`（从 126 构建的历史形态），从 241 构建会漏 126。

**下次一次做对**：用 `distribute_registry.sh`（`ctr push/pull` 增量层，实测 21–721 MiB/s，不传 tarball）：
```
IMAGES="agent-platform:dev knowledge-service-web:latest" \
  bash deploy/k8s/scripts/distribute_registry.sh <节点1> <节点2>
```
两个必须手动补的点（这次都踩了）：
1. **列出所有节点**：从 241 跑要显式 `125 126`，**外加 241 本机**——脚本的 WORKERS 不含构建机自己，而 Pod 会调度到 241。
2. **双 ref 都要 tag**：containerd 里同一镜像有两个 ref（`192.168.100.241:5000/<name>:<tag>` 和 `docker.io/library/<name>:<tag>`），kubelet 按后者解析。`ctr images tag --force` 把两个 ref 都指向新 digest，并用 `crictl images` 核对（不是只看 `ctr images ls`）。这次 241 本地两个 ref 指向不同 digest，导致调度到 241 的 Pod ImagePullBackOff，排查花了很久。

**镜像版本标识陷阱**：docker 短 ID（`23ed9b01`）与 OCI manifest digest（`sha256:2f35514d...`）是同一镜像的两种 ID。`ctr/crictl` 读的是后者——取证基线要记后者，否则量具误报漂移（这次踩过）。

## 4. 上线期：hostPort 死锁与滚动

**现象**：`rollout restart deploy/ks-web` 卡在"new Pod Pending / old replicas pending termination"。

**根因**：ks-web 有 `hostPort: 8000` + `nodeSelector: ambari03`，新 Pod 要同节点同端口，旧 Pod 占着不让，RollingUpdate（maxUnavailable 向下取整=0）不会主动退旧 Pod。**agent-platform 无 hostPort，不受影响，正常滚动。**

**处理**：手动删旧 Pod 释放端口，`kubectl -n <ns> delete pod <old-pod>`，新 Pod 即刻调度起来。删前确认新 Pod 镜像 digest 已是新的（`kubectl get pod <new> -o jsonpath=...imageID`）。

**rollout status 超时 ≠ 失败**：`error: timed out waiting for the condition` 常常只是慢（镜像 import/pull + readiness initialDelay 30s），用 `kubectl get pod -o custom-columns=...READY...` 看实际状态，别急着重来。

## 5. 验证期：语义缓存、鉴权门槛、工具转义

**语义缓存命中时模型根本没调用**：问过的题（即使上次答案是降级串）会被缓存，`cache_hit` 事件 + 空 answer。绕过方法：
- 加随机前缀**无效**（语义哈希会归一化掉）；
- **换完全不同的语义/语言**有效（这次中文问法绕过了之前英文问法的缓存）。
- 取证问题必须语义新颖，否则"先命中≠全到"，会误判成"有数据"。

**鉴权门槛**：`/kb/uploads` 需要 `kb.upload` feature，viewer 角色是 403。真环境验证该端点时需临时提权测试账号（DB `UPDATE users SET role='admin', is_admin=true WHERE id=...`），**验证后一定降回 viewer**（这次忘了一次，靠脚本补做）。提权/降权都是 D3，须人授权。

**PowerShell → ssh 转义**（Windows 本机高频坑）：复杂远程命令里的 `|`、`$`、`2>/dev/null`、引号、heredoc BOM 会被 PowerShell 解析或截断，表现是 `bash: syntax error` / `command not found`。**解法：所有复杂远程命令写成 `.sh` 文件 → scp 到目标机 → `bash /tmp/x.sh`**。简单单行命令用 PowerShell 单引号包整体也行，但含 `$`/`|` 一律走脚本文件。

**长连接 ssh 会 reset**：本机到内网的 ssh 会话可能 `client_loop: send disconnect`，但**远端脚本通常继续跑完**。用后台任务 + 实时日志（`> log 2>&1`），靠远端产物/进程判进展，别因本地连接断就重跑导致重复操作。

**SSE 读数**：事件帧是平铺的（payload 恒空），evidence/citation 从 `data:` 的 JSON 里取；判据要看原始 evidence 片段，不能只看"看到了"。观测类判据必须是"后端里查得到本次原文"（状态灯亮≠数据到）。

**下游服务 502（如"数据源查询失败：问数服务不可达 ConnectError"）**：先分清三层再动手——
1. `kubectl get pod -l app=<svc>` 看 Pod 是否 Ready + `kubectl get endpoints <svc>` 是否为空（endpoints 空 ⇒ 平台 ConnectError 502）；
2. 进 Pod `curl /health`（liveness，常 200）vs `curl /ready`（readiness，连库探活）——**/health 200 但 /ready 503 是典型信号**：进程活着但依赖池不可用，k8s 不切流量；
3. `/ready` 返回体带池名和错误类型（如 `{"meta":"TooManyRequests","dw":"TooManyRequests"}`）。再查 `/api/pools` 的 `pool_size/pool_available/requests_waiting`，并用 psycopg **直连 DSN 绕池 SELECT 1**：
   - 直连 OK + `pool_size=0 / waiting>0` ⇒ **进程内连接池卡死**（池无法自愈），重启 Pod 重建池即可：
     ```
     kubectl -n <ns> delete pod <bad-pod-1> <bad-pod-2>   # ReplicaSet 重建
     ```
     验 `/ready=200` + endpoints 非空 + 原失败 URL 200。
   - 直连也失败 ⇒ 是 DB/网络问题，去查 DSN 主机可达性，别重启 Pod（徒劳）。
   - 这类卡死可能与本次部署无关（看 Pod age / 503 持续时间，这次已持续 15h），定性后再报，别顺手改产品代码。重启 Pod 属 D3，须人授权。

## 6. 治本：把"复审触发"变成机械门禁

> 基础服务不常变，但**判据绑 rev/配置**，换任一形状就需重跑。此前"复审触发条件"只是散文，靠人记必然漂移（把上一轮读数搬进本轮账面）。

本仓已落地的机制（换环境/换判据时照此扩展）：
- 台账 `scripts/evidence/baselines/*.json`：登记判据依赖的可实读形状 + 基线值 + `affects`。
- 量具 `scripts/evidence/verify_basis_drift.py`：从 LIVE 实读探针与基线对码，漂移 rc=1 报"需重跑哪几条"，前置不可用 rc=2；`--list` 列台账。
- 运行：`EVIDENCE_SSH_HOST=<控制面IP> uv run --no-sync python scripts/evidence/verify_basis_drift.py`
- 新判据纳入时**必须做非空转反证**（投毒基线 → 应报红）。

详见 plan-knowledge-base-model-2026-11-17.md §8.5 + `scripts/evidence/README.md`。

## 7. 时间线复盘（这次为什么慢）

| 阶段 | 实际耗时 | 本可避免 |
|---|---|---|
| pip 下载/构建失败重试 | ~1.5h + 3 次失败 | §1（pip.conf + 超时重试）——首次就该固化 |
| 逐项配置修复（每项 rollout+等50s+重跑）| ~40min | §2（部署前对齐矩阵）|
| scp 分发失败 → 换 registry | ~15min | §3（直接走 registry）|
| 241 双 ref digest 混乱排查 | ~20min | §3（双 ref 都 tag + crictl 核对）|
| hostPort 死锁 | ~10min | §4（预知并直接删旧 Pod）|
| milvus 崩 + 镜像缺失 | ~15min | §0（开工前查健康端点）|
| 语义缓存绕法试错 | ~15min | §5（换全新语义问法）|
| PowerShell/ssh 转义试错 | 累计 ~20min | §5（复杂命令走脚本文件）|

**一句话总结**：慢的不是产品，是「环境配置未预对齐 + 工具链转义 + 容器分发细节」。基础服务稳定后，这些检查一次成型、后续几乎零成本；换任何 agent，从 §0 清单开始即可。
