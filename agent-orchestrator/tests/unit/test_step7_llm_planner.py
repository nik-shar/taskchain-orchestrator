from agent_orchestrator.graph.nodes import plan


def test_step7_llm_mode_uses_llm_plan_when_available(monkeypatch) -> None:
    def fake_llm_plan(user_input: str, *, settings):
        return [
            {
                "id": "llm_1",
                "tool": "extract_entities",
                "status": "pending",
                "args": {"text": user_input},
            },
            {
                "id": "llm_2",
                "tool": "summarize",
                "status": "pending",
                "args": {"text": user_input, "max_words": 40},
            },
        ]

    monkeypatch.setattr(plan, "_build_llm_plan", fake_llm_plan)

    result = plan.run(
        {
            "task_id": "t-llm",
            "mode": "llm",
            "user_input": "Need incident analysis for checkout errors",
            "telemetry": {},
        }
    )

    planner_meta = result["telemetry"]["planner"]
    assert planner_meta["effective_mode"] == "llm"
    assert planner_meta["fallback_used"] is False

    tools = [step["tool"] for step in result["plan_steps"]]
    assert tools[-1] == "summarize"
    assert "classify_priority" in tools
    assert "search_incident_knowledge" in tools
    assert "search_previous_issues" in tools
    assert "build_incident_brief" in tools


def test_step7_llm_mode_fallback_still_deterministic(monkeypatch) -> None:
    def fail_llm_plan(user_input: str, *, settings):
        raise RuntimeError("simulated llm failure")

    monkeypatch.setattr(plan, "_build_llm_plan", fail_llm_plan)

    result = plan.run(
        {
            "task_id": "t-llm-fallback",
            "mode": "llm",
            "user_input": "Prepare release summary for Atlas",
            "telemetry": {},
        }
    )

    planner_meta = result["telemetry"]["planner"]
    assert planner_meta["effective_mode"] == "deterministic"
    assert planner_meta["fallback_used"] is True

    tools = [step["tool"] for step in result["plan_steps"]]
    assert "summarize" in tools
    assert "extract_entities" in tools
    assert "classify_priority" in tools


def test_step7_llm_mode_normalizes_sparse_or_noisy_args(monkeypatch) -> None:
    def fake_llm_plan(_user_input: str, *, settings):
        return [
            {
                "id": "llm_1",
                "tool": "classify_priority",
                "status": "pending",
                "args": {},
            },
            {
                "id": "llm_2",
                "tool": "search_incident_knowledge",
                "status": "pending",
                "args": {"foo": "bar"},
            },
            {
                "id": "llm_3",
                "tool": "search_previous_issues",
                "status": "pending",
                "args": {},
            },
            {
                "id": "llm_4",
                "tool": "summarize",
                "status": "pending",
                "args": {"foo": "bar"},
            },
        ]

    monkeypatch.setattr(plan, "_build_llm_plan", fake_llm_plan)

    user_input = "P1 incident: user profile picture related general issues"
    result = plan.run(
        {
            "task_id": "t-llm-args",
            "mode": "llm",
            "user_input": user_input,
            "telemetry": {},
        }
    )

    step_map = {step["tool"]: step for step in result["plan_steps"]}
    assert step_map["classify_priority"]["args"] == {"text": user_input}
    assert step_map["search_incident_knowledge"]["args"] == {"query": user_input, "limit": 3}
    assert step_map["search_previous_issues"]["args"] == {"query": user_input, "limit": 3}
    assert step_map["build_incident_brief"]["args"]["query"] == user_input
    assert step_map["summarize"]["args"]["text"] == user_input
    assert step_map["summarize"]["args"]["max_words"] > 0
    assert "foo" not in step_map["summarize"]["args"]
