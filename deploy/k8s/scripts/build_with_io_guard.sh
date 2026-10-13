#!/usr/bin/env bash
# build_with_io_guard.sh — 在指定构建机上跑 build.sh，全程采 PSI IO 压力，越线自动中止。
#
# 为什么需要它（2026-10-13 实测）：`docker build` 的 pip 层会在**同一块 ROTA=1 单盘**上
# 铺上万个文件。在 126 上构建时实测 `/proc/pressure/io some avg10=67.47%`，连带把同机
# knowledge-service 的 etcd 打进 `slow fdatasync`（5 分钟 41 条）、milvus 累计重启 30→31。
# 换到 241 构建只是换了受害者（241 上是自己的 Pod），**不等于风险消失** ⇒ 边跑边采，越线即停，
# 而不是事后翻日志才发现自己把别人的服务打死了。
#
# 用法（在构建机上执行）：
#   bash deploy/k8s/scripts/build_with_io_guard.sh <expected-rev> [其余节点列表]
#     例：bash .../build_with_io_guard.sh c01e9cf... <internal-ip> <internal-ip>
#     第 2 个参数起 = distribute.sh 的目标节点；**换构建机后必须显式列全其余所有节点**，
#     漏一台则该台没有镜像层，而部署无 nodeSelector ⇒ Pod 调度过去即 ErrImagePull。
#
# 可调环境变量：IO_LIMIT(默认 60%) / IO_STRIKES(默认连续 3 次) / IMAGE / SRC_DIR
# 退出码：0 全成 / 1 构建失败 / 2 rev 或路径问题 / 3 IO 熔断中止 / 4 分发失败 / 5 A1 复验失败
set -uo pipefail

REV="${1:?用法: build_with_io_guard.sh <expected-rev> [目标节点...]}"
shift
TARGETS="${*:-<internal-ip> <internal-ip>}"     # 从 126 构建的历史默认值
SRC_DIR="${SRC_DIR:-/opt/agent-platform}"
REPO="$SRC_DIR/deploy/k8s/scripts"
IMAGE="${IMAGE:-agent-platform:dev}"
IO_LIMIT="${IO_LIMIT:-60}"
IO_STRIKES="${IO_STRIKES:-3}"

[ -d "$REPO" ] || { echo "FAIL: 找不到 $REPO（构建机上先 clone/checkout 到 expected-rev）"; exit 2; }

echo "### 构建机自检"
printf "  host=%s  盘=%s  PSI=%s\n" "$(hostname)" \
  "$(lsblk -d -o NAME,ROTA,SIZE | awk 'NR==2{print $1"(ROTA="$2") "$3}')" \
  "$(awk '/^some/{print $2}' /proc/pressure/io)"
printf "  空闲: %s | 内存 avail: %s\n" "$(df -h / | tail -1 | awk '{print $4}')" "$(free -g | awk 'NR==2{print $7 "G"}')"
echo "  分发目标: $TARGETS"

echo "### 1/3 构建 rev=$REV（IO 采样中，阈值 avg10>${IO_LIMIT}% 连续 ${IO_STRIKES} 次即中止）"
(
  strikes=0
  while true; do
    a10=$(awk '/^some/{split($2,a,"="); print int(a[2])}' /proc/pressure/io)
    echo "$(date +%H:%M:%S) avg10=${a10}%"
    if [ "${a10:-0}" -gt "$IO_LIMIT" ]; then
      strikes=$((strikes + 1)); echo "  越线 $strikes/$IO_STRIKES"
      if [ "$strikes" -ge "$IO_STRIKES" ]; then
        echo "TRIP: IO 熔断"
        # 括号技巧：模式若写成 "docker build"，本 subshell 自己的 argv 里并没有这个串，
        # 但外层 ssh 命令行可能有（pkill -f 会连自己的会话一起杀，实测踩过两次）。
        pkill -f "[d]ocker build" || true
        exit 9
      fi
    else
      strikes=0
    fi
    sleep 10
  done
) &
SAMPLER=$!
trap 'kill $SAMPLER 2>/dev/null' EXIT

cd "$SRC_DIR" || exit 2
sed -i 's/\r$//' "$REPO"/*.sh 2>/dev/null || true
timeout 1800 bash "$REPO/build.sh" "$REV"
BUILD_RC=$?
kill $SAMPLER 2>/dev/null; wait $SAMPLER 2>/dev/null; SAMPLER_RC=$?
echo "build rc=$BUILD_RC  sampler rc=$SAMPLER_RC"
[ "$SAMPLER_RC" = "9" ] && { echo "FAIL: 因 IO 熔断中止构建（换个安静时段，或换构建机）"; exit 3; }
[ "$BUILD_RC" = "0" ] || { echo "FAIL: 构建未通过"; exit 1; }

echo "### 2/3 A1：在**镜像内**验目标 import 真成功（而非「解析器不报错」）"
# 这条判据的存在理由：langfuse.langchain 的导入前置是**顶层 langchain 包**，
# 上一版只验依赖解析就上线，结果镜像里 import 失败被软 except 吞成"静默不报"。
docker run --rm "$IMAGE" sh -c \
  'cat /srv/agent-platform/GIT_REV; python -c "import langfuse, langfuse.langchain; print(\"A1 OK langfuse\", langfuse.__version__)"' \
  || { echo "FAIL: A1 不通过，禁止分发"; exit 5; }

echo "### 3/3 分发到其余全部节点"
IMAGE="$IMAGE" timeout 1800 bash "$REPO/distribute.sh" $TARGETS || { echo "FAIL: 分发失败"; exit 4; }

echo "### 回读：每个节点自己的 containerd-k8s 里有没有这个镜像（不信脚本的 OK 行）"
for h in $(hostname -I | awk '{print $1}') $TARGETS; do
  line=$(ssh -o BatchMode=yes -o ConnectTimeout=8 root@$h \
    'sudo crictl --runtime-endpoint unix:///run/containerd-k8s/containerd.sock images 2>/dev/null | grep -E "agent-platform[[:space:]]+dev" | head -1')
  printf "  %-16s %s\n" "$h" "${line:-（未见到）}"
done
echo "### 结束前 PSI: $(awk '/^some/{print $2}' /proc/pressure/io)"
echo "OK: 构建 + A1 + 分发完成。下一步在 control-plane 上 apply/rollout/verify。"
