#!/usr/bin/env bash
# build-env.sh — 构建期下载源的**唯一真相源**（plan-build-pypi-acceleration-2026-11-23）
#
# 为什么在 scripts/ 而不是 deploy/k8s/scripts/：后者被 .gitignore:145 整目录排除（含真实
# k8s 节点标签等内网标识，按方案 X 不进公开 GitHub）。若把源配置留在那里，改了不入库，
# 新克隆/新 agent 拿到的还是旧值 ⇒ 又踩一遍慢源（AGENTS.md「入库≠被读」同族）。
# 本文件**只含公网源 URL、零内网真值**，可安全入库，受 P18 门禁 + doc-sync 保护。
# 目录名不用 `scripts/build/`：.gitignore:13 的 `build/` 规则会匹配任意层级同名目录，
# 导致"以为入库、实际被 ignore"（2026-11-23 实踩，已改名 deploy-recipe）。
#
# 消费方式（构建机上 gitignored 的 deploy/k8s/scripts/build.sh 等）：
#   source <repo>/scripts/deploy-recipe/build-env.sh
#   BUILD_ARGS=(... "--build-arg" "PIP_INDEX_URL=${PIP_INDEX_URL}")
# 绝不再硬编码 --build-arg PIP_INDEX_URL=...（那会覆盖本文件，且门禁扫不到 gitignored 副本）。
#
# 可用环境变量覆盖源（仅当某源临时不可达）；默认值只在本文件定义一次。

# PyPI 源：阿里云（公共镜像，241 容器实测 19MB/s；清华源回源仅 50–160kB/s）
PIP_INDEX_URL="${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple/}"
PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST:-mirrors.aliyun.com}"
# NPM 源：npmmirror（公共镜像，241 实测 0.19s vs npmjs 1.84s）
NPM_REGISTRY="${NPM_REGISTRY:-https://registry.npmmirror.com/}"

# torch 本体仍走 download.pytorch.org（阿里云无 +cpu 版），但传递依赖必须先从快源预装，
# 再让本体 --no-deps 拉——这条纪律由 P18 门禁钉住，3 个 Dockerfile 已落地。

export PIP_INDEX_URL PIP_TRUSTED_HOST NPM_REGISTRY
