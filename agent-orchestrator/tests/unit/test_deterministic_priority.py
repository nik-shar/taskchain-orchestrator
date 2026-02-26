from agent_orchestrator.tools.deterministic import classify_priority
from agent_orchestrator.tools.schemas import ClassifyPriorityInput


def test_explicit_priority_major_overrides_backlog_status() -> None:
    text = (
        "Bu\n"
        "Priority: Major\n"
        "Status: Long Term Backlog\n"
        "Summary: Having non-ASCII characters in the JSON body representation sent"
    )

    result = classify_priority(ClassifyPriorityInput(text=text))

    assert result.priority == "high"
    assert result.reasons
    assert "explicit priority 'major'" in result.reasons[0]


def test_status_used_when_priority_absent() -> None:
    text = "Status: Long Term Backlog\nSummary: polish docs"

    result = classify_priority(ClassifyPriorityInput(text=text))

    assert result.priority == "low"
    assert result.reasons
    assert "explicit status 'long term backlog'" in result.reasons[0]


def test_priority_code_is_parsed() -> None:
    result = classify_priority(ClassifyPriorityInput(text="Priority: P1"))

    assert result.priority == "high"
    assert result.reasons
    assert "explicit priority 'p1'" in result.reasons[0]
