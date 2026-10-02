# K8s 最小部署验证报告（kubeadm 三节点集群 · agent-platform）

> 执行日期：2026-09-29 · 环境：内网 3 台 Ubuntu 22.04.2 测试机
> 结论：**L0-L5 全部达标**（含可选加分项 HPA）。postgres 落 control-plane（ambari03），agent-platform 落 worker（跨节点分布），节点驱逐迁移 8.4s。

## 1. 机器探测（步骤 0）

| 机器 | IP | hostname | 角色 | OS / 架构 | 内存 | root 盘 |
|---|---|---|---|---|---|---|
| 测试机 1 | 192.168.100.126 | **ambari03** | control-plane（兼数据节点，跑 postgres） | Ubuntu 22.04.2 / x86_64 | 8C，满足 | 98G（/ 与 /data 同一文件系统，非独立分区） |
| 测试机 2 | 192.168.100.125 | **ambari02** | worker | Ubuntu 22.04.2 / x86_64 | 满足 | 98G |
| 测试机 3 | 192.168.100.241 | **ambari01** | worker（驱逐演练目标） | Ubuntu 22.04.2 / x86_64 | 满足 | 98G |

- kernel：5.15.0-181-generic · CRI：containerd 2.2.1 · k8s：v1.31.14
- **共用测试机现状**：docker 在跑其他团队服务——126=8 容器（knowledge-service 栈：milvus/neo4j/mongo/etcd/pgvector 等）、125=9（MaxKB/DataEase/APISIX/MySQL）、241=1（exhibition-dashboard）。
- **241 磁盘**：初始 85%（14G 空闲）。经排查真因是 `/root`(38G，含 .m2 21G/.vscode-server/.lingma-server/.cache/.npm) + `/opt/src`(16G)，**并非容器日志**（容器日志仅 40KB）。用户授权清理缓存 + 监控日志后 → **46%（51G 空闲）**。

## 2. 架构决策：隔离双 containerd 实例（关键）

三台机器 containerd 2.2.1 已装**且与 docker 共用**。README 步骤 1.3（覆盖 config + 重启 containerd）会**打断他人容器**。用户决策采用**独立第二 containerd 实例**方案：

| 维度 | docker 共享 containerd（不动） | k8s 专用 containerd-k8s（新建） |
|---|---|---|
| systemd unit | `containerd.service` | `containerd-k8s.service` |
| root | `/var/lib/containerd` | `/var/lib/containerd-k8s` |
| state | `/run/containerd` | `/run/containerd-k8s` |
| sock | `/run/containerd/containerd.sock` | `/run/containerd-k8s/containerd.sock` |
| SystemdCgroup | — | **true** |

- kubelet `KUBELET_EXTRA_ARGS=--container-runtime-endpoint=unix:///run/containerd-k8s/containerd.sock`；crictl.yaml 同步。
- **隔离性实证**：kubeadm init 后 control-plane 静态 pod（etcd/apiserver/cm/scheduler/kube-proxy）镜像**仅存在于 containerd-k8s**（未导入 docker 侧）却全部 `Running` → 证明 kubelet 走的是隔离实例；同时 docker 侧 8 个他人容器全程 `Running` 未受影响。

## 3. 集群拓扑（L0）

```
$ kubectl get nodes -o wide
NAME       STATUS   ROLES           AGE   VERSION    INTERNAL-IP      OS-IMAGE             CONTAINER-RUNTIME
ambari01   Ready    <none>          32m   v1.31.14   192.168.100.241  Ubuntu 22.04.2 LTS   containerd://2.2.1
ambari02   Ready    <none>          32m   v1.31.14   192.168.100.125  Ubuntu 22.04.2 LTS   containerd://2.2.1
ambari03   Ready    control-plane   35m   v1.31.14   192.168.100.126  Ubuntu 22.04.2 LTS   containerd://2.2.1
```
✅ **L0 达标**：三节点全部 Ready。CNI = flannel v0.28.9（pod-cidr 10.244.0.0/16）。

### 组网关键命令
- init（126）：`kubeadm init --image-repository registry.aliyuncs.com/google_containers --pod-network-cidr=10.244.0.0/16 --apiserver-advertise-address=192.168.100.126 --cri-socket=unix:///run/containerd-k8s/containerd.sock`（配置见 `/root/kubeadm-config.yaml`，v1beta4，cgroupDriver=systemd）
- join（125/241）：`kubeadm join 192.168.100.126:6443 --token <token> --discovery-token-ca-cert-hash sha256:<hash> --cri-socket=unix:///run/containerd-k8s/containerd.sock` → 双 RC=0

