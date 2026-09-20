"""Tests for the planner, which TaskChain exposes as a `suggest_plan` MCP tool."""
from unittest.mock import MagicMock, patch

from agent.planner import Planner


def test_planner_returns_plan():
    planner = Planner(model="gpt-4o-mini")
    with patch.object(planner.client.chat.completions, "create") as mock_create:
        mock_create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="1. Find auth.\n2. Fix it."))]
        )
        plan = planner.plan("owner/repo", "Auth is broken")
    assert plan["repo_id"] == "owner/repo"
    assert "Find auth" in plan["plan"]


def test_planner_passes_context_through():
    planner = Planner(model="gpt-4o-mini")
    with patch.object(planner.client.chat.completions, "create") as mock_create:
        mock_create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="1. Do the thing."))]
        )
        plan = planner.plan(
            "owner/repo",
            "Cache is stale",
            context={"dna_summary": "A demo repo", "related_issues": []},
        )
    assert plan["context"]["dna_summary"] == "A demo repo"
    prompt = mock_create.call_args.kwargs["messages"][1]["content"]
    assert "A demo repo" in prompt


def test_planner_falls_back_when_llm_fails():
    planner = Planner(model="gpt-4o-mini")
    with patch.object(planner.client.chat.completions, "create", side_effect=RuntimeError("boom")):
        plan = planner.plan("owner/repo", "Auth is broken")
    assert "Apply the smallest change" in plan["plan"]
