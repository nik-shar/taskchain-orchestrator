from types import SimpleNamespace

from agent_orchestrator.graph.nodes import execute
import agent_orchestrator.tools.llm as llm_module
import agent_orchestrator.tools.registry as registry_module
from agent_orchestrator.tools.registry import RegistryResolution, ToolSpec, resolve_registry
from agent_orchestrator.tools.schemas import (
    BuildIncidentBriefInput,
    BuildIncidentBriefOutput,
    SummarizeInput,
    SummarizeOutput,
)


def test_step8_execute_node_uses_llm_registry_when_available(monkeypatch) -> None:
    def fake_llm_summary(payload: SummarizeInput) -> SummarizeOutput:
        return SummarizeOutput(summary=f"LLM summary: {payload.text[:30]}")

    llm_registry = {
        "summarize": ToolSpec(
            input_model=SummarizeInput,
            output_model=SummarizeOutput,
            fn=fake_llm_summary,
            implementation="llm",
        )
    }

    def fake_resolve_registry(**kwargs):
        return RegistryResolution(
            registry=llm_registry,
            requested_mode="llm",
            effective_mode="llm",
            fallback_reason=None,
        )

    monkeypatch.setattr(execute, "resolve_registry", fake_resolve_registry)
    monkeypatch.setattr(
        execute,
        "get_settings",
        lambda: SimpleNamespace(
            executor_mode="llm",
            llm_provider="openai",
            llm_model="gpt-4o-mini",
            llm_base_url="https://api.openai.com/v1",
            llm_timeout_s=8.0,
            llm_max_retries=1,
            llm_backoff_s=0.2,
            resolved_openai_api_key=lambda: "dummy",
            tool_timeout_s=2.0,
            tool_max_retries=1,
            tool_retry_backoff_s=0.0,
        ),
    )

    state = {
        "task_id": "step8-1",
        "user_input": "Investigate checkout incident quickly",
        "plan_steps": [{"id": "s1", "tool": "summarize", "status": "pending"}],
        "tool_results": {},
        "telemetry": {},
        "retry_count": 0,
    }
    result = execute.run(state)

    assert result["tool_results"]["summarize"]["status"] == "ok"
    assert result["tool_results"]["summarize"]["implementation"] == "llm"
    assert result["telemetry"]["executor"]["effective_mode"] == "llm"


def test_step8_registry_falls_back_when_llm_key_missing() -> None:
    resolution = resolve_registry(
        requested_mode="llm",
        provider="openai",
        api_key="",
        model="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        timeout_s=8.0,
        max_retries=1,
        backoff_s=0.2,
    )

    assert resolution.effective_mode == "deterministic"
    assert resolution.fallback_reason


def test_step8_registry_enables_llm_incident_brief_when_available(monkeypatch) -> None:
    monkeypatch.setattr(
        registry_module,
        "build_openai_summarize_tool",
        lambda **_kwargs: (lambda payload: SummarizeOutput(summary=payload.text[:20])),
    )
    monkeypatch.setattr(
        registry_module,
        "build_openai_incident_brief_tool",
        lambda **_kwargs: (
            lambda payload: BuildIncidentBriefOutput(
                summary=f"LLM brief for {payload.query[:20]}",
                similar_incidents=[],
                probable_causes=["Likely upstream dependency issue."],
                recommended_actions=["Escalate and monitor."],
                escalation_recommendation="Escalate to on-call immediately.",
                confidence=0.71,
                citations=[],
            )
        ),
    )

    resolution = resolve_registry(
        requested_mode="llm",
        provider="openai",
        api_key="dummy",
        model="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        timeout_s=8.0,
        max_retries=1,
        backoff_s=0.2,
    )

    assert resolution.effective_mode == "llm"
    assert resolution.registry["summarize"].implementation == "llm"
    assert resolution.registry["build_incident_brief"].implementation == "llm"