## 4. 镜像构建与分发（步骤 5）

- 在 126（ambari03）`docker build -t agent-platform:dev .`：**RC=0**，耗时 **4m13s**（15:15:26 → 15:19:39），产物 `agent-platform:dev` 364MB。
- 分发（适配隔离 containerd）：`docker save agent-platform:dev pgvector/pgvector:pg16 | gzip > /tmp/images.tar.gz`（255M），scp 到 125/241，三台执行
  `ctr --address /run/containerd-k8s/containerd.sock -n k8s.io images import /tmp/images.tar.gz` → **三台 IMP_RC=0**，`crictl images` 确认 agent-platform + pgvector 均在 k8s.io 命名空间。

## 5. 分层验收（L1-L5）

### L1 编排 ✅
```
$ kubectl -n agent-platform get pods,svc -o wide
pod/agent-platform-...-n2mrh   1/1  Running  10.244.1.7  ambari02   # worker
pod/postgres-...-vn7v6         1/1  Running  10.244.0.2  ambari03   # control-plane
service/agent-platform   ClusterIP  10.98.76.44    8000/TCP
service/postgres         ClusterIP  10.104.165.121 5432/TCP
```
- describe pod 事件：`Container image "agent-platform:dev" already present on machine` → `Created` → `Started`（**再次佐证隔离镜像导入生效**）。pod `phase=Running ready=true`。

### L2 健康 ✅
```
$ kubectl -n agent-platform port-forward svc/agent-platform 18000:8000
$ curl 127.0.0.1:18000/health           → HTTP 200
{"status":"healthy","version":"0.1.0","storage":"postgres","coordination":true,"revert":true,...}
```

### L3 冒烟 ✅
```
$ curl 127.0.0.1:18000/docs             → HTTP 200
$ kubectl exec <ap-pod> -- printenv DATABASE_URL
  postgresql://agent:agent_platform_dev@postgres:5432/agent_platform
$ kubectl exec <ap-pod> -- python -c "import socket;print(socket.gethostbyname('postgres'))"
  postgres -> 10.104.165.121   # 集群内 Service DNS 解析正确
```

### L4 pod 自愈 ✅
删除 ambari01 上的 agent-platform pod → Deployment 自动重建（本次调度到 ambari02）→ Ready。
- **自愈耗时：6.2s**

### L4+ 节点驱逐（三节点招牌）✅
drain 前确认 ambari02 上本集群工作负载仅 agent-platform + coredns（**其他团队的 docker 服务不在本 k8s 集群内，drain 不受影响**）。
```
$ kubectl drain ambari02 --ignore-daemonsets --delete-emptydir-data --force --grace-period=20
node/ambari02 drained
# agent-platform pod 迁移至 ambari01（10.244.2.4）ready=true
$ kubectl uncordon ambari02 → 三节点再次全部 Ready
```
- **迁移耗时：8.4s**

### L5 HPA（可选加分项）✅
- 部署 metrics-server v0.7.1（镜像走 aliyun，加 `--kubelet-insecure-tls` 解决 kubeadm kubelet 自签证书无 IP SAN）：`kubectl top nodes` 正常出数。
- 应用 HPA（min=1 max=3，为演示将 target CPU 设为 1%）+ pod 内 `timeout 110 python -c "while True: pass"` 烧 CPU：
```
t=15s desired=3 replicas=3   ...   MAX_REPLICAS_SEEN=3
agent-platform-...-cq4kn  ambari01
agent-platform-...-n2mrh  ambari02
agent-platform-...-xdc7m  ambari01
```
- **HPA 从 1 副本自动扩到 3（maxReplicas）**，分散于两个 worker。演示后已删测试 HPA、缩回 1 副本，`/health` 复验 200。

## 6. 达标标准核对

- [x] 三节点全部 Ready（L0）
- [x] postgres + agent-platform 以 Deployment+Service 部署，跨节点分布（L1）
- [x] `curl /health` = 200（L2）
- [x] 节点驱逐自愈，drain worker → pod 迁移另一 worker，记录耗时（L4+ = 8.4s，另 L4 = 6.2s）
- [x] 踩坑记录填写（README 末尾 10 条）
- [x] metrics-server + HPA 扩缩容一次（L5，1→3 副本）

