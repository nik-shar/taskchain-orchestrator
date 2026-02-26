FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    AGENT_ORCHESTRATOR_COMPANY_SIM_ROOT=/app/company_details/company_sim \
    AGENT_ORCHESTRATOR_RAG_INDEX_PATH=/app/data/rag_index.sqlite

COPY agent-orchestrator/pyproject.toml agent-orchestrator/README.md ./agent-orchestrator/
COPY agent-orchestrator/src ./agent-orchestrator/src
COPY company_details/company_sim ./company_details/company_sim
COPY data/rag_index.sqlite ./data/rag_index.sqlite

RUN python -m pip install --upgrade pip && \
    python -m pip install ./agent-orchestrator

EXPOSE 8080

CMD ["sh", "-c", "uvicorn agent_orchestrator.api.main:app --host 0.0.0.0 --port ${PORT}"]
