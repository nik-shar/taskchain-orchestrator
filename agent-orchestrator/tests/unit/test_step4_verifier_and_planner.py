from agent_orchestrator.graph.nodes import execute, plan, retrieve, verify


def test_planner_llm_mode_falls_back_to_deterministic(monkeypatch) -> None:
    def _fail_llm_plan(*_args, **_kwargs):
        raise RuntimeError("forced planner failure")

    monkeypatch.setattr(plan, "_build_llm_plan", _fail_llm_plan)

    state = {
        "task_id": "t1",
        "mode": "llm",
        "user_input": "Investigate incident in Payments service",
        "telemetry": {},
    }

    result = plan.run(state)

    planner_meta = result["telemetry"]["planner"]
    assert planner_meta["requested_mode"] == "llm"
    assert planner_meta["effective_mode"] == "deterministic"
    assert planner_meta["fallback_used"] is True


def test_verifier_incident_gate_fails_without_retrieval_evidence() -> None:
    state = {
        "user_input": "Production incident with high latency",
        "tool_results": {
            "summarize": {
                "status": "ok",
                "data": {"summary": "Production incident with high latency"},
            },
            "extract_entities": {"status": "ok", "data": {"entities": ["Production"]}},
            "classify_priority": {"status": "ok", "data": {"priority": "high", "reasons": []}},
        },
        "retry_count": 0,
        "retry_budget": 2,
    }

    result = verify.run(state)

    assert result["verification"]["passed"] is False
    failures = result["verification"]["gate_failures"]
    assert "missing_incident_knowledge_evidence" in failures
    assert "missing_previous_issue_evidence" in failures
    assert "missing_policy_citation" in failures


def test_verifier_incident_gate_fails_on_missing_citation_metadata() -> None:
    state = {
        "user_input": "Production incident with high latency",
        "tool_results": {
            "summarize": {
                "status": "ok",
                "data": {"summary": "Production incident with high latency"},
            },
            "extract_entities": {"status": "ok", "data": {"entities": ["Production"]}},
            "classify_priority": {"status": "ok", "data": {"priority": "high", "reasons": []}},
            "search_incident_knowledge": {
                "status": "ok",
                "data": {
                    "results": [
                        {
                            "title": "Runbook: Checkout Incident Response",
                            "snippet": "",
                            "source_id": "",
                        }
                    ]
                },
            },
            "search_previous_issues": {
                "status": "ok",
                "data": {"results": [{"summary": "", "ticket": ""}]},
            },
        },
        "retry_count": 0,
        "retry_budget": 2,
    }

    result = verify.run(state)
    failures = result["verification"]["gate_failures"]
    assert "missing_incident_citation_metadata" in failures
    assert "missing_incident_snippet_evidence" in failures
    assert "missing_previous_issue_citation_metadata" in failures
    assert "missing_previous_issue_snippet_evidence" in failures


def test_step4_incident_flow_passes_verifier_gates() -> None:
    state = {
        "task_id": "t2",
        "mode": "deterministic",
        "executor_mode": "deterministic",
        "user_input": "Incident in Payments service causing latency",
        "plan_steps": [],
        "tool_results": {},
        "telemetry": {},
        "retry_count": 0,
        "retry_budget": 2,
    }

    planned = plan.run(state)
    state.update(planned)
    state.update(retrieve.run(state))
    state.update(execute.run(state))
    result = verify.run(state)

    assert result["verification"]["passed"] is True
    assert result["verification"]["gate_failures"] == []
    assert state["tool_results"]["build_incident_brief"]["status"] == "ok"
    brief = state["tool_results"]["build_incident_brief"]["data"]
    assert brief["summary"]
    assert isinstance(brief.get("recommended_actions"), list)
    assert isinstance(brief.get("citations"), list)


def test_execute_reruns_failed_tool_on_retry_iteration() -> None:
    state = {
        "task_id": "t3",
        "user_input": "Investigate incident in Payments",
        "executor_mode": "deterministic",
        "plan_steps": [
            {"id": "analyze", "tool": "summarize", "status": "pending"},
        ],
        "tool_results": {
            "summarize": {
                "status": "failed",
                "error": "previous timeout",
                "attempts": 2,
                "duration_ms": 100.0,
            }
        },
        "telemetry": {},
        "retry_count": 1,
    }

    result = execute.run(state)

    assert result["tool_results"]["summarize"]["status"] == "ok"
    assert result["telemetry"]["tool_execution"]["events"][-1]["iteration"] == 1
