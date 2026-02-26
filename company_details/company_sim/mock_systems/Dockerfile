FROM python:3.11-slim

WORKDIR /app

COPY company_sim/mock_systems/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY company_sim /app/company_sim

ENV PYTHONUNBUFFERED=1 \
    PORT=8000 \
    APP_MODULE=company_sim.mock_systems.jira_api:app

CMD ["sh", "-c", "uvicorn ${APP_MODULE} --host 0.0.0.0 --port ${PORT}"]