def test_step8_execute_node_runs_llm_incident_brief(monkeypatch) -> None:
    def fake_llm_incident_brief(payload: BuildIncidentBriefInput) -> BuildIncidentBriefOutput:
        return BuildIncidentBriefOutput(
            summary=f"LLM brief: {payload.query[:30]}",
            similar_incidents=[issue.ticket for issue in payload.previous_issues if issue.ticket][
                :2
            ],
            probable_causes=["Likely image rendering failure path."],
            recommended_actions=["Validate profile media dependency and escalate."],
            escalation_recommendation="Escalate to service owner and on-call.",
            confidence=0.82,
            citations=[],
        )

    llm_registry = {
        "build_incident_brief": ToolSpec(
            input_model=BuildIncidentBriefInput,
            output_model=BuildIncidentBriefOutput,
            fn=fake_llm_incident_brief,
            implementation="llm",
        )
    }

    monkeypatch.setattr(
        execute,
        "resolve_registry",
        lambda **_kwargs: RegistryResolution(
            registry=llm_registry,
            requested_mode="llm",
            effective_mode="llm",
            fallback_reason=None,
        ),
    )
    monkeypatch.setattr(
        execute,
        "get_settings",
        lambda: SimpleNamespace(
            executor_mode="llm",
            llm_provider="openai",
            llm_model="gpt-4o-mini",
            llm_base_url="https://api.openai.com/v1",
            llm_timeout_s=8.0,
            llm_max_retries=1,
            llm_backoff_s=0.2,
            resolved_openai_api_key=lambda: "dummy",
            tool_timeout_s=2.0,
            tool_max_retries=1,
            tool_retry_backoff_s=0.0,
        ),
    )

    state = {
        "task_id": "step8-brief",
        "user_input": "P1 incident: profile picture requests failing",
        "plan_steps": [{"id": "b1", "tool": "build_incident_brief", "status": "pending"}],
        "tool_results": {
            "search_incident_knowledge": {
                "status": "ok",
                "data": {"results": [{"title": "Policy", "snippet": "Escalate on P1."}]},
            },
            "search_previous_issues": {
                "status": "ok",
                "data": {
                    "results": [
                        {
                            "ticket": "WLC-43",
                            "summary": "User profile picture doesn't display",
                            "relevance": 0.91,
                        }
                    ]
                },
            },
        },
        "telemetry": {},
        "retry_count": 0,
    }
    result = execute.run(state)

    assert result["tool_results"]["build_incident_brief"]["status"] == "ok"
    assert result["tool_results"]["build_incident_brief"]["implementation"] == "llm"
    assert "LLM brief" in result["tool_results"]["build_incident_brief"]["data"]["summary"]


def test_step8_llm_incident_brief_parser_normalizes_similar_incident_dicts() -> None:
    response_json = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"summary":"Incident brief","similar_incidents":'
                        '[{"ticket":"WLC-43","summary":"User profile picture doesn\'t display"},'
                        '{"ticket":"STL-1157","summary":"Avatar upload intermittently fails"}],'
                        '"probable_causes":"Cache inconsistency in media path",'
                        '"recommended_actions":["Invalidate cache","Escalate to on-call"],'
                        '"escalation_recommendation":"Escalate immediately",'
                        '"confidence":"0.77",'
                        '"citations":[{"ticket":"WLC-43","summary":"User profile picture doesn\'t display"}]}'
                    )
                }
            }
        ]
    }

    parsed = llm_module._parse_incident_brief(response_json)

    assert parsed.summary == "Incident brief"
    assert parsed.similar_incidents[0].startswith("WLC-43:")
    assert parsed.similar_incidents[1].startswith("STL-1157:")
    assert parsed.probable_causes == ["Cache inconsistency in media path"]
    assert parsed.escalation_recommendation == "Escalate immediately"
    assert parsed.confidence == 0.77
    assert parsed.citations[0].reference == "WLC-43"
