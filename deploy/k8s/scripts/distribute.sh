#!/usr/bin/env bash
# distribute.sh — 镜像导出并导入到全部节点（containerd 隔离实例，命名空间 k8s.io）。
#
# 用法（在**构建所在的那台**上执行；默认 WORKERS 是"从 126 构建"的历史形态）：
#   bash deploy/k8s/scripts/distribute.sh
#   bash deploy/k8s/scripts/distribute.sh <internal-ip> <internal-ip>
#   WORKER_USER=<ssh_user> bash deploy/k8s/scripts/distribute.sh <internal-ip> <internal-ip>
#   IMAGES="agent-platform:dev" bash deploy/k8s/scripts/distribute.sh <internal-ip> <internal-ip>
#
# ⚠ 换构建机时必须显式传其余全部节点，别用默认值。
#   例：2026-10-13 起构建放在 <internal-host>(241)（避开 126 那块挤着 etcd/milvus/postgres 的
#   ROTA=1 单盘），此时默认列表 `125 241` 会**漏掉 126** —— 部署无 nodeSelector，
#   Pod 一旦调度到 126 就是 ErrImagePull（可变 tag + IfNotPresent，本地没有层可回退）。
#   正确写法：bash deploy/k8s/scripts/distribute.sh <internal-ip> <internal-ip>
#
# 默认导**两个** tag（与 build.sh 同一条源）：只导一个会出现"平台已新、问数服务仍是旧 tag"，
#   而可变 tag + IfNotPresent 下 Pod 拉到旧镜像**不报错** ⇒ 静默跑旧代码（比 ErrImagePull 难查）。
#   旧写法 IMAGE=<tag> 仍生效（单镜像覆盖），文档里的既有配方不因本次改动失效。
#
# 成功判据：每个 worker 上 crictl images 出现**每个**目标镜像行。
# 注意：同 tag 覆盖 + imagePullPolicy=IfNotPresent 时，须另行
#   kubectl -n "$NAMESPACE" rollout restart deploy/<workload> 才生效（本脚本不代做，防误伤）。
# 退出码：0 成功 / 1 任一节点导入或校验失败。
set -euo pipefail

IMAGES="${IMAGE:-${IMAGES:-agent-platform:dev nl2sql-service:dev}}"
WORKERS="${*:-<internal-ip> <internal-ip>}"
WORKER_USER="${WORKER_USER:-root}"   # 126->workers 已配 key 免密（root，实测 BatchMode 通）
CTR_SOCK="${CTR_SOCK:-/run/containerd-k8s/containerd.sock}"   # 隔离实例，勿打裸 ctr（踩坑表）

for IMAGE in $IMAGES; do
  # tarball 路径按 tag 分文件：共用一个路径会让后导的镜像在 scp 阶段覆盖先导的包，
  # 于是"两个 tag 都报 OK"里有一个其实是另一个的层。
  TARBALL="/tmp/${IMAGE%:*}.tar.gz"
  echo "### distribute $IMAGE -> $WORKERS"
  docker save "$IMAGE" | gzip > "$TARBALL"
  echo "saved: $(du -h "$TARBALL" | cut -f1)"

  for host in $WORKERS; do
    scp -q "$TARBALL" "$WORKER_USER@$host:/tmp/" || { echo "FAIL: scp -> $host"; exit 1; }
    ssh "$WORKER_USER@$host" \
      "sudo ctr --address $CTR_SOCK -n k8s.io images import $TARBALL" \
      || { echo "FAIL: import on $host"; exit 1; }
    # crictl 输出 IMAGE/TAG 分列，无 "name:tag" 连串（首版 grep -F '$IMAGE' 误报 FAIL 的根因）
    ssh "$WORKER_USER@$host" \
      "sudo crictl --runtime-endpoint unix://$CTR_SOCK images | grep -E '${IMAGE%:*}[[:space:]]+${IMAGE##*:}'" \
      || { echo "FAIL: image not visible on $host"; exit 1; }
    echo "OK: $host"
  done

  # 本机（构建机）也须导入：宿主 moby 与 k8s 用的 containerd-k8s 是两套库、互不可见。
  # 只 docker build 不补这一笔 = 调度到构建机自己的 Pod 静默跑旧镜像（AGENTS.md 126 §3/§4）。
  sudo ctr --address "$CTR_SOCK" -n k8s.io images import "$TARBALL" >/dev/null
  echo "OK: distribute done for $IMAGE"
done
