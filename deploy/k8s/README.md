# K8s 最小部署证据（kubeadm 三节点集群，内网 Ubuntu 测试机）

> 目标：为「Kubernetes」简历词补真实证据——**kubeadm 搭建 1 control-plane + 2 worker 三节点集群**，
> 部署 agent-platform（API + pgvector），完成分层验证并归档证据。
> 证据级别说明：三节点真集群 > minikube 单节点——面试可讲"搭建过多节点集群（etcd/apiserver/调度/网络插件）"，
> 而非只"本地单机跑过"。预计 2-3 晚（容器化已完成，本目录只补编排层）。

## 机器与角色（2026-09-29 用户确认）

| 机器 | IP | 角色 | 备注 |
|---|---|---|---|
| 测试机 1 | 192.168.100.126 | **control-plane**（兼数据节点，跑 postgres） | 主操作机，kubectl 在此 |
| 测试机 2 | 192.168.100.125 | worker | 跑 agent-platform |
| 测试机 3 | 192.168.100.241 | worker | 备用/驱逐目标 |

> 节点 hostname 以 `hostnamectl` 实际为准；实测为 **ambari03(126) / ambari02(125) / ambari01(241)**。
> `10-postgres.yaml` 的 `nodeSelector.kubernetes.io/hostname` 原为 `node-126` 占位，**已改为真实值 `ambari03`**（见末尾踩坑表）。

## 达标标准（全部勾上才算证据成立）

- [x] 三节点集群：`kubectl get nodes` 三个节点全部 Ready（ambari01/02/03 全 Ready，v1.31.14）
- [x] postgres(pgvector) + agent-platform 以 Deployment + Service 部署，`kubectl get pods -o wide` 确认分布（postgres→ambari03，agent-platform→worker 跨节点）
- [x] `curl /health` 返回 200（port-forward，`{"status":"healthy","storage":"postgres"}`）
- [x] **节点驱逐自愈（三节点招牌测试）**：drain ambari02 → agent-platform pod 迁移到 ambari01 → **迁移耗时 8.4s**（另 L4 pod 自愈 6.2s）
- [x] 部署过程踩坑记录填写在本文档末尾
- [x] （加分项，可选）metrics-server + HPA 扩缩容一次（HPA CPU 负载下 1→3 副本，见 VERIFICATION.md L5）

## 步骤

### 0. 前置探测（每台机器都跑，结果记入 VERIFICATION.md）

```bash
lsb_release -a          # Ubuntu 版本（20.04/22.04/24.04）
uname -m                # x86_64 / aarch64（影响镜像架构选择）
free -h && df -h /      # 内存 ≥2G、磁盘 ≥20G
swapon --show           # 若有 swap → 步骤 1 关闭
curl -sI https://registry.cn-hangzhou.aliyuncs.com --max-time 5   # 外网/内网源连通性
```

⚠️ **纪律**：三台是共用测试机——若机器上有他人服务（`docker ps`、`systemctl list-units --type=service` 粗查），
先与使用者确认可安装系统组件（containerd、kubelet、关 swap）再动手。

### 1. 系统准备（三台都要，需 sudo）

```bash
# 1.1 关 swap（kubelet 硬要求）
sudo swapoff -a && sudo sed -i '/swap/s/^/#/' /etc/fstab

# 1.2 内核模块与网络参数
sudo modprobe overlay br_netfilter
cat <<EOF | sudo tee /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1
EOF
sudo sysctl --system

# 1.3 containerd（Ubuntu 源即可）
sudo apt-get update && sudo apt-get install -y containerd
sudo mkdir -p /etc/containerd
containerd config default | sudo tee /etc/containerd/config.toml
# ★ 经典坑：必须把 SystemdCgroup 改为 true，否则 kubelet 起不来
sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
sudo systemctl restart containerd && sudo systemctl enable containerd

# 1.4 kubelet/kubeadm/kubectl（国内走阿里源；能出外网可换官方源）
sudo apt-get install -y apt-transport-https ca-certificates curl gpg
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.31/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.31/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list
sudo apt-get update && sudo apt-get install -y kubelet kubeadm kubectl
sudo apt-mark hold kubelet kubeadm kubectl   # 防止 apt upgrade 擅自升级
```

