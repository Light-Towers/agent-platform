# ============================================================================
# 阶段 1/2 web-builder —— Node 只活在这一层（工单件 §9.3 / §10.2 形态 A″）
#
# 为什么在镜像里构建，而不是 COPY 本机已建好的 dist：后者让镜像内容取决于
# 「构建机碰巧有什么」——本机 dist 可能是旧 rev 的产物，而症状与本仓记过的
# 「可变 tag + IfNotPresent ⇒ 静默跑旧代码」完全同族（都是绿着跑的旧东西）。
#
# 2026-11-02 在 241 实取（不是推断）：node:24-alpine = node v24.22.2、corepack 0.36.0
# 在位、**pnpm 不在位** ⇒ 必须 `corepack enable`；corepack 读 web/package.json 的
# `packageManager: pnpm@10.33.0` 取版本，故 pnpm 版本号在本仓只有那一处真相，
# Dockerfile 与 workflow 都不双写（同 ADR-0013「三处 pin 必须一致」的反面做法）。
FROM node:24-alpine AS web-builder

WORKDIR /web

# 默认走官方 registry（仓库默认值必须中性，不能把内网镜像烤进 Dockerfile）。
# 内网构建时显式传 --build-arg NPM_REGISTRY=https://registry.npmmirror.com/：
# 241 实测两条都 200（npmjs 1.84s / npmmirror 0.19s），国际链路慢时换快的那条，
# 换的是下载路径而不是锁文件内容。
ARG NPM_REGISTRY=https://registry.npmjs.org/
RUN corepack enable

# 清单先 COPY、源码后 COPY：改一行 .vue 不应重装依赖（层缓存的最小前提）。
# --frozen-lockfile 是判据不是优化项：pnpm-lock.yaml 与 package.json 对不上时必须红，
# 而不是"悄悄装成别的版本然后构建绿"——锁文件因此是必入库件（工单件 §9.2）。
#
# ⚠ 2026-11-16 订正一处**注释与实物不同步**：上面那句"改一行 .vue 不应重装依赖"当时
#   **并没有成立**——`COPY web/ ./` 写在 `pnpm install` 之前，所以任何前端源码改动都会
#   让安装层失效，重跑一遍 pnpm install（2026-11-16 实测：内网每次 30–45s，且要联网）。
#   ⇒ 拆成三层：依赖层（只随清单变）/ 源码层（只随源码变）/ 构建层。
#   依据：COPY 的层缓存键 = 该指令及其之前所有层的输入摘要；把「清单」与「源码」
#   分成两次 COPY，安装层便不再看见源码。
COPY web/package.json web/pnpm-lock.yaml ./
RUN echo "registry=${NPM_REGISTRY}" > .npmrc && pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm run build

# ============================================================================
# 阶段 2/2 运行镜像：python:3.11-slim，**里面没有 node、没有 node_modules**
FROM python:3.11-slim

# ===== pip 下载加速（2026-11-17，消除构建期反复失败）=====
# 根因：wheel 从国际链路下载慢 + ReadTimeoutError（详见 plan-build-pypi-acceleration-2026-11-23）。
# 2026-11-23 实取：容器内拉阿里云 19MB/s、清华源回源仅 50-160kB/s ⇒ 默认走阿里云 + 读超时重试：
#   · pip.conf（pip config set）对所有 pip 子进程生效，含 editable 安装的 build isolation；
#   · 显式 --index-url 的命令（torch 走 download.pytorch.org）不受影响，仍走原路径（CPU wheel 走 CDN 不慢）。
# 默认值只在 build-env.sh 与各 Dockerfile 对齐；构建入口 build.sh source build-env.sh 后经
# --build-arg 覆盖，不再靠人每次手工传参。
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG PIP_TRUSTED_HOST=mirrors.aliyun.com
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TIMEOUT=120 \
    PIP_RETRIES=15
RUN pip config set global.index-url "${PIP_INDEX_URL}" \
 && pip config set global.trusted-host "${PIP_TRUSTED_HOST}"

WORKDIR /srv/agent-platform

