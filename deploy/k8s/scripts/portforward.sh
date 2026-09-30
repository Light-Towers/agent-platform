#!/usr/bin/env bash
# portforward.sh — 固化版 svc port-forward（踩坑表：内联后台 setsid 引号被吞 + 残留占端口，
# 曾致 curl HTTP=000；本脚本先清旧再拉起并自证）。
#
# 用法（在 126 上执行）：
#   bash deploy/k8s/scripts/portforward.sh [start|status|stop]
#
# 成功判据：ss 出现监听行 + curl /health 返回 200 且 JSON 含 otel_status 字段（S2 真状态面）。
# 退出码：0 成功 / 1 拉起或探测失败。
set -euo pipefail

ACTION="${1:-start}"
NAMESPACE="${NAMESPACE:-agent-platform}"
SVC="${SVC:-agent-platform}"
LOCAL_PORT="${LOCAL_PORT:-18000}"
REMOTE_PORT="${REMOTE_PORT:-8000}"
BIND="${BIND:-0.0.0.0}"   # Windows 侧经 NAT 访问须 0.0.0.0（勿留默认 127.0.0.1）

stop_pf() { pkill -f "port-forward svc/$SVC" 2>/dev/null || true; }

case "$ACTION" in
  start)
    stop_pf; sleep 1
    nohup kubectl -n "$NAMESPACE" port-forward "svc/$SVC" "$LOCAL_PORT:$REMOTE_PORT" \
      --address "$BIND" >/tmp/portforward.log 2>&1 &
    disown
    for i in $(seq 1 10); do
      ss -tlnp 2>/dev/null | grep -q ":$LOCAL_PORT " && break
      sleep 1
    done
    ss -tlnp | grep ":$LOCAL_PORT " || { echo "FAIL: 端口 $LOCAL_PORT 未监听（看 /tmp/portforward.log）"; exit 1; }
    HEALTH="$(curl -sf "http://127.0.0.1:$LOCAL_PORT/health")" || { echo "FAIL: /health 不可达"; exit 1; }
    echo "$HEALTH"
    echo "$HEALTH" | grep -q '"otel_status"' || echo "WARN: 响应无 otel_status 字段——镜像可能早于 S2（核对 GIT_REV）"
    echo "OK: port-forward :$LOCAL_PORT 就绪"
    ;;
  status)
    ss -tlnp | grep ":$LOCAL_PORT " && curl -sf "http://127.0.0.1:$LOCAL_PORT/health" || echo "未就绪"
    ;;
  stop)
    stop_pf; echo "OK: port-forward 已停"
    ;;
  *)
    echo "用法: portforward.sh [start|status|stop]"; exit 1;;
esac
