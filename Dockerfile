FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --upgrade pip && \
    python -m pip install .

EXPOSE 8080

CMD ["sh", "-c", "uvicorn orchestrator_api.main:app --host 0.0.0.0 --port ${PORT}"]
