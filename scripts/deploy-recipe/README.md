# 构建与分发配方（下一个 agent 从这里开始）

> 本目录是**入库的构建知识层**：只含公网源与流程纪律、零内网真值，可安全入库并受门禁保护。
> 内网真值（节点 IP/标签、image tag、checkout 路径）在 gitignored 的 `deploy/k8s/scripts/`，
> 本机保留物理文件。**两者关系**：本目录定"怎么配、怎么跑、坑在哪"；deploy 脚本按本目录取值执行。

## 1. 下载源（唯一真相源 = `build-env.sh`）

- **绝不硬编码 `--build-arg PIP_INDEX_URL=...` 在 deploy 脚本里**——那会覆盖 `build-env.sh`，
  且 deploy 脚本 gitignored、门禁扫不到 ⇒ 新 agent 又踩慢源（2026-11-23 实踩）。
- 构建脚本应 `source scripts/deploy-recipe/build-env.sh`，用 `${PIP_INDEX_URL}` 传 `--build-arg`。
- 3 个 Dockerfile 的默认值与本文件对齐（阿里云 19MB/s，非清华源 50–160kB/s）。
- torch 本体走 `download.pytorch.org`（阿里云无 `+cpu` 版），但**必须**：先从快源预装
  传递依赖（filelock/typing-extensions/sympy/networkx/jinja2/fsspec/markupsafe[/pillow]），
  再 `--no-deps` 拉本体。否则 pip 把依赖也从 pytorch.org 拉（30kB/s + Network unreachable）。
- **P18 门禁**（`scripts/lint_architecture.py`）扫描本目录 + 3 个 Dockerfile：
  出现清华源、或 torch `--index-url` 行缺 `--no-deps` ⇒ CI 红。改源前先看门禁。

## 2. 构建 + 分发

| 镜像 | Dockerfile | 入口 |
|---|---|---|
| `agent-platform:dev`（含 web 产物） | 根 `Dockerfile` | 241 上 `deploy/k8s/scripts/build_with_io_guard.sh <rev> <worker1> <worker2>` |
| `knowledge-service-web:latest`（KS） | `applications/knowledge-service/Dockerfile` | **无标准脚本**，手工 `docker build` + 分发（见 §4） |
| `nl2sql-service:dev` | `Dockerfile.nl2sql-service` | 同 agent-platform 入口 |

- 构建放 **241**（126 的 ROTA=1 单盘上 pip 铺包会把同机 etcd 打进 slow fdatasync）。
- IO 守卫**不得关**；吞吐慢时用 `IO_LIMIT=80 IO_STRIKES=6` 放宽判定，不是关守卫。
- 镜像绑 rev：build.sh 的 rev 门禁 + 镜像内 `/srv/agent-platform/GIT_REV` 双回读。
- A1：每个镜像内 import 探针真过才分发。

## 3. 分发：两套 containerd 库（最容易踩的坑）

**241 moby、`/run/containerd/containerd.sock`、`/run/containerd-k8s/containerd.sock` 三者互不可见。**
k8s kubelet 用 `/run/containerd-k8s/containerd.sock`。手工分发**必须**：

```bash
# 正确（kubelet 能拉到）
ctr --address /run/containerd-k8s/containerd.sock -n k8s.io images import "$TARBALL"
# 错误（镜像进了默认库，crictl 回读仍是旧 ID，但脚本可能报 OK ⇒ 静默跑旧代码）
ctr -n k8s.io images import "$TARBALL"
```

- 标准 `distribute.sh` 已带 `--address`；**手写分发脚本时照抄它，别用裸 ctr**。
- 构建机 241 自己也要 import 一次（distribute 默认只覆盖其余节点）。
- 回读用 `crictl --runtime-endpoint unix:///run/containerd-k8s/containerd.sock images`，
  且按完整 tag 匹配（脚本回读 grep 常先命中 registry 路径的旧 tag，造成假绿）。
- 大 tarball（600MB+）scp 偶发不落盘 ⇒ scp 后 `ls -la` 确认，import 失败先查文件在不在。

## 4. KS 镜像无标准脚本（手工流程）

```bash
cd /opt/agent-platform   # 241 上，checkout 到目标 rev
source scripts/deploy-recipe/build-env.sh
docker build --network=host -f applications/knowledge-service/Dockerfile \
  -t knowledge-service-web:latest .
# A1: docker run --rm knowledge-service-web:latest python -c 'import knowledge_service.main'
docker save knowledge-service-web:latest | gzip > /tmp/ks.tar.gz
# 三台（含 241 自己）按 §3 的 --address 方式 import + crictl 回读
```

建议（待办）：把这段固化成入库脚本 + runbook，避免每个 agent 重写。当前按本节执行。

## 5. rollout：hostPort 死锁

ks-web 单副本 + `nodeSelector` 钉 ambari03 + `hostPort:8000` + `maxSurge:25%` ⇒
新 Pod 抢不到 8000 端口 Pending。解法（已验证）：

```bash
kubectl -n <ns> patch deploy ks-web --type=json -p='[
  {"op":"replace","path":"/spec/strategy/rollingUpdate/maxSurge","value":0},
  {"op":"replace","path":"/spec/strategy/rollingUpdate/maxUnavailable","value":1}]'
kubectl -n <ns> rollout restart deploy/ks-web
kubectl -n <ns> rollout status deploy/ks-web --timeout=300s
# 完成后把 maxSurge/maxUnavailable 恢复 25%/25%
```

## 6. 配置改动姿势

- 用 `kubectl get <obj> -o json` → python 改键 → `kubectl apply -f`（整份，原子）。
- **不要 `kubectl set env`**（会留字面值，造成清单与现网分叉，AGENTS.md 内网 §5）。
- envFrom 挂的 ConfigMap 更新后 Pod 不自动拿到新值 ⇒ 必须 rollout。
- 改前备份到 `/tmp`，含回滚所需原 yaml。

## 7. 完整部署取证

`docs/operations/evidence/2026-11-23-kb-image-e2e-deploy/readings.md`（绑 rev / 镜像 ID / 回读读数）。
