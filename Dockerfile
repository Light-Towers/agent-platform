FROM python:3.11-slim

WORKDIR /srv/agent-platform

# 观测依赖（opt-in 启用需要装包，否则软降级为 no-op）：
#   - ".[otel]" → 根包 extras：opentelemetry-sdk + opentelemetry-exporter-otlp（OTLP HTTP exporter，供 Jaeger）
# 注：Langfuse 仍不入默认镜像。旧「v2 与 langgraph 1.x 不可共存」的根因已由观测方案 S4
#     迁 v3+/v4 代际契约（langfuse.langchain，OTel-based，不再锁 langchain-core<0.4）终结；
#     镜像不装属 opt-in 减重决策，启用方 --extra langfuse / extras 声明见 lint L-4 归一位。

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
RUN pip install --no-cache-dir ./packages/agent-core ./packages/shared-schemas ./packages/agent-runtime ".[otel]"

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
