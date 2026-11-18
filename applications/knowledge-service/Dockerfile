# 知识库服务（Knowledge Service）生产镜像
# 说明：默认按 requirements 全量安装（含 torch / langchain / magic-pdf，镜像较大但开箱即用）。
#       如需更小体积，可改用 CPU-only 依赖或按 README 的「CPU slim」说明裁剪。
# 2026-09-22 T1.1：monorepo 重组后路径修复。build context = 仓库根
# （docker-compose.yml context: ../..），COPY 路径一律相对仓库根；
# 包名已由 app 改为 knowledge_service（F-S0-08）。
#
# 2026-11-13 分层修复（部署提速 + 修复打包 bug）：
#   1) 把「第三方依赖安装（torch/langchain…大依赖，极少变动）」与
#      「业务源码拷贝 + editable 安装（频繁变动）」拆成两层。
#      改 import_router.py 等源码后重 build，只重跑末尾 `pip install -e . --no-deps`
#      （分钟级），不再触发 torch/langchain 全量重装。
#   2) 修复打包 bug：pyproject 的 readme = "README.md"，但原 Dockerfile 从未把 README.md
#      拷进镜像，导致 hatchling 生成元数据失败（OSError: Readme file does not exist）。
#      现显式 COPY README.md ./ 进镜像（见「代码层」开头）。
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# PyPI 源（2026-11-17 固化国内源，消除国际链路大包下载反复超时）：
# 默认清华源 + 读超时重试。docker build 可用 --build-arg PIP_INDEX_URL=... 覆盖。
# pip.conf 确保 editable 安装的 build isolation 子进程也走国内源。
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PIP_INDEX_URL=$PIP_INDEX_URL \
    PIP_TIMEOUT=120 \
    PIP_RETRIES=15

RUN pip config set global.index-url "${PIP_INDEX_URL}" \
 && pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn

WORKDIR /app

# ─────────────────────────────────────────────────────────────────────────────
# 第 1 层：依赖层（极少变动，可充分缓存）
# 只拷贝「依赖声明 + 共享包源码」，不拷业务源码，确保改业务代码不会让本层失效。
# ─────────────────────────────────────────────────────────────────────────────
COPY applications/knowledge-service/pyproject.toml applications/knowledge-service/requirements.txt ./
COPY packages/agent-core ./packages/agent-core
COPY packages/shared-schemas ./packages/shared-schemas
COPY applications/exhibition-agent ./applications/exhibition-agent

# 安装第三方依赖（requirements.txt 与 pyproject dependencies 保持一致）与共享包（editable）。
# otel-* 为可选 tracing 依赖（M4 全链路追踪），随镜像一并安装，确保 OTel 真实导出开箱即用
# （默认 no-op 降级，配置 AGENT_CORE_TRACE_ENABLED + endpoint 后启用）。
# 2026-11-16：CPU 版 torch 三件套先装（与根 Dockerfile 同因）。
# requirements.txt 里裸写 torch/torchvision/torchaudio ⇒ pip 默认拉 CUDA 轮（数 GB），
# 2026-11-16 实测在 241 构建 KS 镜像时 `pip install -r requirements.txt` 卡 20+ 分钟
# 无 TCP 连接（只有 57s CPU）。先从 CPU 索引装好满足依赖，后面 requirements 不再拉 CUDA 版。
RUN pip install --upgrade pip \
 && pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu \
 && pip install -r requirements.txt \
 && pip install -e ./packages/agent-core \
 && pip install -e ./packages/shared-schemas \
 && pip install -e ./applications/exhibition-agent \
 && pip install opentelemetry-sdk opentelemetry-api opentelemetry-exporter-otlp-proto-http

# ─────────────────────────────────────────────────────────────────────────────
# 第 2 层：代码层（频繁变动，重建代价低）
# README.md 必须随镜像存在：pyproject 的 readme = "README.md"，缺它 hatchling 生成元数据会失败。
# ─────────────────────────────────────────────────────────────────────────────
COPY README.md ./
COPY applications/knowledge-service/knowledge_service ./knowledge_service
COPY applications/knowledge-service/prompts ./prompts
COPY applications/knowledge-service/eval ./eval

# 业务包以 editable 安装，但 --no-deps：依赖已在第 1 层装好，此处仅登记源码路径。
# 改动源码后重 build，只会重跑这一条（快）。
RUN pip install -e . --no-deps

# 服务端口（FastAPI / uvicorn）
EXPOSE 8000

# 启动统一服务（文件导入 + 查询 合并为单一应用）；包名 knowledge_service（F-S0-08 改名后）
CMD ["uvicorn", "knowledge_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