### 2. 初始化 control-plane（仅 126）

```bash
# 国内拉不到 k8s 官方镜像时用阿里源
sudo kubeadm init \
  --image-repository registry.aliyuncs.com/google_containers \
  --pod-network-cidr=10.244.0.0/16 \
  --apiserver-advertise-address=192.168.100.126

mkdir -p $HOME/.kube
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config && sudo chown $(id -u):$(id -g) $HOME/.kube/config
kubectl get nodes   # 126 应为 NotReady（还没装 CNI），记下 join 命令
```

### 3. worker 加入（125 / 241）

```bash
# 用 init 输出的 join 命令（含 token/hash），token 24h 过期，过期用 kubeadm token create --print-join-command 重生成
sudo kubeadm join 192.168.100.126:6443 --token <token> --discovery-token-ca-cert-hash sha256:<hash>
```

### 4. CNI 网络（仅 126 执行 apply）

```bash
# flannel（pod-cidr 10.244.0.0/16 与 init 参数一致）
kubectl apply -f https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml
kubectl get nodes -w   # 三节点全部 Ready 即过；拉不到 quay 镜像见踩坑表
```

### 5. 应用镜像分发（关键：集群用 containerd，不是 docker）

```bash
# 5.1 在 126 上构建 agent-platform 镜像（126 需装 docker；仓库根目录执行）
docker build -t agent-platform:dev .

# 5.2 导出并分发到两个 worker（containerd 命名空间必须 k8s.io）
docker save agent-platform:dev | gzip > /tmp/agent-platform.tar.gz
scp /tmp/agent-platform.tar.gz user@192.168.100.125:/tmp/
scp /tmp/agent-platform.tar.gz user@192.168.100.241:/tmp/

# 5.3 在 125/241 上分别导入（pgvector 等公共镜像同理，若节点拉不动 docker hub）
sudo ctr -n k8s.io images import /tmp/agent-platform.tar.gz
sudo crictl images | grep agent-platform   # 确认导入成功
```

### 6. 部署（顺序：config → postgres → agent-platform）

```bash
kubectl apply -f deploy/k8s/00-config.yaml
kubectl apply -f deploy/k8s/10-postgres.yaml
kubectl apply -f deploy/k8s/20-agent-platform.yaml
kubectl -n agent-platform get pods -o wide -w
```

预期：postgres（在 126）先 Ready；agent-platform（125/241）走 startupProbe 40s 窗口后 Ready。

### 7. 分层验收（每层输出记入 VERIFICATION.md）

| 层 | 命令 | 判定 |
|---|---|---|
| L0 集群 | `kubectl get nodes` | 三节点全部 Ready |
| L1 编排 | `kubectl -n agent-platform get pods,svc -o wide` + `describe pod` | 全 Ready/Bound，探针事件存在 |
| L2 健康 | `kubectl -n agent-platform port-forward svc/agent-platform 18000:8000` → `curl 127.0.0.1:18000/health` | 200 |
| L3 冒烟 | `curl 127.0.0.1:18000/docs`；`kubectl exec` 确认容器内 `DATABASE_URL` 指向集群内 pg | 双通过 |
| L4 **pod 自愈** | 删除 agent-platform pod → 自动拉起 → 记录耗时 | 闭环 |
| L4+ **节点驱逐** | `kubectl drain <worker> --ignore-daemonsets --delete-emptydir-data` → pod 迁移到另一 worker → `kubectl uncordon` | **记录迁移耗时（三节点招牌证据）** |
| L5 HPA（可选） | metrics-server manifests → 取消 20-agent-platform.yaml HPA 注释 → `get hpa -w` | 有反应 |

### 8. 清理（演练结束，机器要还给别人时）