## 7. 遗留 / 边界说明（诚实标注）

- **hostPath 存储**：kubeadm 无默认 storageclass，postgres 用 hostPath 固定在 ambari03，数据**不随 pod 重调度迁移**（demo 可接受，生产应换 StorageClass + 拓扑感知调度）。
- **隔离 containerd 为本机变通**：因共用测试机不能动 docker 的共享 containerd 才起第二实例；纯净专用机可直接按 README 步骤 1.3 单实例操作。
- metrics-server 用 `--kubelet-insecure-tls`（demo 简化）；生产应配置 kubelet 服务证书含 IP SAN 或走 requestheader CA。
- 控制面组件冷启动初期 controller-manager 重启 4 次（证书/leader 选举抖动），约 20s 内出现 `No resources found`，属自愈非缺陷。

## 8. 清理（演练结束归还机器时执行，本次暂保留现场）

```bash
kubectl delete namespace agent-platform
# 如需彻底还原：每台 kubeadm reset；删除 containerd-k8s.service 及 /var/lib/containerd-k8s（切勿动 docker 的共享 containerd）
```

---

# 观测链路补证（第二次演练 · 2026-09-29）

> 目标：OTel + Jaeger 端到端取证 + 真实 LLM 调用。**结论：OTel→Jaeger 面 ✅、业务面（真实 LLM）✅、Langfuse 面 ❌（根本性依赖冲突，决策性放弃）、/metrics ❌（agent_server 不提供该端点，任务前提偏差）**。
> 部署源说明：镜像从 126:`/opt/agent-platform` @`031c89a`（api 尚未拆分 query_router 的旧提交）构建，与本仓 HEAD 存在版本差；发现的两个产品 bug 在两侧同步修复（本地 `query_router.py` / 126 旧版 `routes.py` 等价补丁）。

## A. 前置探测 ✅

- dockerhub 从 126 可达（aliyun mirror 无 jaeger 路径，直连 `jaegertracing/all-in-one:latest` 拉取成功）。
- 运行中镜像内确认无 `opentelemetry-sdk`（pip show 为空）→ 观测依赖必须在 Dockerfile 加装。
- 集群无 LLM key（pod 启动日志 `llm=False`，"无 LLM 模式"），后经用户补充魔搭 ModelScope key。

## B. Dockerfile 加装 OTel 依赖 + 重建分发 ✅

- `Dockerfile` L23 增 `".[otel]"` extras（opentelemetry-sdk + exporter-otlp），L17-22 注释登记 Langfuse 不装原因。
- 重建三轮：#1（otel-only）**3m32s**/390MB → #2（otel.py 符号修复后）~6min → #3（span 生命周期修复后）**3m43s**，均 RC=0。
- 分发三轮均成功：`docker save | gzip`（~118M）→ scp 125/241 → 三台 `ctr --address /run/containerd-k8s/containerd.sock -n k8s.io images import`，`IfNotPresent` + 同 tag 覆盖需 `kubectl rollout restart` 生效。
- 镜像内验证：`pip show opentelemetry-sdk` = 1.45.0（构建机 + pod 内双确认）。

## C. 观测基础设施与配置注入 ✅

- **Jaeger**：all-in-one 以 docker 起于 126（`COLLECTOR_OTLP_ENABLED=true`，16686 UI / 4317 gRPC / 4318 OTLP-HTTP），常驻运行。
- **OTel env**：`kubectl set env deploy/agent-platform OTEL_ENABLED=true OTEL_EXPORTER=otlp OTEL_SERVICE_NAME=agent-platform OTEL_ENDPOINT=http://192.168.100.126:4318/v1/traces`（agent_server 读 OTel 官方 env 名的任务假设不成立，实际为 pydantic-settings 字段大写）。
- **LLM 凭据**：`kubectl create secret generic observability-keys --from-literal=LLM_API_KEY=...`（key 未落任何 git 文件），`--from=secret` 注入 + `LLM_BASE_URL=https://api-inference.modelscope.cn/v1`、`LLM_MODEL=deepseek-ai/DeepSeek-V4.1-Flash` → 启动日志 `llm=True`。
- **Langfuse：未部署（决策性放弃）**。根因：`agent_runtime/tracing.py` 的 `from langfuse.callback import CallbackHandler` 是 v2-only API；v2 锁 langchain-core<0.4，与应用栈 `langgraph>=1.2.10,<2`（langchain-core 1.x）不可共存，pip 实测无限回溯。修复需改产品码 `tracing.py` 迁 v3 OTel-based API，超出本次授权范围。用户决策：只做 OTel+Jaeger，Langfuse 如实标注不可用。

