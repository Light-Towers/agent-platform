#!/usr/bin/env bash
# distribute.sh — 镜像导出并导入到全部节点（containerd 隔离实例，命名空间 k8s.io）。
#
# 用法（在 126 上执行；默认分发到两个 worker）：
#   bash deploy/k8s/scripts/distribute.sh
#   bash deploy/k8s/scripts/distribute.sh 192.168.100.125 192.168.100.241
#   WORKER_USER=<ssh_user> IMAGE=<tag> bash deploy/k8s/scripts/distribute.sh
#
# 成功判据：每个 worker 上 crictl images 出现目标镜像行。
# 注意：同 tag 覆盖 + imagePullPolicy=IfNotPresent 时，须另行
#   kubectl -n "$NAMESPACE" rollout restart deploy/agent-platform 才生效（本脚本不代做，防误伤）。
# 退出码：0 成功 / 1 任一节点导入或校验失败。
set -euo pipefail

IMAGE="${IMAGE:-agent-platform:dev}"
WORKERS="${*:-192.168.100.125 192.168.100.241}"
WORKER_USER="${WORKER_USER:-osmondy}"
CTR_SOCK="${CTR_SOCK:-/run/containerd-k8s/containerd.sock}"   # 隔离实例，勿打裸 ctr（踩坑表）
TARBALL="${TARBALL:-/tmp/agent-platform.tar.gz}"

docker save "$IMAGE" | gzip > "$TARBALL"
echo "saved: $(du -h "$TARBALL" | cut -f1)"

for host in $WORKERS; do
  scp -q "$TARBALL" "$WORKER_USER@$host:/tmp/" || { echo "FAIL: scp -> $host"; exit 1; }
  ssh "$WORKER_USER@$host" \
    "sudo ctr --address $CTR_SOCK -n k8s.io images import $TARBALL" \
    || { echo "FAIL: import on $host"; exit 1; }
  ssh "$WORKER_USER@$host" \
    "sudo crictl --runtime-endpoint unix://$CTR_SOCK images | grep -F '$IMAGE'" \
    || { echo "FAIL: image not visible on $host"; exit 1; }
  echo "OK: $host"
done

# 本机（126）也须可导入（postgres 与部分负载跑在 control-plane）
sudo ctr --address "$CTR_SOCK" -n k8s.io images import "$TARBALL" >/dev/null
echo "OK: distribute done for $IMAGE"
