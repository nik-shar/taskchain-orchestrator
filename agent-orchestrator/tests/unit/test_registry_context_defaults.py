from agent_orchestrator.tools.registry import default_args_for_tool


def test_classify_priority_defaults_use_structured_context() -> None:
    args = default_args_for_tool(
        "classify_priority",
        user_input="users report image upload errors",
        context={"priority": "Major", "severity": "SEV2", "status": "Long Term Backlog"},
    )

    assert "Priority: Major" in args["text"]
    assert "Severity: SEV2" in args["text"]
    assert "Status: Long Term Backlog" in args["text"]
    assert "Summary: users report image upload errors" in args["text"]


def test_retrieval_defaults_use_service_and_severity_context() -> None:
    args = default_args_for_tool(
        "search_previous_issues",
        user_input="checkout failures",
        context={"service": "checkout-api", "severity": "SEV2", "priority": "P1"},
    )

    assert args["query"] == "checkout failures"
    assert args["service"] == "checkout-api"
    assert args["severity"] == "SEV2"