# 观测依赖（opt-in 启用需要装包，否则软降级为 no-op）：
#   - ".[otel]" → 根包 extras：opentelemetry-sdk + opentelemetry-exporter-otlp（OTLP HTTP exporter，供 Jaeger）
# Langfuse 客户端包**自 2026-10-13 起入默认镜像**（需求方拍板接该面，方案
# docs/plans/plan-langfuse-wiring-2026-10-13.md）：extras 声明位仍归一在 agent-runtime
# （`[langfuse] = langfuse>=4.0.0`，lint L-4 监控），启用条件仍是配置（LANGFUSE_* 三键齐）。
# 装它的理由不是"要观测"，而是**消除"关了与坏了分不清"**：包不装时 tracing.py 只 warning
# 后返回空列表，配了凭据也静默不报；包常驻后 /health 的 langfuse_ready 才有真值可报。
# 实测代价（126 现网镜像内 pip --dry-run，2026-10-13）：新增 3 个包
# （langfuse 4.17.0 / backoff / wrapt ≈ 1MB），现有 OTel 1.45.1、pydantic 2.50.1、
# langchain-core、httpx **一个都没被降级**，解析 14.1s 零回溯
# ⇒ 旧「v2 与 langgraph 1.x 不可共存」的根因确已由 S4 迁 v3+/v4 契约终结。

# agent-core / shared-schemas 是 pyproject.toml 的本地路径依赖（[tool.uv.sources] editable），
# 必须一并 COPY 进来，否则 pip install . 找不到包导致构建失败。
COPY pyproject.toml README.md ./
COPY packages/agent-core ./packages/agent-core
COPY packages/shared-schemas ./packages/shared-schemas
COPY packages/agent-runtime ./packages/agent-runtime

# agent-core / shared-schemas / agent-runtime 是 [project].dependencies 里的本地 workspace 包，
# [tool.uv.sources] workspace=true 仅 uv 能解析；普通 pip 会误当 PyPI 包去下载。
# 故在同一安装事务中把本地路径一并传入，让 pip 识别为已满足的依赖。
# 注：pip 不认 [tool.uv.sources] workspace=true，故需显式传入本地路径。
#
# 本地语义模型（EMBEDDING_MODE=local）依赖：
# 1) extra 挂在 agent-core 上，不是根包 —— 写成 ".[otel,memory-embed-local]" 时 pip 只对未知
#    extra 告警并继续，构建照样绿、镜像里却没有 sentence_transformers，属静默丢失（2026-10-10 实测）。
# 2) torch 先从 CPU 索引装：否则 sentence-transformers 拉的是 CUDA 轮，白背 ~2G 且 Pod 内无 GPU可用。
#
# ⚠ 2026-11-16 调整**本层的位置**：原来这行在 `COPY applications/agent_server` 之后，
#   于是**每次改业务代码都让这层失效** ⇒ 重下 209MB 的 CPU 版 torch（2026-11-16 实测
#   约 2 分钟；且 `--no-cache-dir` 让 pip 自己不留缓存，只能靠 Docker 层缓存兜）。
#   ⇒ 把 torch 提到「业务代码 COPY」之前：它与业务代码无关，单独成层后，
#   改 applications/ 只失效后面那条 pip（依赖解析快得多），改 packages/ 才失效这一层。
#
# ⚠ 2026-11-23 再调整（plan-build-pypi-acceleration）：torch 的**传递依赖**
#   （networkx/sympy/jinja2/fsspec/pillow…）此前跟着 --index-url 一起从 download.pytorch.org
#   拉，实测 30kB/s + 偶发 Network unreachable，是最后一段慢源。改为先从快源（pip.conf 的
#   阿里云）预装这些依赖，再让 torch 本体 --no-deps 从 CPU 索引拉——209MB wheel 走 CDN
#   不慢，且依赖已满足后 pip 不再回 pytorch.org 取。
RUN pip install --no-cache-dir filelock typing-extensions sympy networkx jinja2 fsspec markupsafe \
 && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu --no-deps