## D. 端到端三面验收

| 面 | 结果 | 证据 |
|---|---|---|
| 业务面（真实 LLM） | ✅ | `POST /query`（SSE）事件流完整：`route(search) → evidence → replan×2 → answer → done`；answer 为 DeepSeek-V4.1-Flash 真实推理输出（证据不足时拒绝编造并给出配置建议，非模板拼接），无异常无 500 |
| Jaeger 面 | ✅ | `traceID=d377f513b63f7addb6305c9f33564e3a`（链路首证）→ 最终干净通过轮 `traceID=cd4d9a667d58bda327c78369e773f1ba`；`/api/services` 含 `agent-platform`，span op=`query` |
| Langfuse 面 | ❌ | 未启用（见 C 根因与用户决策） |
| /metrics | ❌ | agent_server 无 `/metrics` 端点（任务假设来自 agent_federation 口径），如实标注 |

### D 过程发现的两个产品 bug（均先报告、获用户授权后修复）

1. **`agent_runtime/otel.py` 符号错误**：`TraceIdRatioBasedSampler` 在 opentelemetry-sdk 全部版本不存在（正确符号 `TraceIdRatioBased`），模块加载 ImportError 被 guard 吞 → OTel opt-in 路径从未真正生效，静默降级 NoOp，且告警文案误导（"SDK not installed"）。修复 2 处 + 注释；用户授权「授权改 otel.py（2行）修复后继续」。
2. **`query_router.py`（旧版 `routes.py`）span 生命周期误用**：对 `start_as_current_span()` 返回的 CM 手动 `__enter__()` 后直接 `set_attribute` —— 真 OTel（api≥1.27）的 `_AgnosticContextManager.__enter__()` 不返回 span → **/query 直接 500**；且 attach/detach 跨 SSE 生成器 asyncio 任务报 `created in a different Context`。此前从未暴露因为 bug 1 导致恒走 NoOp，而 NoOp shim 的 `__getattr__` 恰好兼容此误用。修复：改 `start_span(context=extract_traceparent(...))` + `finally: span.end()`（不挂当前上下文），本地与 126 旧版双同步。
   **勘误（2026-09-29 复盘追加）**：该修复注释中"保留 W3C 父链接"的声称在 agent_server 实际不成立——`agent_core.tracing_propagation.extract/inject_traceparent` 以 `agent_core.tracing.is_tracing_enabled()` 为门，而 agent_server 只调 `agent_runtime.otel.init_otel()`（另一状态机，从不置 `_enabled`）→ extract 恒 None、透传实际断裂（双状态机接线缺陷 R6）。生命周期修复有效、父链接待全局方案 S2 落地后复验。见 `docs/plans/plan-observability-global-remediation-2026-09-29.md`。**R6 复验已于 2026-09-30 闭环，见下方第三次演练节。**

### 测试方法学记录

- `query_router.py` 的 cache_hit 短路在 span 创建前 return，**缓存命中不产生 trace** → 端到端用例必须用带时间戳后缀的唯一 query 绕语义缓存。
- BatchSpanProcessor 默认 ~5s 调度 flush，取证脚本请求后 `sleep 8` 再查 Jaeger API。

---

# 第三次演练：S4+S5 后全局治理复验（R6 闭环 · 2026-09-30）

> 目标：在 `30cbf25`（含 S2 统一 TracingMiddleware + S4/S5 全部内容）上复跑六件套取证链，验收 R6「W3C traceparent 父子同 trace」。**结论：R6 达标 ✅；途中拓出两个只有存量库升级路径才暴露的迁移链真实缺陷（已修+回归用例钉住，详见下）；六件套脚本自身两处缺陷也在实跑中磨出修正——印证「脚本未经实战即未拥有」。**

## A. 同步与构建（GIT_REV 绑定首次实战）

