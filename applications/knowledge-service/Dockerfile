# 掌柜智库（Zhanggui Zhiku）生产镜像
# 说明：默认按 requirements 全量安装（含 torch / langchain / magic-pdf，镜像较大但开箱即用）。
#       如需更小体积，可改用 CPU-only 依赖或按 README 的「CPU slim」说明裁剪。
# 2026-09-22 T1.1：monorepo 重组后路径修复。build context = 仓库根
# （docker-compose.yml context: ../..），COPY 路径一律相对仓库根；
# 包名已由 app 改为 knowledge_service（F-S0-08）。
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 1) 先拷贝依赖清单（利用 Docker 层缓存，仅依赖变化时重新安装）
COPY applications/knowledge-service/pyproject.toml applications/knowledge-service/requirements.txt ./

# 1.5) 拷贝 agent-core 共享内核（monorepo 共享包，editable 安装）
COPY packages/agent-core ./packages/agent-core

# 2) 拷贝源码与提示词，再以可编辑模式安装（源码改动即时生效，便于调试）
COPY applications/knowledge-service/knowledge_service ./knowledge_service
COPY applications/knowledge-service/prompts ./prompts

# 3) 安装依赖（构建阶段需要联网拉取 PyPI 包）
#    先装 agent-core（本地共享包），再装本项目（editable），
#    opentelemetry-* 为可选 tracing 依赖（M4 全链路追踪，方案 §8），此处随镜像一并安装，
#    确保 OTel 真实导出开箱即用（默认 no-op 降级，配置 ZHANGUI_TRACE_ENABLED + endpoint 后启用）。
RUN pip install --upgrade pip && pip install -e ./packages/agent-core && pip install -e . \
    && pip install opentelemetry-sdk opentelemetry-api opentelemetry-exporter-otlp-proto-http

# 服务端口（FastAPI / uvicorn）
EXPOSE 8000

# 启动统一服务（文件导入 + 查询 合并为单一应用）；包名 knowledge_service（F-S0-08 改名后）
CMD ["uvicorn", "knowledge_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