```bash
kubectl delete namespace agent-platform
sudo kubeadm reset   # 每台；worker 侧另有 reset 提示按提示执行
```

## 备选：k3s 单命令组网（kubeadm 卡住超过一晚时的降级路径）

```bash
# 126（server）：curl -sfL https://rancher-mirror.rancher.cn/k3s/k3s-install.sh | INSTALL_K3S_MIRROR=cn sh -
# 125/241（agent）：用 server 生成的 node-token join
# 差异：k3s 自带 local-path storageclass 与 Traefik，步骤 1/4 可整段跳过；证据口径降为「轻量发行版多节点」
```

## 踩坑记录（部署时填写）

| 问题 | 现象 | 原因 | 解决 |
|---|---|---|---|
| 共用测试机 containerd 冲突 | 三台已装 containerd 2.2.1 且与 docker 共用；README 步骤 1.3 覆盖 config + restart 会打断他人容器 | 生产共用机不能重启别人依赖的共享 containerd | 起**独立第二实例** `containerd-k8s.service`（root=`/var/lib/containerd-k8s`、sock=`/run/containerd-k8s/containerd.sock`、SystemdCgroup=true），kubelet/crictl 指向该 sock，docker 侧零改动（实测 126 的 8 个他人容器不受影响） |
| nodeSelector 占位 hostname 无效 | postgres 无法按预期固定到 126 | `10-postgres.yaml` 写死 `node-126` 占位，真实 hostname 是 `ambari03` | 改为 `kubernetes.io/hostname: ambari03`（`kubectl get nodes` 实测），postgres 落 ambari03 |
| kubeadm init preflight 失败 | `[ERROR FileExisting-conntrack]` init 中止 | Ubuntu 默认未装 conntrack 用户态工具 | `apt-get install -y conntrack`（三台），重跑 init RC=0 |
| registry.k8s.io 镜像拉取超时 | pause/sandbox 起不来 | 国内访问 k8s 官方 CDN 307 跳转后被阻塞 | 全部镜像走 aliyun `registry.aliyuncs.com/google_containers`，containerd sandbox 镜像改 aliyun `pause:3.10.1`（2.2s 拉到） |
| flannel pod CrashLoopBackOff | 节点 NotReady，flannel 反复重启 | `br_netfilter` 内核模块未加载（`lsmod` 为 0），`/proc/sys/net/bridge/bridge-nf-call-iptables` 不存在 | `modprobe br_netfilter overlay` + 持久化，删 flannel pod 重拉 → 三节点 Ready |
| 镜像 import 到错误的 containerd | worker pod 曾 ImagePullBackOff | 隔离实例下裸 `ctr -n k8s.io`（README 步骤 5.3）打到的是 docker 的共享 containerd | `ctr --address /run/containerd-k8s/containerd.sock -n k8s.io images import`，`crictl --runtime-endpoint` 同样指 k8s sock 验证 |
| kubeadm 集群无默认 storageclass | postgres PVC 永远 Pending | kubeadm 不像 minikube/k3s 自带 provider storageclass | 10-postgres.yaml 改用 hostPath `/data/k8s-demo/agent-platform/pgdata`（demo 可接受，数据不随 pod 重调度迁移） |
| apt-get update 因无关第三方坏源报错 | 系统准备脚本 `set -e` 意外中止 | nodesource（focal 与 22.04 版本不匹配）/ gitlab-runner（GPG key 过期）两类无关源 404/GPG fail | k8s 源本身正常，update 用 `... \|\| true` 容忍坏源，仅 `apt-mark hold` k8s 组件 |
| metrics-server 无指标 / HPA targets unknown | `kubectl top` 报 `x509: ... doesn't contain any IP SANs` | kubeadm kubelet 自签服务证书不含节点 IP SAN | metrics-server 部署加 `--kubelet-insecure-tls`，`kubectl top nodes` 随即出数、HPA 正常扩缩 |
| control-plane 组件冷启动重启 | 部署初期 ReplicaSet 短暂不创建（约 20s 内 `No resources found`） | `kube-controller-manager` 启动初期证书/leader 选举抖动，重启 4 次后稳定 | 自愈，非缺陷；稳定后 deployment `Available=True`，pod 正常拉起 |
| Langfuse 与应用栈根本性依赖冲突（观测二轮） | Dockerfile 加 langfuse 后 pip 无限回溯装不上 | `tracing.py` 用 v2-only `langfuse.callback`；v2 锁 langchain-core<0.4 与 `langgraph>=1.2.10`（core 1.x）不可共存 | 决策性放弃 Langfuse 面（用户确认），如实标注不可用；根治需迁 v3 OTel-based API（产品码改动，另行立项） |
| OTel 符号潜伏 bug 致静默降级 | 设了 OTEL_ENABLED 但 Jaeger 0 trace，告警文案"SDK not installed"与实际 pip show 1.45.0 矛盾 | `otel.py` import 了不存在的 `TraceIdRatioBasedSampler`（正确符号 `TraceIdRatioBased`），ImportError 被 try guard 吞成 NoOp | pod 内逐条 import 测试定位；改 `TraceIdRatioBased` 2 处（用户授权）；教训：可选依赖 guard 的告警文案必须区分"未安装"与"安装但导入失败" |
| 真 OTel 下 /query 直接 500（观测二轮） | SSE 无任何事件、日志 `AttributeError: '_AgnosticContextManager' object has no attribute 'set_attribute'` + `created in a different Context` | 对 `start_as_current_span()` 返回的 CM 手动 `__enter__()` 后当 span 用（真 OTel api≥1.27 不返回 span）；attach/detach 跨 SSE 生成器 asyncio 任务不安全；NoOp shim 的 `__getattr__` 兼容掩盖了问题，因 bug 链 1 从未暴露 | 改 `start_span(context=extract_traceparent(...))` + `finally: span.end()`（不挂当前上下文，保留 W3C 父链接）；本地 query_router.py 与 126 旧版 routes.py 同步修 |
| cache_hit 不产生 trace | 修复后重跑同文本请求 Jaeger 仍 0 trace | 语义缓存命中在 span 创建前短路 return | 端到端用例用带时间戳后缀的唯一 query 绕缓存；另：取证脚本需 sleep ≥8s 等 BatchSpanProcessor flush |
| 126 仓库与本地 HEAD 版本漂移 | 本地 routes.py 仅 24 行，镜像内 routes.py 却 426 行报错 | `/opt/agent-platform` 停在旧提交 `031c89a`（api 未拆分），镜像从旧源构建 | 修产品码前先 `ssh grep` 远端实际文件核实形态；补丁用 python 精确替换（未命中即退出）+ `ast.parse` 语法自检 |
| PowerShell/sandbox 长命令回显风暴且 scp 未落地 | 合并多条 scp+ssh 时终端被 base64 EncodedCommand 回显淹没，后续发现远端文件还是旧版 | sandbox 包装层对长复合命令处理异常 | 拆逐条短命令；每次同步后远端 `grep`/`md5sum` 验证落地；.sh 脚本先 `sed -i 's/\r$//'` 去 CRLF 再 bash 执行 |
| port-forward 内联后台起不来 | 进程存活但 curl HTTP=000，随后退出 | setsid 内联命令的 `--address 0.0.0.0` 被引号层吞掉；残留旧 pf 占端口 | 固化为脚本（pkill 旧 pf + nohup + disown + ss 验证 + health 探测）一次拉起 |
| 双 tracing 状态机致 traceparent 透传断裂（复盘新发现，未修） | agent_server 设好 OTel 且 span 能出，但联邦→子服务链路 trace 无法串联 | `agent_core.tracing_propagation` 的 extract/inject 以 `agent_core.tracing.is_tracing_enabled()` 为门；agent_server 只调 `agent_runtime.otel.init_otel()`（另一套状态机）→ extract 恒 None，透传静默失效 | 待全局方案：`docs/plans/plan-observability-global-remediation-2026-09-29.md`（R6，S1 收敛单状态机 + S2 middleware 装配后复验） |

