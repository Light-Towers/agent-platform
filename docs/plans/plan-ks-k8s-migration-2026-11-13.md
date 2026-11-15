# Plan · KS（知识库服务）全套迁 k8s

- 日期：2026-11-13
- 范围：把 `knowledge-service` 整套（web + milvus + etcd + minio + mongo + neo4j）从 126 的
  docker moby（docker-compose）迁到 k8s，与 `agent-platform` / `nl2sql-service` 统一编排。
- 状态：Proposed（待用户审批后执行备份 + apply）
- 关联：项 1（Dockerfile 拆层 + 单文件热更 runbook）已落地并提交 `fd9d018f`。

## 1. 决策前提（关键约束）

**本 k8s 集群无任何 StorageClass / PV / CSI provisioner**（`kubectl get sc` →
No resources；无 provisioner pod）。因此 **PVC 动态供给不可用**，原想用 PVC 持久化 stateful
组件在此集群会永远 Pending。

**既定范式**：`deploy/k8s/10-postgres.yaml` 已确立——kubeadm 三节点无默认 storageclass，
改用 **`hostPath` + 钉 node-126**（control-plane 兼任数据节点，`nodeSelector` + `toleration`）。
postgres/valkey/权重缓存(`/opt/ap-models`) 全部如此。

**结论**：KS 全套迁 k8s 采用同一范式——所有组件用 k8s 编排，`hostPath` 持久化，钉 node-126，
**数据原地复用 126 磁盘**（拷贝到 `/data/k8s-demo/knowledge-service/<comp>/` 后由 hostPath 指向）。
这满足"统一用 k8s"且不引入集群级存储变更。

> 权衡：hostPath 钉单节点 = 无跨节点 HA（与当前 docker moby on 126 一致，也与 postgres 现状一致）。
> 若要真 HA 需先装 CSI/local-path（集群级变更，超出本 Plan，单独评估）。

## 2. 当前状态（126 docker moby，调研实测）

| 容器 | 镜像/版本 | 持久化 |
|------|-----------|--------|
| knowledge-service-web | `8fe43ec2877f`（**旧镜像**；G2 构建 `5e5850813e2c` 已打好但**未 up -d**） | bind: `./output ./logs ./models` |
| milvus | milvusdb/milvus:v2.5.10 | `milvus_data:/var/lib/milvus` |
| etcd | quay.io/coreos/etcd:v3.5.18 | `etcd_data:/etcd` |
| minio | minio/minio:RELEASE.2024-01-16T16-07-38Z | `minio_data:/data` |
| mongo | mongo:7 | `mongo_data:/data/db` |
| neo4j | neo4j:5 | `neo4j_data:/data` |

docker 卷实质在 `/var/lib/docker/volumes/knowledge-service_<name>/_data`；web 的 bind 在
`/opt/agent-platform/applications/knowledge-service/{output,logs,models}`。
磁盘 `/` 80%（19G 可用），docker 镜像/构建缓存可回收空间大。

## 3. 目标拓扑

- 命名空间：`agent-platform`（沿用现有）。
- 节点：全部 `nodeSelector: kubernetes.io/hostname: <internal-node-03>`（=<internal-host-126>）+ 对应 toleration。
- 服务发现：为每个组件建 `ClusterIP` Service，名称沿用 compose 里的 `milvus`/`mongo`/`minio`/
  `neo4j`/`etcd`，使 web 的 `MILVUS_URL=http://milvus:19530` 等 env 原样可用。
- 组件编排形态：
  - etcd / mongo / neo4j / milvus / web → `Deployment`（单副本，hostPath 持久化）
  - minio → `Deployment`；`minio-init` 改为 web 的 **initContainer**（幂等建桶 `kb-import-bucket`）
  - 资源 limits 沿用 compose（`deploy.resources.limits` 字面值搬进 `resources.limits`）
- 配置：compose 的 `.env` 拆为 `ConfigMap`（非密）+ `Secret`（密，沿用 `05-secrets.yaml` 风格）。
  **需从 126 的 `.env` 提取**，密字段（MINIO_*/NEO4J_*）进 Secret。
- 探针：沿用 compose 的 healthcheck 命令转写为 k8s `livenessProbe`/`readinessProbe`
  （web `/health/live`；milvus `:9091/healthz`；mongo `mongosh ping`；etcd `etcdctl endpoint health`；
  neo4j `:7474`）。

## 4. 存储映射（hostPath on 126）

目标目录统一放 `/data/k8s-demo/knowledge-service/`（与 postgres 的 `/data/k8s-demo/agent-platform/` 并列）：

