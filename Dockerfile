FROM python:3.11-slim

WORKDIR /srv/agent-platform

# agent-core / shared-schemas 是 pyproject.toml 的本地路径依赖（[tool.uv.sources] editable），
# 必须一并 COPY 进来，否则 pip install . 找不到包导致构建失败。
COPY pyproject.toml README.md ./
COPY agent-core ./agent-core
COPY shared-schemas ./shared-schemas
COPY app ./app

# agent-core / shared-schemas 是 [project].dependencies 里的本地 workspace 包，
# [tool.uv.sources] workspace=true 仅 uv 能解析；普通 pip 会误当 PyPI 包去下载。
# 故在同一安装事务中把两个本地路径一并传入，让 pip 识别为已满足的依赖。
RUN pip install --no-cache-dir ./agent-core ./shared-schemas .

# 容器安全：以非 root 用户运行（最佳实践）
RUN useradd -m -u 10001 appuser
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
