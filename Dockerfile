FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ORCHESTRATOR_COMPANY_SIM_ROOT=/app/company_details/company_sim \
    ORCHESTRATOR_RAG_INDEX_PATH=/app/data/rag_index.sqlite

COPY pyproject.toml README.md ./
COPY src ./src
COPY company_details/company_sim ./company_details/company_sim
COPY data/rag_index.sqlite ./data/rag_index.sqlite

RUN python -m pip install --upgrade pip && \
    python -m pip install .

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "orchestrator_api.main:app", "--host", "0.0.0.0", "--port", "8080"]