# Northstar Metrics Operations Policy v2

Effective date: 2026-02-01
Supersedes: `company_sim/policies/policy_v1.md`

## 1. Scope and Required References

This revision tightens response and rollback controls for production reliability.

Mandatory references for every operational decision:

- `company_sim/tool_configs/slack.yaml`
- `company_sim/tool_configs/jira.yaml`
- `company_sim/tool_configs/oncall_rota.yaml`
- `company_sim/tool_configs/github_actions.yaml`
- `company_sim/tool_configs/postgres.yaml`

## 2. Incident Severity Matrix (P1/P2/P3)

Severity definitions are unchanged from v1, but response obligations are stricter.

- `P1`: Critical outage/security/data integrity risk.
- `P2`: Material degradation with customer impact and workaround.
- `P3`: Low-impact or internal issue.

All incidents must use Jira project `OPS` and priority mapping in `company_sim/tool_configs/jira.yaml`.

## 3. Escalation Timings (Updated)

Use escalation order from `company_sim/tool_configs/oncall_rota.yaml`.

- `P1`
  - Acknowledge in 3 minutes.
  - Escalate to secondary on-call at +7 minutes if no mitigation owner assigned.
  - Escalate to incident manager at +15 minutes.
  - Escalate to VP Engineering at +25 minutes if customer impact is ongoing.
- `P2`
  - Acknowledge in 10 minutes.
  - Escalate to secondary on-call at +20 minutes if unowned.
  - Escalate to incident manager at +45 minutes if unresolved.
- `P3`
  - Acknowledge within 2 business hours.

## 4. Reporting Channels and Communication Cadence (Updated)

Routing must use channels in `company_sim/tool_configs/slack.yaml`.

- All incidents: `#ops-incidents`
- Paging/handoff: `#eng-oncall`
- Executive stream for `P1`: `#exec-incident-brief`
- Audit notifications: `#audit-ops`

Cadence:

- `P1`: Update every 10 minutes in `#ops-incidents`; summary every 20 minutes in `#exec-incident-brief`.
- `P2`: Update every 20 minutes in `#ops-incidents`.
- `P3`: Start and end updates in `#ops-incidents`; no periodic cadence required.

## 5. Change Windows (Updated)

Change events must be announced in `#ops-changes` and linked to Jira `OPS` Change issue.

- Standard production window: Monday-Thursday, 13:00-21:00 UTC.
- High-risk changes: Thursday, 16:00-19:00 UTC only.
- Freeze window: Thursday 22:00 UTC to Monday 07:00 UTC.
- Emergency exception during freeze: active `P1` incident and incident commander approval required.

## 6. Rollback Triggers (Updated)

Invoke GitHub Actions `rollback-deploy` workflow when any condition occurs:

1. Error rate >2.5% for 5 consecutive minutes.
2. p95 latency >25% above 7-day baseline for 10 minutes.
3. 2 consecutive failed synthetic checks in any production region.
4. Any production data validation failure with severity `high` or `critical`.

## 7. Approvals (Updated)

Apply approval gates in both Jira and GitHub Actions (`company_sim/tool_configs/jira.yaml`, `company_sim/tool_configs/github_actions.yaml`).

- Standard production deploy: 2 approvals and approved Jira `OPS` Change issue.
- High-risk change or destructive SQL: 3 approvals (service owner, SRE on-call, engineering manager).
- Emergency deploy: 1 approval (incident commander) plus retrospective manager approval within 12 hours.

## 8. Audit Logging Requirements (Expanded)

- Incident timelines must be updated in Jira within 5 minutes of major actions.
- Every deployment and rollback must post to `#audit-ops` with run URL and linked Jira key.
- Postgres audit tables in `ops_audit` must be populated within 10 minutes.
- Daily audit reconciliation must verify parity across Jira, Slack, GitHub Actions, and Postgres logs.

## 9. Change Log from v1 to v2

At least the following controls changed:

1. Escalation timings tightened for P1/P2/P3.
2. Incident communication cadence increased (P1: 15m -> 10m, P2: 30m -> 20m).
3. Change windows shifted and freeze start moved earlier.
4. Rollback thresholds tightened (lower error/latency thresholds and faster trigger windows).
5. Approval rules tightened for high-risk/destructive SQL.
6. Audit logging deadlines tightened and daily reconciliation added.