- 本地 `git bundle a5fa903..HEAD` → scp → 126 fetch+checkout：MD5 双端一致（`771a5f61…`），126 HEAD=`30cbf25a046eabb41db992617f173d9125e12048`，脏改动先备份 `/tmp/r6-dirty-*-20260930-1100.patch`。
- `build.sh 30cbf25a…`：rev 门禁通过，镜像 `ab5fe54b6860`，label 回读 + `docker run cat /srv/agent-platform/GIT_REV` 双通道均 = `30cbf25a…`（dirty=no）。
- `distribute.sh`：125/241 两 worker 均导入 `ab5fe54b6860`（脚本经上一轮实测修正：WORKER_USER=root、crictl IMAGE/TAG 分列 grep）。

## B. 存量库迁移链两层缺陷（复验核心价值）

新 pod 基线 stamp/续链在**存量库**（历史演练遗留，无 schema_migrations 记录）上必崩，而全新库路径（本地/CI）永不暴露：

1. **baseline 拒 stamp：V3 八表缺失**。演练早期库未含 awaitable_tasks/budget_*/cost_records/execution_*/episodic_memories/procedural_memories 八表 → `_try_baseline_stamp` 不完整即拒（行为正确）。处置：只读侦察库形态后从 001 L188-312 精确提取纯新表块补建（老表缺口交由 runner 续链 002-010 增量补齐）。
2. **v6 续链崩 UndefinedColumn：sql_* 三表无 workspace_id**。旧基线建 sql_ddl/sql_docs/sql_examples 时无此列、v2 只给 chunks 补、增量链从未补 → v6 复合索引 (tenant_id, workspace_id) 必崩。修复入产品码 `006_tenant_corpus.up.sql`（三表 `ADD COLUMN IF NOT EXISTS workspace_id TEXT NOT NULL DEFAULT ''`，幂等，新库 no-op）+ 回归用例 `test_v6_upgrade_from_legacy_corpus_shape`（commit `30cbf25`）。

修复后 rollout：新 pod `66499c8569-k876q` Running 0 重启，schema_migrations 1..10 全落，容器内 `/srv/agent-platform/GIT_REV` = `30cbf25a…`（运行对象与提交一致，R14 达成）。

## C. 端到端取证（R6 判据）

- OTEL env 历史 set 保留在 deploy spec（`set env --list` 四点齐备）；jaeger 容器常驻复用。
- `portforward.sh start` → /health：`"otel":true,"otel_status":"ACTIVE"`（S2 统一接线后首次集群内 ACTIVE，旧轮为手写局部接线）。
- `e2e_traceparent.sh`：客户端自造 traceparent（parent_span=`0123456789abcdef`）→ /query 200 → sleep 8 → Jaeger 命中，span 数=8。
- **父子同 trace 硬判据（Jaeger API 逐 span 解析）**：服务端两条 `POST /query` span 的 CHILD_OF 引用均 = `0123456789abcdef`（客户端父），全 trace 去重 traceID 仅 1 个，无断链/新 trace → **R6 闭环 ✅**。
- `verify.sh 30cbf25a…`：L0 三节点 Ready / L1 pod+svc / L2 otel_status / GIT_REV 绑定四层全过（本次拓出脚本自身缺陷：nodes 不支持 `--field-selector=status!Ready`，pipefail 下静默中断脚本 → 改 awk 按 STATUS 列判定，随本轮入库）。

## D. Windows skip 用例真实 PG 补盲

`tests/ha/test_migrations_real_pg.py`（含新增 v6 存量库用例）在 Windows 本地 skip，本轮在集群 pod 内（Linux + 真实 pgvector PG）补盲实跑：**4 passed**（含全新库完整 baseline 链 + checksum 篡改拒绕 + 幂等重跑）。环内一次性 pytest（pip --user，pod 重启即失效）；中途两轮失败均为补盲环境搭建问题（pytest.ini 段名写错致 asyncio_mode 未生效），非产品码/用例问题，修正后全绿。

## E. 环境事实登记（第三次演练时点）

