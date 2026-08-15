FROM python:3.11-slim
WORKDIR /app

COPY shared-schemas/ ./shared-schemas/
RUN pip install --no-cache-dir ./shared-schemas

COPY wenda-adapter/pyproject.toml .
COPY wenda-adapter/main.py .
RUN pip install --no-cache-dir .

EXPOSE 8001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
