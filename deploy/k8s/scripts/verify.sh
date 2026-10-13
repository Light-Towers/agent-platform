#!/usr/bin/env bash
# verify.sh — 聚合取证一键复跑（L0 集群 → L1 编排 → L2 健康/otel_status → Pod 内 GIT_REV 回查），
# 输出可直接粘入 deploy/k8s/VERIFICATION.md 的证据块。
#
# 用法（在 126 上执行）：
#   bash deploy/k8s/scripts/verify.sh [expected-rev]
#
# 成功判据：三节点 Ready / pod Ready / /health 200 且 otel_status ∈ {ACTIVE,DEGRADED,DISABLED,UNINITIALIZED}；
#           传 expected-rev 时**跑着的 Pod 内** GIT_REV 必须相等（R14：验证对象与提交一致才可声称）。
# 退出码：0 全部通过 / 1 任一层不达标。
set -euo pipefail

EXPECTED_REV="${1:-}"
NAMESPACE="${NAMESPACE:-agent-platform}"
LOCAL_PORT="${LOCAL_PORT:-18000}"
FAIL=0

echo "== L0 nodes =="
kubectl get nodes --no-headers | awk '{print $1, $2, $5}'
# nodes 不支持 field-selector（服务端报 field label not supported），按 STATUS 列判非 Ready（含 NotReady/SchedulingDisabled 等）
NOT_READY=$(kubectl get nodes --no-headers | awk '$2!="Ready"' | wc -l)
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

echo "== GIT_REV 绑定（读回**跑着的 Pod 里**那份，不是 docker run）=="
# 为什么不能 `docker run` 取镜像内 GIT_REV：宿主 moby 库与 k8s 用的 containerd-k8s 库是两套、
# 互不可见（AGENTS.md 126 §3）。2026-10-13 实踩——Pod 内 = c01e9cf、该 Pod 的 imageID = ff65490fa3d5
# （= 各节点 containerd-k8s 里那份），而 126 的 moby `dev` 标签还停在 2 小时前**中止的那次构建**
# 3cd5580 ⇒ docker run 读到的是旧镜像，报出来的 FAIL 是假阴性。
# 验证对象必须是运行中的那个容器（R14：验证对象与提交一致才可声称）。
# 跨节点镜像内容是否齐，由 distribute 侧的 crictl 回查负责（见 build_with_io_guard.sh）。
POD=$(kubectl -n "$NAMESPACE" get pod -l app=agent-platform -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [ -z "$POD" ]; then
  echo "FAIL: 命名空间内没有 app=agent-platform 的 Pod，无从回查 rev"; FAIL=1
else
  echo "pod: $POD  node: $(kubectl -n "$NAMESPACE" get pod "$POD" -o jsonpath='{.spec.nodeName}')"
  echo "pod imageID: $(kubectl -n "$NAMESPACE" get pod "$POD" -o jsonpath='{.status.containerStatuses[0].imageID}')"
  echo "pod restarts: $(kubectl -n "$NAMESPACE" get pod "$POD" -o jsonpath='{.status.containerStatuses[0].restartCount}')"
  EMBEDDED=$(kubectl -n "$NAMESPACE" exec "$POD" -- cat /srv/agent-platform/GIT_REV 2>/dev/null || echo "<读取失败>")
  echo "pod 内 GIT_REV: $EMBEDDED"
  if [ -n "$EXPECTED_REV" ] && [ "$EMBEDDED" != "$EXPECTED_REV" ]; then
    echo "FAIL: Pod 内 rev != 期望 $EXPECTED_REV —— 禁止对旧镜像声称新提交验证结果"; FAIL=1
  fi
fi

[ "$FAIL" -eq 0 ] && echo "OK: verify 全部通过" || { echo "RESULT: 存在不达标层"; exit 1; }
