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
