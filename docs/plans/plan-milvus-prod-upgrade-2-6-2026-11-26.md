# Plan：现网 Milvus 2.5.10 → 2.6.3 升级 / 回退（2026-11-26）

> 状态：**草案，待批准（D2：难逆 + 大影响）**。批准前不改现网任何资源。
> 目标：把 `agent-platform` 命名空间下 `ks-milvus` 从 `milvusdb/milvus:v2.5.10` 升到 `v2.6.3`，为 ADR-0017 的治本形态（引擎侧 jieba 领域词典）提供版本前提；**升级本身不改变检索行为**。

## 1. 现状取证（2026-11-26，只读）

| 项 | 读数 | 取证命令 / 证据 |
|---|---|---|
| 工作负载 | Deployment `ks-milvus`，`replicas=1`，`imagePullPolicy=IfNotPresent` | `kubectl get deploy -n agent-platform ks-milvus -o yaml` |
| 镜像 | `milvusdb/milvus:v2.5.10`（container + initContainer 均为该镜像） | 同上 |
| 命令 | `milvus run standalone` | 同上 |
| 依赖 | 外部 etcd `etcd:2379`、MinIO `minio:9000`，非内嵌 | env `ETCD_ENDPOINTS` / `MINIO_ADDRESS` |
| 依赖版本 | etcd `quay.io/coreos/etcd:v3.5.18`；MinIO `RELEASE.2024-01-16T16-07-38Z` | `kubectl get deploy ks-etcd/ks-minio -o yaml` |
| MQ | `MQ_TYPE=default`（在 2.5 中等价 RocksMQ） | Deployment env；2.6 配置 `mq.type` 默认已改为 Woodpecker |
| 调度 | `nodeSelector kubernetes.io/hostname=ambari03`（126）+ control-plane toleration | 同上 |
| 数据 | hostPath `/data/k8s-demo/knowledge-service/milvus`，`du -sh` = **246M** | `du -sh` on 126 |
| Pod 状态 | `ks-milvus-...qd444` Running，重启 **67 次**（21 分钟前）；另一个副本 `...fj92l` `ContainerStatusUnknown` 33 次 | `kubectl get pods -n agent-platform -o wide` |
| Service | `milvus` ClusterIP `10.111.204.66:19530,9091` | `kubectl get svc -n agent-platform` |
| CRI 镜像 | 126 的 CRI 只有 `milvusdb/milvus:v2.5.10`（1.73GB），**没有 2.6.x**；241 没有 | `crictl images` |
| 清单来源 | 有 `kubectl.kubernetes.io/last-applied-configuration` 注解，但**仓库 `deploy/` 与全仓 `*.yaml` 中找不到 ks-milvus 清单** | `grep -r "name: ks-milvus"` 零命中 |
| 现有集合 | `platform_doc_v3_bge_m3`（由 `applications/agent_server/config.py:105` 引用）与 KS 侧集合共用同一实例 | `config.py:101-105` 注释 |

## 2. 决策与边界

1. **升版本不改行为**：升级后继续 `milvus run standalone`，沿用外部 etcd / MinIO、hostPath、nodeSelector、资源限制；不改 `DOC_BACKEND` 与 `RETRIEVAL_ANALYZER_PROFILE`（默认仍 `simple_2_5`）。
2. **必须锁 MQ**：`MQ_TYPE=default` 在 2.5 = RocksMQ，在 2.6 默认会变成 Woodpecker；跨 MQ 切换在升级中不受支持。**升级时显式改成 `MQ_TYPE=rocksmq`**，POC 已验证 2.6.3 接受该值（日志 `mqType=rocksmq`）。
3. **不升级集群形态**：不做 distributed / multi-replica；单副本 standalone 保持。
4. **治本形态分两步**：先完成引擎升级（本方案），再在独立变更里把 `RETRIEVAL_ANALYZER_PROFILE` 切到 `domain_dict_2_6` 并挂领域词典；不在升级同批做，避免故障归因困难。
5. **D2 审批**：本方案需人批准；执行窗口内 KS / agent_server 会有短暂检索不可用。

## 3. 前置条件（缺一不可）

