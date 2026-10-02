#!/usr/bin/env bash
# build.sh — 在 126（control-plane，构建机）上构建 agent-platform 镜像，并绑定 git rev。
#
# 用法（在 126 上执行；Windows 侧先 scp 本目录并去 CRLF）：
#   sed -i 's/\r$//' deploy/k8s/scripts/*.sh
#   bash deploy/k8s/scripts/build.sh <expected-rev>
#
# 成功判据：构建源 HEAD == <expected-rev>（不等即中止——126 假同步事故的根治门禁，
# 观测方案 §3.5 R14）；docker build 成功；镜像内 GIT_REV 文件回读 == expected-rev。
# 退出码：0 成功 / 1 docker build 失败 / 2 rev 不匹配（禁止带旧源构建）。
set -euo pipefail

EXPECTED_REV="${1:?用法: build.sh <expected-rev>（本地要验证的提交，先 git -C <repo> rev-parse HEAD 取得）}"
SRC_DIR="${SRC_DIR:-/opt/agent-platform}"
IMAGE="${IMAGE:-agent-platform:dev}"

ACTUAL_REV="$(git -C "$SRC_DIR" rev-parse HEAD)"
if [ "$ACTUAL_REV" != "$EXPECTED_REV" ]; then
  echo "FAIL: 构建源 $SRC_DIR HEAD=$ACTUAL_REV != 期望 $EXPECTED_REV"
  echo "      先同步：git -C $SRC_DIR fetch && git -C $SRC_DIR checkout $EXPECTED_REV"
  exit 2
fi
DIRTY="$(git -C "$SRC_DIR" status --porcelain | head -5 || true)"
[ -n "$DIRTY" ] && echo "WARN: 工作区不干净（构建含未提交改动，取证须注明）: $DIRTY"

cd "$SRC_DIR"
docker build --build-arg GIT_REV="$ACTUAL_REV" -t "$IMAGE" .

# 回读验证：镜像内嵌 rev == 构建源 rev（label + 文件双通道）
EMBEDDED="$(docker run --rm "$IMAGE" cat /srv/agent-platform/GIT_REV)"
if [ "$EMBEDDED" != "$ACTUAL_REV" ]; then
  echo "FAIL: 镜像内 GIT_REV=$EMBEDDED != $ACTUAL_REV"; exit 1
fi
# 注：Labels 是 map 且 key 含点，docker 模板必须用 index，直写 .Labels.org.xxx 会解出 <no value>
docker inspect -f 'revision label: {{ index .Config.Labels "org.opencontainers.image.revision" }}' "$IMAGE"
echo "OK: built $IMAGE @ $ACTUAL_REV (dirty=${DIRTY:+yes}${DIRTY:-no})"