## 可复跑取证（deploy/k8s/scripts/ 六件套，观测方案 §3.5 固化）

> 本轮演练 16 个 scratch `_*.sh` 的等价固化版：每个脚本头部自带用法/成功判据/退出码语义，
> 全部设计为 **在 126 上 bash 执行**（幂等可重入）。Windows 侧只负责分发与结果回收
> （守则见 `docs/operations/testing-playbook.md` 远程演练节）。
> 经 git checkout 的分发天然 LF（`.gitattributes` 已强制 `*.sh eol=lf`）；用 scp 直传工作区文件时若含 CRLF，先 `sed -i 's/\r$//' *.sh`。

| 脚本 | 作用 | 成功判据 | 关键退出码 |
|---|---|---|---|
| `build.sh <expected-rev>` | 126 构建 + **GIT_REV 绑定** | 构建源 HEAD==期望 rev；镜像内 `/srv/agent-platform/GIT_REV` 回读相等 | 2=rev 不匹配（禁止旧源构建，假同步事故根治） |
| `distribute.sh` | `docker save\|gzip` → scp 125/241 → 隔离 containerd 导入 | 每节点 `crictl images` 出现目标镜像行 | 1=某节点 scp/import/校验失败 |
| `jaeger.sh [start\|status\|stop]` | 126 幂等拉起 all-in-one（4318 OTLP-HTTP） | `/api/services` 返回含 "services" | 1=15 次探测未就绪 |
| `portforward.sh [start\|status\|stop]` | 固化版 port-forward（先清旧再拉起） | `ss` 监听行 + `/health` 200 且含 `otel_status` | 1=未监听或 /health 不可达 |
| `e2e_traceparent.sh` | **R6 端到端复验主体**：带 traceparent POST /query（唯一 query 绕缓存）→ sleep 8 → Jaeger 查同 trace | Jaeger 返回该 trace_id 且 span 数 ≥1 | 1=未落 trace；2=请求非 200 |
| `verify.sh [expected-rev]` | L0/L1/L2 聚合取证一键复跑 | 三节点 Ready + otel_status 存在 + rev 一致 | 1=任一层不达标 |

