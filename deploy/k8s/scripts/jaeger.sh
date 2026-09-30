#!/usr/bin/env bash
# jaeger.sh — 在 126 上幂等拉起 Jaeger all-in-one（docker，OTLP-HTTP 4318 收件）。
#
# 用法（在 126 上执行）：
#   bash deploy/k8s/scripts/jaeger.sh [start|status|stop]
#
# 成功判据：curl 16686 /api/services 返回 200 且含 "services"。
# 说明：aliyun mirror 无 jaeger 路径，直连 dockerhub 拉取（现场实测可达）；
#       BatchSpanProcessor ~5s flush，取证方须 sleep ≥8 再查（e2e 脚本内置）。
# 退出码：0 成功 / 1 启动或健康检查失败。
set -euo pipefail

ACTION="${1:-start}"
JAEGER_IMAGE="${JAEGER_IMAGE:-jaegertracing/all-in-one:latest}"
UI_PORT="${UI_PORT:-16686}"
OTLP_HTTP_PORT="${OTLP_HTTP_PORT:-4318}"

case "$ACTION" in
  start)
    if docker ps --format '{{.Names}}' | grep -qx jaeger; then
      echo "OK: jaeger 已在运行（幂等复用）"
    else
      docker rm -f jaeger >/dev/null 2>&1 || true
      docker run -d --name jaeger --restart unless-stopped \
        -p "$UI_PORT:$UI_PORT" -p 4317:4317 -p "$OTLP_HTTP_PORT:$OTLP_HTTP_PORT" \
        -e COLLECTOR_OTLP_ENABLED=true "$JAEGER_IMAGE" >/dev/null
    fi
    for i in $(seq 1 15); do
      curl -sf "http://127.0.0.1:$UI_PORT/api/services" | grep -q '"services"' && {
        echo "OK: jaeger UI http://$(hostname -I | awk '{print $1}'):$UI_PORT"; exit 0; }
      sleep 2
    done
    echo "FAIL: jaeger /api/services 15 次探测未就绪"; exit 1
    ;;
  status)
    docker ps --filter name=jaeger --format '{{.Names}} {{.Status}}'
    curl -sf "http://127.0.0.1:$UI_PORT/api/services" || { echo "FAIL: UI 不可达"; exit 1; }
    ;;
  stop)
    docker rm -f jaeger >/dev/null && echo "OK: jaeger removed"
    ;;
  *)
    echo "用法: jaeger.sh [start|status|stop]"; exit 1;;
esac
