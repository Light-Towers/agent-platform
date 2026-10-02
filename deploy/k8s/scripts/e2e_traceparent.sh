#!/usr/bin/env bash
# e2e_traceparent.sh — R6 端到端复验主体：带 traceparent 请求 /query → Jaeger 查父子同 trace。
#
# 用法（在 126 上执行；前置：portforward.sh start + jaeger.sh start + OTEL env 已 set）：
#   bash deploy/k8s/scripts/e2e_traceparent.sh
#   TARGET=http://127.0.0.1:18000 JAEGER=http://127.0.0.1:16686 bash deploy/k8s/scripts/e2e_traceparent.sh
#
# 现场要点（均入踩坑表）：
#   - 唯一 query 带时间戳后缀，绕语义缓存命中短路（cache_hit 路径不建业务 span）；
#   - BatchSpanProcessor ~5s flush → sleep ≥8 再查 Jaeger；
#   - agent_server 读 pydantic-settings 字段大写（OTEL_ENABLED/OTEL_ENDPOINT...），非 OTel 官方 env 名。
# 成功判据：Jaeger /api/traces/<trace_id> 返回该 trace 且 spans 数 ≥1、含 server 端
#           "POST /query" SERVER span（S2 TracingMiddleware 产物，429/409 旁路亦须在）。
# 退出码：0 复验通过 / 1 未落 trace 或断链 / 2 请求本身失败。
set -euo pipefail

TARGET="${TARGET:-http://127.0.0.1:18000}"
JAEGER="${JAEGER:-http://127.0.0.1:16686}"
PARENT_SPAN="0123456789abcdef"
TS="$(date +%s)"
TRACE_ID="$(printf '%032x' $((0x5abcdef * TS)))"           # 每次运行唯一 trace id

CODE=$(curl -s -o /tmp/e2e_body.txt -w '%{http_code}' -X POST "$TARGET/query" \
  -H "Content-Type: application/json" \
  -H "traceparent: 00-$TRACE_ID-$PARENT_SPAN-01" \
  -d "{\"query\": \"e2e取证-$TS 展馆开放时间\", \"thread_id\": \"e2e-$TS\"}")
if [ "$CODE" != "200" ]; then
  echo "FAIL: POST /query HTTP=$CODE body(head)=$(head -c 300 /tmp/e2e_body.txt)"; exit 2
fi
echo "OK: /query 200，trace_id=$TRACE_ID，等 flush..."
sleep 8

SPANS=$(curl -sf "$JAEGER/api/traces/$TRACE_ID" | grep -o '"spanID"' | wc -l)
if [ "${SPANS:-0}" -lt 1 ]; then
  echo "FAIL: Jaeger 无 trace_id=$TRACE_ID 的 span（检查 OTEL_ENABLED/OTEL_ENDPOINT、GIT_REV 是否含 S2）"
  exit 1
fi
curl -sf "$JAEGER/api/traces/$TRACE_ID" | grep -o '"operationName": *"[^"]*"' | sort -u
echo "OK: trace 落 Jaeger，span 数=$SPANS（UI: $JAEGER/trace/$TRACE_ID）"