| 组件 | hostPath | 原数据来源 |
|------|----------|-----------|
| etcd | `/data/k8s-demo/knowledge-service/etcd` | `knowledge-service_etcd_data/_data` |
| milvus | `/data/k8s-demo/knowledge-service/milvus` | `knowledge-service_milvus_data/_data` |
| minio | `/data/k8s-demo/knowledge-service/minio` | `knowledge-service_minio_data/_data` |
| mongo | `/data/k8s-demo/knowledge-service/mongo` | `knowledge-service_mongo_data/_data` |
| neo4j | `/data/k8s-demo/knowledge-service/neo4j` | `knowledge-service_neo4j_data/_data` |
| web-models | `/data/k8s-demo/knowledge-service/web-models` | `.../knowledge-service/models` |
| web-output | `/data/k8s-demo/knowledge-service/web-output` | `.../knowledge-service/output` |
| web-logs | `/data/k8s-demo/knowledge-service/web-logs` | `.../knowledge-service/logs` |

`hostPath` `type: DirectoryOrCreate`（对齐 postgres）。

## 5. 清单清单（新建于 `deploy/k8s/ks/`，编号 40–49）

- `40-ks-configmap.yaml`：非密 env（服务地址、MQ_TYPE、MINIO_BUCKET_NAME 等）
- `41-ks-secret.yaml`：MINIO_*/NEO4J_* 等密（从 126 `.env` 提取）
- `42-ks-etcd.yaml`：Deployment + Service
- `43-ks-minio.yaml`：Deployment + Service
- `44-ks-mongo.yaml`：Deployment + Service
- `45-ks-neo4j.yaml`：Deployment + Service
- `46-ks-milvus.yaml`：Deployment + Service（依赖 etcd/minio 就绪）
- `47-ks-web.yaml`：Deployment + Service（8000），含 minio-init initContainer、模型/输出/日志 hostPath、探针
- `README-ks.md`：KS 部分部署说明（对齐现有 `deploy/k8s/README.md`）

> 镜像：web 用 `knowledge-service-web:latest`（重建自 `fd9d018f` 后的 Dockerfile + G2 代码）；
> 其余直接用 compose 同版本 tag（etcd v3.5.18 / milvus v2.5.10 / minio RELEASE.2024-01-16 / mongo:7 / neo4j:5）。

## 6. 数据迁移流程（风险点，须审批后执行）

1. **全量备份**（审批后第一步，不动运行服务）：
   对 6 个 docker 卷 + 3 个 web bind 目录做 `tar` 备份到 `/data/k8s-demo/ks-backup-<ts>/`，
   并记录 `docker images` / `docker ps` 快照，作为兜底回滚素材。
2. **停写快照**：依次 `docker stop` 各容器（先 web，再依赖项），保证数据一致性后拷贝。
3. **拷贝数据**到 §4 目标 hostPath 目录（milvus/etcd/mongo/neo4j 直接拷数据目录；
   mongo/neo4j 也可用 `mongodump`/`neo4j-admin dump` 更稳妥——执行时二选一）。
4. **apply 清单**（先 etcd→minio→mongo→neo4j→milvus→web，等各自就绪）。
5. **验证**：web `/health/live`、`/health/ready`；KbUpload 表单出现「数据源类型」下拉；
   确认 milvus 集合 / mongo 集合 / neo4j 图谱数据量与迁移前一致（计数对账）。
6. **下线旧 docker**：验证通过后 `docker rm` 旧容器、`docker volume rm` 旧卷（保留备份目录到确认无碍）。

## 7. 回滚 / 中止

- 任何一步失败：**停止 apply**，旧 docker 容器未 `rm` 前可直接 `docker start` 恢复（数据未被删）。
- 已 `rm` 旧容器：从 §6.1 备份 `tar` 还原 docker 卷 + `docker-compose up -d`，数据回到迁移前。
- hostPath 数据目录在迁移后保留，k8s 与 docker 不共享，互不破坏。

## 8. 风险与缓解

| 风险 | 缓解 |
|------|------|
| hostPath 钉单节点，节点故障即全损 | 与现状一致；真 HA 需另装 CSI（不在本 Plan） |
| 数据拷贝不一致（拷贝时仍在写） | 先 `docker stop` 再拷；mongo/neo4j 用 dump 工具 |
| 镜像语义差异（web 用新构建） | G2 已随 `5e5850813e2c` 验证可构建；apply 后重点验 G2 表单 |
| Secret 漏配导致 web 起不来 | 从 126 `.env` 全量提取，apply 前 diff 必填项 |
| 服务名/DNS 不通 | Service 名严格沿用 compose 服务名 |

## 9. 待确认（执行前需用户给定）

- [ ] 126 上 KS 的 `.env` 路径与内容（提取 ConfigMap/Secret 用）
- [ ] web 是否需 GPU（compose 未声明，默认 CPU；若需则加 `nvidia.com/gpu` 资源 + 节点有 GPU）
- [ ] 备份目的地磁盘余量（19G 可用，备份 milvus/neo4j 可能较大，先 `du` 评估）
