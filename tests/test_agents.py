from unittest.mock import patch, MagicMock

from agent.planner import Planner
from agent.executor import Executor
from agent.verifier import Verifier


def test_planner_returns_plan():
    planner = Planner(model="gpt-4o-mini")
    with patch.object(planner.client.chat.completions, "create") as mock_create:
        mock_create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="1. Find auth.\n2. Fix it."))]
        )
        plan = planner.plan("owner/repo", "Auth is broken")
    assert plan["repo_id"] == "owner/repo"
    assert "Find auth" in plan["plan"]


def test_executor_returns_diff():
    executor = Executor(repo_id="owner/repo", model="gpt-4o-mini")
    with patch.object(executor.client.chat.completions, "create") as mock_create:
        mock_create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="```diff\n+ fix\n```"))]
        )
        result = executor.execute({"plan": "Fix auth"})
    assert result["repo_id"] == "owner/repo"
    assert "fix" in result["diff"]


def test_verifier_returns_review():
    verifier = Verifier(repo_id="owner/repo", model="gpt-4o-mini")
    with patch.object(verifier.client.chat.completions, "create") as mock_create:
        mock_create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="Looks good."))]
        )
        result = verifier.verify({"diff": "+ fix"}, issue_description="Auth bug")
    assert result["status"] == "passed"
    assert "Looks good" in result["review"]
