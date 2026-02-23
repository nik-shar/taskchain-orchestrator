# Northstar Metrics Operations Policy v1

Effective date: 2026-01-15

## 1. Scope and Required References

This policy governs production incident response, change management, rollback, and audit evidence for all SaaS services.

Required operational references:

- Slack channels: `company_sim/tool_configs/slack.yaml`
- Jira projects/workflows: `company_sim/tool_configs/jira.yaml`
- On-call escalation chain: `company_sim/tool_configs/oncall_rota.yaml`
- Deployment controls: `company_sim/tool_configs/github_actions.yaml`
- Database audit controls: `company_sim/tool_configs/postgres.yaml`

## 2. Incident Severity Matrix (P1/P2/P3)

- `P1`: Multi-customer outage, security-critical exposure, or data corruption risk in production.
- `P2`: Partial service degradation with measurable customer impact but available workaround.
- `P3`: Minor degradation or internal-only issue with limited/no customer impact.

Jira priority mapping must follow `company_sim/tool_configs/jira.yaml` (`P1=Highest`, `P2=High`, `P3=Medium`) and incidents must be filed in project `OPS`.

## 3. Escalation Timings

Escalation order and current assignees come from `company_sim/tool_configs/oncall_rota.yaml`.

- `P1`
  - Acknowledge in 5 minutes.
  - Escalate to secondary on-call at +10 minutes if no active mitigation.
  - Escalate to incident manager at +20 minutes.
  - Escalate to VP Engineering at +30 minutes if customer impact persists.
- `P2`
  - Acknowledge in 15 minutes.
  - Escalate to secondary on-call at +30 minutes if owner unresponsive.
  - Escalate to incident manager at +60 minutes if unresolved.
- `P3`
  - Acknowledge in 4 hours during business day.

## 4. Reporting Channels and Communication Cadence

Channels must map to `company_sim/tool_configs/slack.yaml`.

- All incidents: `#ops-incidents`
- Paging relay and handoff notices: `#eng-oncall`
- P1 executive updates: `#exec-incident-brief`

Cadence:

- `P1`: Public update every 15 minutes in `#ops-incidents`, mirrored to `#exec-incident-brief`.
- `P2`: Update every 30 minutes in `#ops-incidents`.
- `P3`: Initial notice and resolution summary in `#ops-incidents`.

## 5. Change Windows

Change announcements must be posted to `#ops-changes` and linked to a Jira `OPS` Change ticket.

- Standard production window: Tuesday-Thursday, 14:00-22:00 UTC.
- High-risk changes: Friday, 14:00-16:00 UTC with Engineering Director approval.
- Freeze window: Friday 18:00 UTC to Monday 08:00 UTC.
- Emergency change exception: Allowed during freeze only when linked to active `P1` incident.

## 6. Rollback Triggers

Rollback must be initiated using `rollback-deploy` workflow from `company_sim/tool_configs/github_actions.yaml` when any trigger is met:

1. Error rate >4.0% for 10 consecutive minutes.
2. p95 latency >35% above 7-day baseline for 15 minutes.
3. Health check failure in 3 consecutive checks across 2 regions.
4. Any failed data integrity validation in production.

## 7. Approvals

Approval routing uses Jira and GitHub Actions controls:

- Standard production deploy: 2 approvals (service owner + SRE on-call) and `OPS` Change ticket in `Approved` status.
- Schema change touching Postgres production: 2 approvals including DBA delegate.
- Emergency deploy during incident: 1 approval from incident commander; second approval must be recorded within 24 hours.

## 8. Audit Logging Requirements

- Every incident action must be timestamped in the Jira `OPS` incident timeline.
- Every deploy/rollback must include GitHub Actions run URL in Jira and post a status note in `#audit-ops`.
- Postgres audit records must be written to `ops_audit.deployment_events`, `ops_audit.rollback_events`, and `ops_audit.incident_timeline` within 15 minutes.
- Audit exports must remain immutable and retained per `company_sim/tool_configs/postgres.yaml`.