1. **清单入库**：从 `kubectl get deploy -n agent-platform ks-milvus -o yaml` 导出并脱敏后落到 `deploy/k8s/`，使 `scripts/check_doc_sync.py` 可校验；否则升级后 live 与源不可对账（AGENTS.md「基准同源 / 批准依据必入库」）。
2. **镜像进 CRI**：crictl 的 runtime/image endpoint 是 **`/run/containerd-k8s/containerd.sock`**（见 `/etc/crictl.yaml`），不是 moby 的 `/run/containerd/containerd.sock`。必须用 `ctr --address /run/containerd-k8s/containerd.sock -n k8s.io images import` 导入（`docker save -o` 中转）。2026-11-26 已实测：CRI 一次只保留 `milvusdb/milvus` 的**一个 tag**（导 v2.6.3 后 v2.5.10 消失，反之亦然），因此**两个版本都要留持久 tar**：`/root/backup/milvus-upgrade/milvus-v2.5.10.tar`（1.7G）与 `milvus-v2.6.3.tar`（2.6G），回退时按 tar 重新 import，不依赖外网 registry。
3. **备份**：hostPath 已冷备为 `/root/backup/milvus-upgrade/hostpath-20261126.tar.gz`（46M，sha256 `cd26264696808d2e602cb47039b8d315fca613f1f3fbe4931bef75617c47284d`）；升级前 live deploy yaml sha256 `ccd405357c832289aaeb6b77e18d287cf6145a92ae2a8cd89f2c281c69ccadbe`（见 `docs/operations/ks-milvus-live-baseline.md`）。etcd 与 MinIO bucket 备份仍由运维流程补齐后打勾。
4. **同形态演练**：在 126 上用 2.6.3 起一个**生产同形态** rehearsal（外部 etcd/minio + `MQ_TYPE=rocksmq` + 同 env + 同 hostPath 副本），验：启动无 panic、`/healthz` 200、列出并查询旧 v3 集合、`run_analyzer` 可用。POC 当前只验过内嵌 etcd 形态，不足以替代。
5. **回退前提**：确认 `milvus-v2.5.10.tar` 仍在备份目录，且升级后**未写入 v4 新集合**前才允许镜像级回退；一旦 2.6 写入新数据，回退必须走"备份恢复"而不是改 tag。

## 4. 执行步骤（批准后）

1. 冻结变更窗口，通知 KS / agent_server 调用方可能有短暂 5xx。
2. 修改入库清单：container 与 initContainer 镜像 → `milvusdb/milvus:v2.6.3`；`MQ_TYPE` → `rocksmq`；其他字段逐字保持。
3. `kubectl apply -f deploy/k8s/<ks-milvus>.yaml`；`kubectl rollout status deploy/ks-milvus -n agent-platform --timeout=10m`。
4. 验收：`kubectl get pods` 全 Running 且 RESTARTS 不再增长；`curl http://<clusterIP>:9091/healthz` 200；`list_collections()` 含旧 v3 集合；抽样查询命中与非命中行为与升级前一致。
5. 观察窗口 30 分钟：比 `RestartCount` / `Health` / `StartedAt` 基线；无 `slow fdatasync` 引发的异常退出。
6. 观察通过后，另立变更切 `RETRIEVAL_ANALYZER_PROFILE=domain_dict_2_6`、挂领域词典、建 v4 集合双写；旧集合保留至少 14 个自然日且跨一次完整部署窗口。

## 5. 回退触发与步骤

**触发条件**（任一即回退）：Pod 反复 CrashLoopBackOff / `ContainerStatusUnknown`；`/healthz` 非 200 超过 5 分钟；旧 v3 集合不可查询或报错；Milvus 日志出现 MQ / etcd / MinIO 初始化失败；KS 检索 P95 明显劣化且可归因到引擎升级。

**回退步骤**：

1. 先 `ctr --address /run/containerd-k8s/containerd.sock -n k8s.io images import /root/backup/milvus-upgrade/milvus-v2.5.10.tar` 补回旧镜像（CRI 不保证同时保留两个 tag），再 `kubectl apply -f` 恢复升级前清单（image v2.5.10、`MQ_TYPE=default`）。
2. 若升级后已有 2.6 写入的新数据：先停写入，用升级前备份恢复 hostPath / etcd / MinIO，再回退镜像；**禁止只改 tag 试图向下兼容**。
3. 回退后复跑 §4 验收项，并记录耗时与读数（按 `docs/operations/evidence-format.md` 五字段）。

## 6. 主要风险

- 126 单盘 `ROTA=1` 且常态化 IO stall（AGENTS.md 第七条），镜像 import / 数据备份会放大抖动；避开构建窗口，必要时用 `IO_LIMIT` 守卫口径。
- `imagePullPolicy=IfNotPresent` + 可变 tag：不导 CRI 会静默跑旧代码。
- MQ 从 RocksMQ 误切 Woodpecker 是升级期不支持的操作，必须显式锁 `rocksmq`。
- 升级期间 KS 检索短时不可用；v3 集合数据兼容性需靠 rehearsal 实证，不凭版本号推断。
- 现有 Pod 已 67 次重启，故障基线本身就差，必须区分"升级引入"与"存量抖动"：升级前后逐项比 `RestartCount / Health / StartedAt`。

## 7. 验收判据（四项全绿才算完成）

1. 版本：Deployment 与 CRI 均为 v2.6.3，`crictl images` 与 `kubectl get deploy` 同读数。
2. 可用性：Pod Running、healthz 200、旧 v3 集合可列举可查询。
3. 无回归：KS 抽样查询命中集合与升级前一致；租户 / 工作空间 / 知识库隔离用例全绿。
4. 可回退：回退演练在约定窗口内完成，读数入库；`check_doc_sync.py` rc=0。

## 8. 范围外

不改 dense 模型 / 不改融合权重 / 不引入 ES / 不启用引擎自定义词典（待本升级完成后的独立变更）/ 不动公网镜像分支。
