#!/usr/bin/env bash
# langfuse.sh — 在 126 上按需拉起/停止 Langfuse 观测栈（非常驻：取证完即 stop）。
#
# 用法（在 126 上执行；Windows 侧先 scp 本目录并去 CRLF）：
#   bash deploy/observability/langfuse.sh start --env-file /root/langfuse-obs.env
#   bash deploy/observability/langfuse.sh status
#   bash deploy/observability/langfuse.sh stop          # 停容器，保留卷
#   bash deploy/observability/langfuse.sh down          # 停容器并删卷（销毁观测数据，需确认）
#
# 成功判据（start）：/api/public/health 返回 200，且**项目凭据可用**（用 Basic 认证打
#   /api/public/projects，200 才算无头初始化真把 org/project/key 建出来了）。
#   配置写了 ≠ 接上了：本脚本的两道判据都必须读到，不看 docker ps 的"Up"。
# 退出码：0 成功 / 1 未就绪 / 2 缺 env 文件 / 3 凭据未被接受（初始化没生效）
set -euo pipefail

ACTION="${1:-status}"; shift || true
ENV_FILE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --env-file) ENV_FILE="${2:?--env-file 需要一个路径}"; shift 2;;
    *) echo "未知参数: $1"; exit 2;;
  esac
done

COMPOSE_FILE="$(dirname "$0")/docker-compose.langfuse.yml"
# 126 上没有 `docker compose` v2 **插件**（实测：docker: unknown command: docker compose），
# 但 /usr/local/bin/docker-compose 是 **Compose v2.40.2 独立二进制**（不是 v1）⇒ 用本文件名即可，
# 别照别的机器改成 `docker compose`，那在这台机上直接 unknown command。
DC="${DC:-docker-compose}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:3000/api/public/health}"

need_env() {
  [ -n "$ENV_FILE" ] && [ -f "$ENV_FILE" ] || { echo "FAIL: 需要 --env-file（值不落仓库，见 langfuse.env.example）"; exit 2; }
  local mode; mode="$(stat -c '%a' "$ENV_FILE")"
  [ "$mode" = "600" ] || [ "$mode" = "400" ] || echo "WARN: $ENV_FILE 权限为 $mode，期望 600（世界可读等于对全主机泄露）"
}

case "$ACTION" in
  start)
    need_env
    "$DC" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --no-build
    echo "--- 等待 /api/public/health ---"
    # 冷启动要先跑完 450 条 Prisma 迁移 + ClickHouse 迁移，60×3s=180s 实测不够 ⇒ 放宽到 300s。
    # 判据不变：读不到 200 就是没起来，不看 docker ps 的 Up。
    for i in $(seq 1 100); do
      code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$HEALTH_URL" || true)"
      [ "$code" = "200" ] && { echo "OK: langfuse web 就绪（第 ${i} 次探测）"; break; }
      # web 若在 Restarting，日志里的迁移错误才是真信号，别干等
      if [ "$((i % 10))" = "0" ]; then
        st="$(docker inspect -f '{{.State.Status}} {{.RestartCount}}' lf-langfuse 2>/dev/null || echo n/a)"
        echo "  [${i}] health=$code  web=${st}"
      fi
      sleep 3
      [ "$i" = "100" ] && { echo "FAIL: 300s 内 $HEALTH_URL 未返回 200（当前=$code）"
        echo "      最后一屏 web 日志："; docker logs --tail 15 lf-langfuse 2>&1 | tail -15; exit 1; }
    done
    # 第二道判据：无头初始化出来的项目凭据必须真能用（Basic 认证）。
    # 值只从 env 文件读进 shell 变量，不进 argv（ps aux 全主机可见）。
    PK="$(grep -E '^LANGFUSE_INIT_PROJECT_PUBLIC_KEY=' "$ENV_FILE" | cut -d= -f2-)"
    SK="$(grep -E '^LANGFUSE_INIT_PROJECT_SECRET_KEY=' "$ENV_FILE" | cut -d= -f2-)"
    [ -n "$PK" ] && [ -n "$SK" ] || { echo "FAIL: env 文件缺项目键"; exit 3; }
    auth="$(printf '%s:%s' "$PK" "$SK" | base64 -w0)"
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 \
            -H "Authorization: Basic $auth" "${HEALTH_URL%/health}/projects" || true)"
    if [ "$code" != "200" ]; then
      echo "FAIL: 项目凭据打 /api/public/projects 返回 $code（期望 200）"
      echo "      ⇒ 无头初始化没生效，或键格式不对；此时应用侧配了 env 也只会静默不报"
      exit 3
    fi
    echo "OK: 项目凭据可用（public key 前缀 ${PK:0:9}…，长度 ${#PK}；secret 长度 ${#SK}）"
    echo "    UI: ${LANGFUSE_NEXTAUTH_URL:-http://<实例IP>:3000}（登录邮箱见 env 文件）"
    ;;
  status)
    "$DC" -f "$COMPOSE_FILE" ps 2>/dev/null | tail -n +1
    echo "--- health ---"; curl -s --max-time 5 "$HEALTH_URL" || echo "不可达"
    echo; echo "--- IO 压力（本盘 ROTA=1，起栈期间必须盯）---"; cat /proc/pressure/io
    echo "--- 磁盘 ---"; df -h / | tail -1
    ;;
  stop)
    docker rm -f lf-langfuse lf-langfuse-worker lf-clickhouse lf-valkey lf-minio lf-langfuse-db >/dev/null 2>&1 || true
    echo "OK: 六个容器已停（卷保留：lf-*  列出用 docker volume ls | grep lf-）"
    ;;
  down)
    need_env
    echo "确认删除观测数据卷？5 秒内 Ctrl-C 取消"
    sleep 5
    "$DC" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" down -v
    echo "OK: 容器与卷已删"
    ;;
  *) echo "用法: langfuse.sh [start|status|stop|down] [--env-file <600权限env>]"; exit 1;;
esac
