from unittest.mock import MagicMock, patch

from agent.executor import Executor, parse_model_output
from agent.planner import Planner
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


def test_planner_falls_back_when_llm_fails():
    planner = Planner(model="gpt-4o-mini")
    with patch.object(planner.client.chat.completions, "create", side_effect=RuntimeError("boom")):
        plan = planner.plan("owner/repo", "Auth is broken")
    assert "Apply the smallest change" in plan["plan"]


def test_parse_model_output_reads_edits_and_rationale():
    parsed = parse_model_output(
        'Sure!\n{"edits": [{"path": "a.py", "content": "x"}], "rationale": "why"}'
    )
    assert parsed["error"] is None
    assert parsed["edits"][0]["path"] == "a.py"
    assert parsed["rationale"] == "why"


def test_parse_model_output_accepts_fenced_diff():
    parsed = parse_model_output("```diff\n--- a/x.py\n+++ b/x.py\n@@\n-old\n+new\n```")
    assert parsed["error"] is None
    assert parsed["edits"] == []
    assert parsed["diff"].startswith("--- a/x.py")


def test_parse_model_output_reports_unusable_response():
    parsed = parse_model_output("I cannot help with that.")
    assert parsed["edits"] == []
    assert parsed["error"] == "model returned no usable edits"


def test_executor_without_workspace_fails_cleanly():
    executor = Executor(repo_id="owner/repo", model="gpt-4o-mini")
    result = executor.execute({"plan": "Fix auth"})
    assert result["status"] == "failed"
    assert result["files_changed"] == []
    assert "workspace not available" in result["errors"][0]


def test_verifier_without_worktree_is_not_run():
    verifier = Verifier(repo_id="owner/repo", model="gpt-4o-mini")
    with patch.object(verifier.client.chat.completions, "create") as mock_create:
        mock_create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="Looks reasonable."))]
        )
        result = verifier.verify({"diff": "", "status": "failed"}, issue_description="Auth bug")

    # No tests ran, so this must not be reported as verified.
    assert result["status"] == "not_run"
    assert result["test_command"] is None
    assert "unverified" in result["summary"]
    assert "Looks reasonable" in result["review"]
