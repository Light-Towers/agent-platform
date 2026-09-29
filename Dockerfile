FROM python:3.11-slim

WORKDIR /srv/agent-platform

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
# 观测依赖（opt-in 启用需要装包，否则 agent_runtime.otel 软降级为 no-op）：
#   - ".[otel]" → 根包 extras：opentelemetry-sdk + opentelemetry-exporter-otlp（OTLP HTTP exporter，供 Jaeger）
# 注：Langfuse 不在此安装——agent_server 栈为 langgraph>=1.2.10 / langchain-core 1.x，而产品
#     langfuse 路径（agent_runtime.tracing 的 `from langfuse.callback import CallbackHandler`）
#     只存在于 langfuse v2，需 langchain 0.x（强制 langchain-core<0.4），与 langgraph 1.x 不可共存
#     （实测 pip 无限回溯）。详见 deploy/k8s/README.md 踩坑表与 VERIFICATION.md。
RUN pip install --no-cache-dir ./packages/agent-core ./packages/shared-schemas ./packages/agent-runtime ".[otel]"

# 容器安全：以非 root 用户运行（最佳实践）
RUN useradd -m -u 10001 appuser
USER appuser

EXPOSE 8000

CMD ["uvicorn", "agent_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
