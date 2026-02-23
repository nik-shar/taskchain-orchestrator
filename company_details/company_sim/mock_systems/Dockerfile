FROM python:3.11-slim

WORKDIR /app

COPY company_sim/mock_systems/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY company_sim /app/company_sim

ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "company_sim.mock_systems.jira_api:app", "--host", "0.0.0.0", "--port", "8000"]