典型复跑序列（新提交 `<rev>` 的全链路取证）：

```bash
# 0. 同步 126 构建源（固定动作，禁止手改远端文件）
ssh 126 "git -C /opt/agent-platform fetch && git -C /opt/agent-platform checkout <rev>"
# 1-2. 构建 + 分发（rev 门禁不过即中止）
bash deploy/k8s/scripts/build.sh <rev> && bash deploy/k8s/scripts/distribute.sh
kubectl -n agent-platform rollout restart deploy/agent-platform && kubectl -n agent-platform rollout status deploy/agent-platform
# 3-5. 观测面拉起 + R6 复验 + 聚合取证
bash deploy/k8s/scripts/jaeger.sh start && bash deploy/k8s/scripts/portforward.sh start
bash deploy/k8s/scripts/e2e_traceparent.sh && bash deploy/k8s/scripts/verify.sh <rev>
```

> OTel env（一次性，已现场生效）：`kubectl set env deploy/agent-platform OTEL_ENABLED=true OTEL_EXPORTER=otlp OTEL_SERVICE_NAME=agent-platform OTEL_ENDPOINT=http://192.168.100.126:4318/v1/traces`
> （agent_server 读 pydantic-settings 字段大写，非 OTel 官方 env 名——见踩坑表）。

## 完成后

通知 AI 执行三件事：① `master.md:788` 待补项升级为已证（附 VERIFICATION.md 路径）；② `versions/ai-platform-v3.md` 工程化行加 `Kubernetes`；③ 证据锚登记「kubeadm 三节点集群最小实操」口径（比原计划 minikube 证据级别更高，面试话术同步升级）。