- 126 脏改动备份（历史）：`/tmp/r6-dirty-{inventory,backup}-20260930-0947.{txt,patch}`、`/tmp/r6-dirty-backup-20260930-1100.patch`；verify 证据块 `/tmp/r6_verify.log`。**已于 2026-09-30 门面退役收尾时全部清理**：对应改动均已入库（b3c5c97 / e086483），bundle 与备份 patch 无保留价值；清理走 scp+sh 脚本通道逐项删除并独立只读复核，`/tmp` `/root` 两目录 r6 相关残留计数为 0。
- 该时点集群运行对象：镜像 `ab5fe54b6860` @ `30cbf25`，pod 内一次性验证残留（/tmp/r6_dep_check.py、/tmp/ha、pip --user pytest）随 pod 重启自然消失。**当前运行对象已推至镜像 `f37bcdb1ed7a` @ `626ec17`（见下方第四次演练 §A）。**
- 集群 kubeadm reset：**不执行（用户 2026-09-30 确认保留集群）**——三节点全 Ready、业务 pod 正常 Running，仍为可用的端到端复验环境；详见观测方案 §16（含 controller-manager 重启真因：leader-election 续租超时，非持续故障）。

---

# 第四次演练：门面退役后端到端复验（2026-09-30）

> 目标：上轮 R6 闭环验证的是 `30cbf25`（门面仍在）；门面退役（`e086483`）把消费方全部切为 kernel 直调，本地分层回归无法证明「真集群 + Jaeger 链路仍串」。本轮将镜像重建到 `626ec17` 并复跑取证链。**结论：父链贯通 ✅（双 span 属既存而非回归）；同时定性出上一轮只记下现象、未追源头的新缺陷 R19（FastAPI 原生 telemetry 与 kernel 中间件重复埋点）——待决策，本演练未改产品码。**

## A. 同步/构建/分发（全链复跑，零手工）

- bundle `30cbf25..626ec17`（MD5 双端 `b3772d26…`）→ 126 fetch + `checkout -f`：HEAD=`626ec17…`、工作树干净。**同步前核实**：126 仅剩的脏改动 `deploy/k8s/scripts/verify.sh` 与本地已提交版本 `git hash-object` 一致（`d5bf2af2…`），确认无信息损失后才丢弃旧副本（上轮清理的备份类临时文件未再产生）。
- `build.sh 626ec17…`：rev 门禁通过 → 镜像 `f37bcdb1ed7a`，label + 容器内文件双通道回读均 = `626ec17…`（dirty=no）；RC=0。
- `distribute.sh`：125/241 两 worker 均导入 `f37bcdb1ed7a9`；`rollout restart` 后新 pod `5cd47d7c9b-ldhqn` Running 0 重启。
- **退役面进入运行制品的直接证据**：pod 内 `cat /srv/agent-platform/GIT_REV` = `626ec17…`，且 `ls packages/agent-runtime/agent_runtime/ | grep -c otel.py` = **0**（门面确实不在制品里，不是在本地工作树里嘴述）。
- `verify.sh 626ec17…`：L0 三节点 Ready / L1 pod+svc / L2 `/health` = `"otel":true,"otel_status":"ACTIVE"` / GIT_REV 绑定——四层全过，RC=0。（`otel_status` 现在完全出自 kernel 单一状态机，不再经门面，这本身就是退役后的关键回归信号）

## B. R6 父子链硬判据（门面退役后）

- `e2e_traceparent.sh`：/query 200 → sleep 8 → Jaeger 命中，span 数≥ 1，RC=0。
- **逐 span 解析**（本地拉 Jaeger API）：trace `025d51b88e78f37d` 去重 traceID = 1，两条 `POST /query` 的 CHILD_OF 引用均 = 客户端 `0123456789abcdef` → **父链贯通 ✅**。

## C. 新发现 R19：FastAPI 原生 telemetry 与 kernel 中间件重复埋点（待决策）

现象：每条请求产出 **2 个同名 `POST /query` SERVER span 且互为兄弟**（均直接挂客户端父）。逐 span 标签定性到源头：

| span | 属性命名 | 归属 |
|---|---|---|
| `8f0055d3eaa3687b` | 新版 semconv（`http.request.method`/`http.route`/`url.path`/`server.address`） | **FastAPI 0.142 内置 `fastapi/telemetry/`**（镜像内无任何 instrumentation 包，grep 确认名字出自 fastapi 本体） |
| `34a497f382548ea0` | 旧版 semconv（`http.method`/`http.target`） | 我们的 `agent_core.tracing_middleware` |

