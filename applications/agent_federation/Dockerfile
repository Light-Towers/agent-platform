FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
    gcc libcairo2-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*

# monorepo 路径已更新（2026-08-21）：agent-core → packages/agent-core，
# agent_federation → applications/agent_federation。Dockerfile build context
# 为仓库根目录（docker-compose context: ..）。
COPY packages/agent-core/ ./packages/agent-core/
COPY packages/shared-schemas/ ./packages/shared-schemas/
COPY packages/agent-runtime/ ./packages/agent-runtime/
COPY applications/agent_federation/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir ./packages/agent-core ./packages/shared-schemas ./packages/agent-runtime

COPY applications/agent_federation/ .

EXPOSE 8000

CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]
