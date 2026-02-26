# Roadmap and Risks

tags: #roadmap #risks #production

## Near-term Roadmap
1. Expand toolset for broader enterprise workflows.
2. Strengthen verification beyond structural checks (cross-step consistency, contradiction checks).
3. Improve reliability and observability (better run tracing, metrics, alerting).
4. Production deployment path on Cloud Run with managed Postgres/Cloud SQL.

## Current Risks
- Prompt/schema drift in LLM mode can still produce near-valid but weak outputs.
- Synchronous execution model may limit throughput for heavy tool workloads.
- Retrieval quality depends on corpus freshness and metadata quality.
- Cloud deployment hardening (secrets, scaling, SLO telemetry) still pending.

## Mitigation Plan
- Add contract tests around LLM structured outputs.
- Add queue-based async workers for long-running tools.
- Add data/index refresh pipeline and retrieval evaluation dashboards.
- Add production readiness checklist: health probes, structured logging, rate limits, alerting.

## Good Interview Framing
> [!note]
> "I intentionally prioritized a reliable local vertical slice and testability. The next phase is operational maturity: observability, scaling, and cloud-hardening."

Links: [[03_Key_Design_Decisions]], [[04_Testing_Strategy]]