# ── 依赖层拆分（plan-docker-build-layer-split-2026-11-24）────────────────────
# 原写法：COPY 整个 agent_server → pip install 全部依赖 → 改一行 .py 就让 pip 层失效、
# 重跑 100+ 包安装（实测每次 ~10min）。拆成"骨架装依赖 + 真代码秒级重装"两层：
#   · 骨架只需 __init__.py（纯声明、hatchling 能据此构建 wheel，本机 uv build 实测过），
#     这层的缓存键只绑 pyproject/packages/骨架/命令——改业务 .py 不失效。
#   · 真代码随后 COPY 覆盖，--no-deps 重装包本体（依赖已满足，秒级）。
COPY applications/agent_server/__init__.py ./applications/agent_server/__init__.py
# extras 必须挂在**声明它的那个包**上：`[langfuse]` 声明在 packages/agent-runtime
# （根包没有这个 extra）。写成 `.[langfuse]` 时 pip 只对未知 extra 告警并继续，
# 构建照样绿、镜像里却没有包——与 memory-embed-local 那颗雷完全同形（2026-10-10 实测）。
# identity/auth 两个 extra 是同一条雷的第二个实例（登录链路：签令牌靠 PyJWT[crypto]、校
# 口令靠 argon2-cffi）：本地 .venv 里两个包都靠 `uv sync --all-packages` 的**传递依赖**
# 在位，所以本地跑绿不能证明镜像里有——必须在本行显式带 extra（方案 §9 第二条）。
# pymilvus：Milvus 检索实现运行时需要 MilvusClient（2026-11-18 缺包事故），版本钉 3.0.3
# 与 KS 对齐；稀疏向量是零依赖实现，只需核心包、不需 [model] extra。
RUN pip install --no-cache-dir \
      "./packages/agent-core[memory-embed-local]" ./packages/shared-schemas \
      "./packages/agent-runtime[langfuse,identity,auth]" ".[otel]" pymilvus==3.0.3

# 业务代码层：覆盖骨架，仅重装根包本体（--no-deps 不重新解析依赖，秒级）。
COPY applications/agent_server ./applications/agent_server
RUN pip install --no-cache-dir --no-deps --force-reinstall .

# 前端产物落点 = /srv/agent-platform/web/dist。这条对不是约定，是被机器钉住的契约：
# applications/agent_server/main.py 的默认探测点是**进程 CWD** 拼 `web/dist`，而本镜像的
# WORKDIR `/srv/agent-platform` 既是仓库根也是运行时 CWD ⇒ 两条算出同一个路径。
# ⚠ 基准不是从 `__file__` 往上数：镜像里 `pip install .` 那份 site-packages 才是被 import
# 的模块，往上数两层数到解释器目录 ⇒ 2026-11-02 在 241 真容器 `GET /ui/` 404（同一条构建链上
# /health 是 200，所以这不是“服务没起”而是“探测基准算错地方”）。全案与失效形状在工单件 §9.4，
# 钉子（含“函数体里不得出现 `parents[`”那一格）在 applications/agent_server/tests/test_web_ui_mount.py。
# 放在两条 pip 之后（不是之前）：改一行 .vue 只重建本层，不把 ~2G 的 pip 层缓存打掉。
COPY --from=web-builder /web/dist ./web/dist

# 构建源 git rev 绑定（观测方案 §3.5，解 R14「验证对象与提交不一致」/126 假同步事故）：
# 构建脚本传 --build-arg GIT_REV=$(git rev-parse HEAD)，写入 OCI label + 容器内文件，
# 取证时可 docker run --rm <img> cat /srv/agent-platform/GIT_REV 回查镜像对应提交。
ARG GIT_REV=unknown
LABEL org.opencontainers.image.revision=${GIT_REV}
RUN echo "${GIT_REV}" > /srv/agent-platform/GIT_REV

# 容器安全：以非 root 用户运行（最佳实践）
RUN useradd -m -u 10001 appuser
USER appuser

EXPOSE 8000

CMD ["uvicorn", "agent_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
