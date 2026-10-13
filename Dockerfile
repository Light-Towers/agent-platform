FROM python:3.11-slim

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
COPY applications/agent_server ./applications/agent_server

# agent-core / shared-schemas / agent-runtime 是 [project].dependencies 里的本地 workspace 包，
# [tool.uv.sources] workspace=true 仅 uv 能解析；普通 pip 会误当 PyPI 包去下载。
# 故在同一安装事务中把本地路径一并传入，让 pip 识别为已满足的依赖。
# 注：pip 不认 [tool.uv.sources] workspace=true，故需显式传入本地路径。
#
# 本地语义模型（EMBEDDING_MODE=local）依赖：
# 1) extra 挂在 agent-core 上，不是根包 —— 写成 ".[otel,memory-embed-local]" 时 pip 只对未知
#    extra 告警并继续，构建照样绿、镜像里却没有 sentence_transformers，属静默丢失（2026-10-10 实测）。
# 2) torch 先从 CPU 索引装：否则 sentence-transformers 拉的是 CUDA 轮，白背 ~2G 且 Pod 内无 GPU可用。
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
# extras 必须挂在**声明它的那个包**上：`[langfuse]` 声明在 packages/agent-runtime
# （根包没有这个 extra）。写成 `.[langfuse]` 时 pip 只对未知 extra 告警并继续，
# 构建照样绿、镜像里却没有包——与 memory-embed-local 那颗雷完全同形（2026-10-10 实测）。
RUN pip install --no-cache-dir "./packages/agent-core[memory-embed-local]" ./packages/shared-schemas "./packages/agent-runtime[langfuse]" ".[otel]"

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
