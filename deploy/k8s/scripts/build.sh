#!/usr/bin/env bash
# build.sh — 在选定的构建机上从**同一条源 rev** 构建全部镜像，并逐个绑定 git rev。
#
# 当前两个 tag（IMAGES 可调，空格分隔）：
#   agent-platform:dev   ← Dockerfile              （平台 Supervisor）
#   nl2sql-service:dev   ← Dockerfile.nl2sql-service（Text2SQL 服务，ADR-0011 选项 A 的唯一问数路）
#
# 用法（在**选定的构建机**上执行；Windows 侧先 scp 本目录并去 CRLF）：
#   sed -i 's/\r$//' deploy/k8s/scripts/*.sh
#   bash deploy/k8s/scripts/build.sh <expected-rev>
#   SRC_DIR=/other/checkout bash deploy/k8s/scripts/build.sh <expected-rev>
#   IMAGES="agent-platform:dev" bash deploy/k8s/scripts/build.sh <expected-rev>   # 只构一个
# 构建机不必是 126：本脚本只要求那台机有 docker + 一份处于 expected-rev 的 checkout。
# 2026-10-13 起默认放 <internal-host>(241) —— 126 的 ROTA=1 单盘上 pip 铺上万个文件会把
# 同机 etcd 打进 `slow fdatasync`（实测 avg10 冲到 67%，milvus 重启 30→31）。
# 换机后 distribute.sh 必须显式带上其余全部节点（见该脚本头部）。
#
# 成功判据：构建源 HEAD == <expected-rev>（不等即中止——126 假同步事故的根治门禁，
# 观测方案 §3.5 R14）；**每个** tag 的 docker build 成功，且镜像内 GIT_REV 回读 == expected-rev。
# 退出码：0 成功 / 1 docker build 或回读失败 / 2 rev 不匹配或 tag 无映射（禁止带旧源构建）。
set -euo pipefail

EXPECTED_REV="${1:?用法: build.sh <expected-rev>（本地要验证的提交，先 git -C <repo> rev-parse HEAD 取得）}"
SRC_DIR="${SRC_DIR:-/opt/agent-platform}"
# 旧写法 IMAGE=<tag> 仍生效（单镜像覆盖），免得文档里的配方一改动就失效。
IMAGES="${IMAGE:-${IMAGES:-agent-platform:dev nl2sql-service:dev}}"

# tag → Dockerfile 映射。未知名即中止：**不默认回落到根 Dockerfile**——同一份源、
# 不同的包，回落到根 Dockerfile 会构建出一个“名字是 nl2sql、内容是平台”的镜像，
# rev 门禁与 GIT_REV 回读全都绿，跑着的却是另一个进程（“静默跑错代码”的同形病灶）。
dockerfile_for() {
  case "${1%%:*}" in
    agent-platform) echo "Dockerfile" ;;
    nl2sql-service) echo "Dockerfile.nl2sql-service" ;;
    *) return 1 ;;
  esac
}

ACTUAL_REV="$(git -C "$SRC_DIR" rev-parse HEAD)"
if [ "$ACTUAL_REV" != "$EXPECTED_REV" ]; then
  echo "FAIL: 构建源 $SRC_DIR HEAD=$ACTUAL_REV != 期望 $EXPECTED_REV"
  echo "      先同步：git -C $SRC_DIR fetch && git -C $SRC_DIR checkout $EXPECTED_REV"
  exit 2
fi
DIRTY="$(git -C "$SRC_DIR" status --porcelain | head -5 || true)"
[ -n "$DIRTY" ] && echo "WARN: 工作区不干净（构建含未提交改动，取证须注明）: $DIRTY"

cd "$SRC_DIR"

for IMAGE in $IMAGES; do
  DF="$(dockerfile_for "$IMAGE")" || { echo "FAIL: 镜像名 $IMAGE 无 Dockerfile 映射（新增镜像请同时改本脚本的 dockerfile_for）"; exit 2; }
  echo "### build $IMAGE  <-  $DF"
  docker build --build-arg GIT_REV="$ACTUAL_REV" -f "$DF" -t "$IMAGE" .

  # 回读验证：镜像内嵌 rev == 构建源 rev（label + 文件双通道），**逐 tag** 做。
  # 两个 tag 同源的这件事必须可核对：只验一个就等于没验另一个。
  EMBEDDED="$(docker run --rm "$IMAGE" cat /srv/agent-platform/GIT_REV)"
  if [ "$EMBEDDED" != "$ACTUAL_REV" ]; then
    echo "FAIL: $IMAGE 内 GIT_REV=$EMBEDDED != $ACTUAL_REV"; exit 1
  fi
  # 注：Labels 是 map 且 key 含点，docker 模板必须用 index，直写 .Labels.org.xxx 会解出 <no value>
  docker inspect -f "revision label: {{ index .Config.Labels \"org.opencontainers.image.revision\" }}" "$IMAGE"
done
echo "OK: built [$IMAGES] @ $ACTUAL_REV (dirty=${DIRTY:+yes}${DIRTY:-no})"
