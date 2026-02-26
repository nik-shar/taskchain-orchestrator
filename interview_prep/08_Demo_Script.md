# Live Demo Script

tags: #demo #runbook

## Goal
Show a complete task run and explain reliability controls in under 8 minutes.

## Pre-demo Checklist
- Virtual env active.
- Dependencies installed.
- PostgreSQL reachable.
- App starts with `make run`.

## Demo Flow
1. Start with architecture statement.
2. Show health and tools.
3. Create task.
4. Run task.
5. Inspect stored artifacts and verification.
6. Explain deterministic vs LLM mode switch.

## Commands
```bash
make run
```

In another terminal:
```bash
curl -sS http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8000/tools
```

Create:
```bash
curl -sS -X POST http://127.0.0.1:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "task": "P1 alert: checkout API latency and errors. Investigate incident evidence and provide escalation steps with policy citations.",
    "context": {
      "service": "saas-api",
      "severity": "P1",
      "start_time": "2026-02-14T10:00:00Z",
      "end_time": "2026-02-14T10:30:00Z"
    }
  }'
```

Run:
```bash
curl -sS -X POST http://127.0.0.1:8000/tasks/<TASK_ID>/run \
  -H "Content-Type: application/json" \
  -d '{}'
```

Fetch:
```bash
curl -sS http://127.0.0.1:8000/tasks/<TASK_ID>
```

## Narration Prompts During Demo
- "Plan is typed and explicit before execution."
- "Each tool call is validated and timed."
- "Verifier is the quality gate; success requires evidence for incident flows."
- "All artifacts are persisted for traceability."

## Backup Plan if Something Fails
1. Show `/health` and `/tools` to prove service is alive.
2. Run a simpler deterministic task:
   - "Prepare executive update for Atlas migration with risks."
3. Explain failure mode transparently and show verifier reasons.

See: [[02_Architecture_Deep_Dive]], [[05_LLM_Integration_Story]]

