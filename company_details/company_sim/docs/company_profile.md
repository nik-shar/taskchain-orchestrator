# Northstar Metrics (Fictional) - Company Profile

Northstar Metrics is a mid-size B2B SaaS company that provides workflow analytics and alerting for enterprise IT teams.

## Operating Snapshot

- Employees: 430
- Annual recurring revenue: USD 62M
- Regions: US, EU
- Customers: ~1,900 organizations
- Production footprint: Multi-tenant API and analytics pipelines

## Core Tooling

- Slack for operations coordination (`company_sim/tool_configs/slack.yaml`)
- Jira for incidents/changes/postmortems (`company_sim/tool_configs/jira.yaml`)
- Postgres for transactional and analytics data (`company_sim/tool_configs/postgres.yaml`)
- GitHub Actions for CI/CD and rollback workflows (`company_sim/tool_configs/github_actions.yaml`)
- Weekly on-call rota for SRE escalation (`company_sim/tool_configs/oncall_rota.yaml`)

## Governance Principles

Inspired by common code-of-conduct themes (integrity, accountability, and speak-up behavior), operations staff are expected to:

1. Escalate issues quickly when customer impact is uncertain.
2. Keep incident records complete and timestamped.
3. Prefer reversible, low-risk changes when service health is unstable.
4. Log all privileged and deployment actions to immutable audit channels.

## Policy Sources

- Baseline operational policy: `company_sim/policies/policy_v1.md`
- Updated policy: `company_sim/policies/policy_v2.md`
