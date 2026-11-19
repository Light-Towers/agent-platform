# 构建提速：依赖层与频繁变更源码解耦

> 状态：方案评估完成，待确认构建环境后实施。触发（用户 2026-11-19）：每次部署花时巨长，怀疑每次都全量重下 torch 等包；提议"把基础包做成基础镜像"。

## 用户方案评估：可行，方向对，但当前环境有个前提要先解决

用户提议"把 torch 等基础包做成基础镜像，避免每次从头下"——方向正确。但有个关键事实：

**当前 241 用的是 legacy builder**（构建日志实证：`DEPRECATED: The legacy builder is deprecated...`，出现在所有 build_*.log）。
⇒ 用户拍板选的 "BuildKit `RUN --mount=type=cache`" **在 legacy builder 下不生效**（`--mount` 是 BuildKit 专属）。

两条路：
- **A. 先切 BuildKit**：构建脚本加 `DOCKER_BUILDKIT=1` + Dockerfile 加 `# syntax=docker/dockerfile:1`，再用 cache mount。收益最大（缓存跨构建复用 wheel），但要先确认 241 上 buildx/containerd 支持 BuildKit，且切 builder 可能影响现有构建流程。
- **B. 不切 BuildKit，纯层顺序 + 保留 pip 缓存**：去掉 `--no-cache-dir`，把 torch 安装单独成层且放在所有 workspace 源码 COPY 之前。层失效时 pip 仍能从镜像内 `~/.cache/pip` 命中。改动最小、无环境依赖。

## 病根（实取，不是猜）
- `Dockerfile:73` 把 `packages/agent-core` 等 workspace 源码 **COPY 在 torch 层之前**（:92）。
- 今天加 `hot_text.py` 改了 agent-core ⇒ torch 层输入变 ⇒ 整个依赖层失效 ⇒ 全量重下（build_hotprompt.log 只有 12 行但耗时 13min，就是重下被缓冲）。
- `upload` 批 892 行日志 = pip 全量重下的实证。
- `--no-cache-dir`（:53/:92/:102 和 KS Dockerfile 同）让 pip 自身不留缓存，只能靠 Docker 层缓存兜——层一失效就全量下载。

## 真环境事实（待服务器恢复确认）
- 代码里**没有直接 import torch**（grep 实证）。torch 由 flagembedding / pymilvus[model] / sentence-transformers 间接拉入。
- 真环境 embedding：平台 health 报 `LocalEmbedder`，但 KS 日志见 `EMBEDDING_MODE=api`（硅基流动）——两侧可能不同。**确认前不砍 torch**（用户选保守方案）。

## 方案（用户拍板：保守解耦，不砍 torch）
1. **优先 A（切 BuildKit + cache mount）**：先确认 241 支持，构建脚本加 `DOCKER_BUILDKIT=1`，Dockerfile 两个都加 `# syntax` 头 + torch/依赖安装行用 `RUN --mount=type=cache,target=/root/.cache/pip`。
2. **回退 B（不切 builder）**：调整层顺序——torch 安装提到所有 workspace 源码 COPY 之前；去掉 `--no-cache-dir` 让 pip 缓存留在镜像层内被后续复用。
3. 两个 Dockerfile（根 `Dockerfile` 平台 + `applications/knowledge-service/Dockerfile` KS）同样处理。

## 验证
- 改一次 agent-core（或一个频繁变的文件）重构建，观察是否还重下 torch：BuildKit cache mount 命中应秒级、B 方案 pip 从缓存命中应分钟级而非十几分钟。
- 不砍任何依赖，镜像功能不变（health/openapi 同前）。

## 待确认（服务器断连，用户约明早 9:00 验证）
- **A 方案验证脚本已备好**：`C:\...\Temp\opencode\verify_buildkit.sh`（scp 到 241 执行）。
  内容：① buildx version ② docker info 的 BuildKit 特性 ③ 最小 Dockerfile 用 `RUN --mount=type=cache` 构建自证能咬。
  rc=0 ⇒ A 可行（切 BuildKit + cache mount）；rc≠0 ⇒ 回退 B（纯层顺序 + 去 --no-cache-dir）。
- 真环境 embedding 模式 ⇒ 决定将来能否激进砍 torch（本次不做）。
- ⚠ 本 agent 无定时唤醒能力，不能明早 9:00 自跑——需用户届时发一句"开始验证"才执行。
