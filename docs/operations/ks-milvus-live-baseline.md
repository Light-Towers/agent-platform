# ks-milvus 现网基线（升级批准依据）

> 用途：ADR-0017 / `docs/plans/plan-milvus-prod-upgrade-2-6-2026-11-26.md` 的"批准依据必入库"。
> 真机清单可在 `deploy/k8s/ks-milvus.yaml`（被 `.gitignore` 忽略，仅本机 apply 用）找到；本文件是**脱敏的可复核基线**，不含可直接使用的内部坐标。

## 1. 取证读数（2026-11-26，只读）

- 来源：`ssh root@<internal-node-126> "kubectl get deploy -n agent-platform ks-milvus -o yaml"`
- live yaml 行数：129
- live yaml sha256：`ccd405357c832289aaeb6b77e18d287cf6145a92ae2a8cd89f2c281c69ccadbe`
- 部署：`Deployment/ks-milvus`，namespace `agent-platform`，`replicas=1`，`imagePullPolicy=IfNotPresent`
- 镜像：container 与 initContainer 均为 `milvusdb/milvus:v2.5.10`
- 命令：`milvus run standalone`
- env：`ETCD_ENDPOINTS=etcd:2379`、`MINIO_ADDRESS=minio:9000`、`MINIO_REGION=us-east-1`、`MINIO_BUCKET_NAME=a-bucket`、`MQ_TYPE=default`
- 调度：`nodeSelector kubernetes.io/hostname=<internal-node-126>`，带 control-plane toleration
- 数据卷：hostPath `<internal-path>/milvus`，取证时 `du -sh` = **246M**
- 探针：`/healthz` on 9091，initialDelay 30s / period 15s / timeout 10s
- 资源：limits `cpu=2.0, memory=4G`；requests `cpu=250m, memory=2G`
- Pod：一个 Running（重启 67 次），一个 `ContainerStatusUnknown`（33 次）——升级前故障基线已差，必须逐项比 `RestartCount / Health / StartedAt`

## 2. 升级动作（相对基线的唯一差异）

1. 两处镜像 `v2.5.10` → `v2.6.3`
2. `MQ_TYPE` `default` → `rocksmq`
   - 理由：2.5 的 `default` = RocksMQ；2.6 的 `default` 会变成 Woodpecker，跨 MQ 切换在升级中不受支持。
   - POC 已验证 2.6.3 接受 `MQ_TYPE=rocksmq`（日志 `mqType=rocksmq`，客户端可连）。
3. 去掉 live 导出的 status / 运行时元数据字段；其余字段逐字保持。

## 3. 复审触发条件

出现任一情形即复审本基线与升级方案，不等事故后再查：

1. live deploy 的 sha256 与上文不一致（说明有人就地改过配置，例如 `kubectl set env`）。
2. 升级窗口内 Pod 出现 CrashLoopBackOff / `ContainerStatusUnknown` 或重启计数继续增长。
3. 旧 v3 集合在 2.6.3 上不可列举 / 不可查询。
4. 决定启用 `RETRIEVAL_ANALYZER_PROFILE=domain_dict_2_6`（与升级同批启用需重新评审，当前方案明确分两步）。
5. `deploy/k8s/` 的忽略规则变化，或本文件从版本控制清单消失。

## 4. 升级准备读数（2026-11-26，已执行且可逆）

- 待 apply 清单：本机 `deploy/k8s/ks-milvus.yaml`（gitignored），相对基线只有两处差异：两处镜像 → v2.6.3、`MQ_TYPE` → `rocksmq`。
- 镜像备份：`/root/backup/milvus-upgrade/milvus-v2.5.10.tar`（1.7G）、`milvus-v2.6.3.tar`（2.6G）。CRI 实测一次只保留一个 milvus tag，故两个 tar 都必须保留。
- CRI 正确 endpoint：`/run/containerd-k8s/containerd.sock`（`/etc/crictl.yaml`）；曾误导入 `/run/containerd/containerd.sock`（moby 运行时），已纠正，该错误读入未影响 Pod。
- hostPath 冷备：`/root/backup/milvus-upgrade/hostpath-20261126.tar.gz`，46M，sha256 `cd26264696808d2e602cb47039b8d315fca613f1f3fbe4931bef75617c47284d`。
- **执行更新（2026-11-26）**：已获明确批准并 apply，rollout 成功；Deployment revision 5，镜像 v2.6.3，`MQ_TYPE=rocksmq`，新 Pod 0 重启，healthz 200，旧 v3 集合 83 行可查询。详见 `docs/plans/plan-milvus-prod-upgrade-2-6-2026-11-26.md` §9。
- apply 前曾因 CRI 单 tag 行为导致 `ErrImagePull`，已从 v2.5.10 tar 恢复服务并重新取证，见 §9.1。
