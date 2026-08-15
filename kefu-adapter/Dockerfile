FROM python:3.11-slim
WORKDIR /app

COPY shared-schemas/ ./shared-schemas/
RUN pip install --no-cache-dir ./shared-schemas

COPY kefu-adapter/pyproject.toml .
COPY kefu-adapter/main.py .
RUN pip install --no-cache-dir .

EXPOSE 8002
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
