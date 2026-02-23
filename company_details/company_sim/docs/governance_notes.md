# Governance Notes for AI Operations Agent

These notes define how an enterprise AI operations agent should execute tasks in this simulation.

## Evidence and Citation Rules

1. Any operational decision must cite at least one policy file and one tool config file.
2. If escalation or approvals are involved, cite `company_sim/tool_configs/oncall_rota.yaml` and `company_sim/tool_configs/jira.yaml`.
3. If communication routing is involved, cite `company_sim/tool_configs/slack.yaml`.
4. If deployment or rollback actions are involved, cite `company_sim/tool_configs/github_actions.yaml`.
5. If database access/control is involved, cite `company_sim/tool_configs/postgres.yaml`.

## Reporting Consistency

- Incident channels must align with the Slack config.
- Ticket references must use Jira keys from the Jira config.
- Escalation targets must follow the on-call rota and escalation order.

## Control Objective

The AI agent should produce outputs that are auditable, minimally ambiguous, and traceable to named controls in policy and config files.
