# company_sim

Fictional company simulation dataset for an enterprise AI operations agent.

## Folder Layout

```text
company_sim/
  README.md
  docs/
    company_profile.md
    governance_notes.md
  mock_systems/
    README.md
    Dockerfile
    docker-compose.yml
    requirements.txt
    jira_api.py
    metrics_api.py
    logs_api.py
    common.py
    data/
      jira_tickets.json
      metrics_timeseries.json
      log_events.json
    tests/
      test_jira_api.py
      test_metrics_api.py
      test_logs_api.py
  tool_configs/
    slack.yaml
    jira.yaml
    postgres.yaml
    github_actions.yaml
    oncall_rota.yaml
  policies/
    policy_v1.md
    policy_v2.md
  scenarios/
    tasks.jsonl
    expected_outcomes.jsonl
```

## Simulation Summary

- Company: Northstar Metrics (mid-size SaaS)
- Tool stack: Slack, Jira, Postgres, GitHub Actions
- Baseline policy: `company_sim/policies/policy_v1.md`
- Updated policy: `company_sim/policies/policy_v2.md`

## Config Cross-References

- Communications and reporting channels: `company_sim/tool_configs/slack.yaml`
- Incident/change ticketing and project keys: `company_sim/tool_configs/jira.yaml`
- Database controls and audit tables: `company_sim/tool_configs/postgres.yaml`
- CI/CD approvals and rollback pipeline: `company_sim/tool_configs/github_actions.yaml`
- Escalation routing and handoff: `company_sim/tool_configs/oncall_rota.yaml`

## Scenarios

- `company_sim/scenarios/tasks.jsonl` contains 30 realistic AI-ops tasks.
- `company_sim/scenarios/expected_outcomes.jsonl` contains expected output properties only (not full answers), including required citations.

## Mock Systems

- Jira mock API: `company_sim/mock_systems/jira_api.py`
- Metrics mock API: `company_sim/mock_systems/metrics_api.py`
- Logs mock API: `company_sim/mock_systems/logs_api.py`
- Compose runtime: `docker-compose.yml` (or `company_sim/mock_systems/docker-compose.yml`)
- Integration tests: `make test`
