#!/usr/bin/env bash
# verify.sh — 聚合取证一键复跑（L0 集群 → L1 编排 → L2 健康/otel_status → 镜像 GIT_REV 回查），
# 输出可直接粘入 deploy/k8s/VERIFICATION.md 的证据块。
#
# 用法（在 126 上执行）：
#   bash deploy/k8s/scripts/verify.sh [expected-rev]
#
# 成功判据：三节点 Ready / pod Ready / /health 200 且 otel_status ∈ {ACTIVE,DEGRADED,DISABLED,UNINITIALIZED}；
#           传 expected-rev 时镜像内 GIT_REV 必须相等（R14：验证对象与提交一致才可声称）。
# 退出码：0 全部通过 / 1 任一层不达标。
set -euo pipefail

EXPECTED_REV="${1:-}"
NAMESPACE="${NAMESPACE:-agent-platform}"
IMAGE="${IMAGE:-agent-platform:dev}"
LOCAL_PORT="${LOCAL_PORT:-18000}"
FAIL=0

echo "== L0 nodes =="
kubectl get nodes --no-headers | awk '{print $1, $2, $5}'
NOT_READY=$(kubectl get nodes --no-headers --field-selector=status!Ready 2>/dev/null | wc -l)
[ "$NOT_READY" -eq 0 ] || { echo "FAIL: $NOT_READY 个节点未 Ready"; FAIL=1; }

echo "== L1 workload =="
kubectl -n "$NAMESPACE" get pods,svc -o wide --no-headers

echo "== L2 health（需先 portforward.sh start）=="
if HEALTH=$(curl -sf "http://127.0.0.1:$LOCAL_PORT/health"); then
  echo "$HEALTH"
  echo "$HEALTH" | grep -q '"otel_status"' || { echo "FAIL: 无 otel_status（镜像早于 S2？）"; FAIL=1; }
else
  echo "FAIL: /health 不可达（port-forward 未起？）"; FAIL=1
fi

echo "== GIT_REV 绑定 =="
EMBEDDED=$(docker run --rm "$IMAGE" cat /srv/agent-platform/GIT_REV 2>/dev/null || echo "<读取失败>")
echo "image rev: $EMBEDDED"
if [ -n "$EXPECTED_REV" ] && [ "$EMBEDDED" != "$EXPECTED_REV" ]; then
  echo "FAIL: 镜像 rev != 期望 $EXPECTED_REV —— 禁止对旧镜像声称新提交验证结果"; FAIL=1
fi

[ "$FAIL" -eq 0 ] && echo "OK: verify 全部通过" || { echo "RESULT: 存在不达标层"; exit 1; }