取证得到的三个硬事实（均非推测）：
1. **非门面退役回归**：按 rollout 时刻分桶对比，旧镜像 `30cbf25`（门面在）的历史 trace `025d50100af8b208` **同样是 2 条**。上轮 §C 当时已写下“两条 `POST /query` span”，但未追问为何是两条——本轮才定性到源头。
2. **框架会自己 `set_tracer_provider`**（`fastapi/telemetry/_runtime.py:162`）并从 `OTEL_*` 标准 env 自配 OTLP exporter——这是 **第二个 provider/状态机入口**，属本方案 R6/R12 反模式在框架层的重现。
3. **业务属性落在 B 的子 span 而非请求 span**：`question_hash`/`question_length`/`request_id`/`thread_id` 全部出现在 `fastapi.endpoint`（B 的子）上，两条请求 span 自身均无业务属性；语义未丢但拓扑错位。
4. **探针淹没**：limit=1500 的窗口内 `GET /health` 占 1496 条，真实 `/query` 仅 8 条——取证须按 operation 精查，否则拉不到目标样本。

处置：**不在本演练内改代码**（AGENTS.md「先方案后编码」+ 影响对外观测拓扑）。已登记为观测方案 §18 R19，并于 2026-09-30 按用户决策转独立 issue **[#23](https://github.com/Light-Towers/agent-platform/issues/23)**（label `bug`，含 4 条已验证事实 + 5 条验收标准）后续单独处理，默认取最小改动方案（工厂内 `telemetry={"tracing": False}` 关原生 + lint 门禁）；候选另两项（改用原生而退役我们的中间件 / 保留双层但去重 + 排除 health 降噪）见 §18 表。

## D. 取证脚本知识修正（本轮踩出，未入库代码只记经验）

- **Jaeger find API（`/api/traces?start=&end=`）的时间单位是微秒，不是毫秒**：传 ms 窗口会落到 1970 → 返回空列表且不报错（本轮两次误判为空结果）；而按 traceID 直查 `/api/traces/<id>` 不受影响。脚本内自检：空结果时换 µs 重试并打印实际单位。
- 多层引号内联命令仍必碎（本轮 `\"query\":` 被吞成 `{query:` 导致 422）——一律走 scp+sh 脚本承载；本轮所有远端取证脚本执行完即删（`rm -f` + `ls | grep -c` 自证为 0，不留下轮清理债）。

## E. 环境收尾（本轮为零残留）

- port-forward 已停（126 `ss -ltn | grep -c :18000` = 0）；集群仍为可用复验环境：三节点 Ready，业务 pod `5cd47d7c9b-ldhqn` Running 0 重启（镜像 `f37bcdb1ed7a` @ `626ec17`），postgres Running。
- 三台远端临时产物清零：本轮产生的 5 项（`/root/build-626ec17.log`、`/root/dist-626ec17.log`、`/tmp/retire_body.txt`、`/tmp/e2e_body.txt`、`/tmp/agent-platform.tar.gz` 119M×3 台）+ **宽口径复核扫出的 19 项历史 ad-hoc 残留**（第一/二次演练的 `_build_*.sh`/`_distrib*.sh`/`_otel_*.sh`/`build*.log`/`distrib*.log`、`ap_dev.tar.gz` 118M、`images.tar.gz` 255M、`evalsync_c/` eval 脚本副本、`e2e_smoke.sh`/`_e2e_otel.sh`）逐项删除。
  - **删除前逐个 `ls -l` 定性**：全部为 `/tmp`（个别 `/root`）下一次性 sh/log/tar，非仓库工作树内容；镜像已导入 containerd、脚本正文已入库 `deploy/k8s/scripts/`，无信息损失。
  - **复核口径教训**：本轮按前缀 tag（`626ec17`）复核得 0，但换**关键词宽口径**（`otel|e2e|distrib|build|tar.gz|evalsync|dirty`）才暴露历史三轮的 19 项残留——清干净的标准应是「目录里无 ad-hoc 文件」而非「无本轮 tag 文件」。
  - 三台最终宽口径计数均 **0**（`/tmp` `/root` `/var/tmp`），磁盘 125 41G→40G / 241 49G→48G。
- 本地 `.codeartsdoer/temp/` 本轮 8 个取证脚本（`retire_e2e_forensics.py`、`_dual_span_ab.py`、`_span_tags.py`、`_jaeger_probe.py`、`_span_forensics{,2,3}.sh`、`_drill4_cleanup.sh`）执行完即删，不形成下轮清理债。

