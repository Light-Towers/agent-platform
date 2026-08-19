# 掌柜智库（Zhanggui Zhiku）生产镜像
# 说明：默认按 requirements 全量安装（含 torch / langchain / magic-pdf，镜像较大但开箱即用）。
#       如需更小体积，可改用 CPU-only 依赖或按 README 的「CPU slim」说明裁剪。
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 1) 先拷贝依赖清单（利用 Docker 层缓存，仅依赖变化时重新安装）
COPY zhanggui-zhiku/pyproject.toml zhanggui-zhiku/requirements.txt ./

# 1.5) 拷贝 agent-core 共享内核（monorepo sibling，editable 安装）
COPY agent-core ./agent-core

# 2) 拷贝源码与提示词，再以可编辑模式安装（源码改动即时生效，便于调试）
COPY zhanggui-zhiku/app ./app
COPY zhanggui-zhiku/prompts ./prompts

# 3) 安装依赖（构建阶段需要联网拉取 PyPI 包）
#    先装 agent-core（本地 sibling），再装本项目（editable），
#    opentelemetry-* 为可选 tracing 依赖（M4 全链路追踪，方案 §8），此处随镜像一并安装，
#    确保 OTel 真实导出开箱即用（默认 no-op 降级，配置 ZHANGUI_TRACE_ENABLED + endpoint 后启用）。
RUN pip install --upgrade pip && pip install -e ./agent-core && pip install -e . \
    && pip install opentelemetry-sdk opentelemetry-api opentelemetry-exporter-otlp-proto-http

# 服务端口（FastAPI / uvicorn）
EXPOSE 8000

# 启动统一服务（文件导入 + 查询 合并为单一应用）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
