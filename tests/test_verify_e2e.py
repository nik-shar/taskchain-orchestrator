"""End-to-end plan -> execute -> verify(retry) loop against a real Docker sandbox.

Unlike the unit tests, nothing here is faked except the model: the Executor really writes
files, the Verifier really runs the repository's test command inside a container, and the
gate really is that command's exit code. A fixture repository with a genuine bug is used,
and the first attempt intentionally leaves the bug in place so the retry path is exercised.

Requires a Docker daemon; skipped otherwise (`-m 'not docker'` to deselect).
"""
from unittest.mock import MagicMock

import pytest

import agent.orchestrator as orchestrator_module
import config
from agent.orchestrator import Orchestrator, clear_sessions
from utils.sandbox import is_docker_available

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(not is_docker_available(), reason="requires a running Docker daemon"),
]

BUGGY_APP = "def add(a, b):\n    return a - b\n"
FIXED_APP = "def add(a, b):\n    return a + b\n"

TEST_APP = (
    "import unittest\n"
    "\n"
    "from app import add\n"
    "\n"
    "\n"
    "class TestAdd(unittest.TestCase):\n"
    "    def test_add(self):\n"
    "        self.assertEqual(add(2, 3), 5)\n"
    "\n"
    "\n"
    "if __name__ == '__main__':\n"
    "    unittest.main()\n"
)


class FakePlanner:
    def __init__(self, *args, **kwargs):
        pass

    def plan(self, repo_id, issue_description, context=None):
        return {"repo_id": repo_id, "issue": issue_description, "plan": "make add() add"}


def _response(content: str) -> MagicMock:
    return MagicMock(choices=[MagicMock(message=MagicMock(content=content))])


@pytest.fixture
def fixture_repo(tmp_path, monkeypatch):
    """A workspace whose test suite genuinely fails until the patch is correct."""
    monkeypatch.setattr(config, "WORKTREES_DIR", tmp_path / "worktrees")
    monkeypatch.setattr(config, "SANDBOX_TEST_COMMAND", "python -m unittest discover -q")

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "app.py").write_text(BUGGY_APP)
    (workspace / "test_app.py").write_text(TEST_APP)

    monkeypatch.setattr(orchestrator_module, "Planner", FakePlanner)
    monkeypatch.setattr(orchestrator_module, "get_workspace", lambda repo_id: workspace)
    clear_sessions()
    return workspace


def _install_model(monkeypatch, executor_payloads):
    """Route model calls by system prompt: executor gets the queue, verifier gets a review."""
    state = {"executor_calls": 0}

    def fake_create(**kwargs):
        system = kwargs["messages"][0]["content"]
        if "coding agent" in system:
            index = min(state["executor_calls"], len(executor_payloads) - 1)
            state["executor_calls"] += 1
            return _response(executor_payloads[index])
        return _response("Advisory review of the patch.")

    client = MagicMock()
    client.chat.completions.create.side_effect = fake_create
    monkeypatch.setattr("agent.executor.build_llm_client", lambda *a, **k: client)
    monkeypatch.setattr("agent.verifier.build_llm_client", lambda *a, **k: client)
    return state


def test_loop_retries_after_real_test_failure_then_passes(fixture_repo, monkeypatch):
    # Attempt 1 writes the same buggy body, so the real test run must fail.
    _install_model(
        monkeypatch,
        [
            '{"edits": [{"path": "app.py", "content": "def add(a, b):\\n    return a - b\\n"}],'
            ' "rationale": "no-op attempt"}',
            '{"edits": [{"path": "app.py", "content": "def add(a, b):\\n    return a + b\\n"}],'
            ' "rationale": "real fix"}',
        ],
    )

    session = Orchestrator().run_fix("owner/repo", "add() returns the wrong result", max_attempts=2)

    assert session.attempts == 2, session.history
    assert session.history[0]["verification_status"] == "failed"
    assert session.history[1]["verification_status"] == "passed"
    assert session.status == "passed"

    verification = session.verification
    assert verification["test_command"] == "python -m unittest discover -q"
    assert verification["exit_code"] == 0
    # Evidence comes from the repository's own suite, not from the model.
    assert "OK" in verification["test_output"] or "Ran 1 test" in verification["test_output"]

    execution = session.execution
    assert execution["files_changed"] == ["app.py"]
    assert "+    return a + b" in execution["diff"]
    # The patch really landed in the worktree on disk.
    worktrees = fixture_repo.parent / "worktrees" / "owner" / "repo"
    patched = sorted(worktrees.glob("*/app.py"))
    assert patched, "expected a worktree containing the patched app.py"
    assert "return a + b" in patched[-1].read_text()


def test_failing_tests_are_reported_as_failed_not_passed(fixture_repo, monkeypatch):
    """With no usable fix available, verification must fail rather than self-certify."""
    _install_model(
        monkeypatch,
        [
            '{"edits": [{"path": "app.py", "content": "def add(a, b):\\n    return a - b\\n"}]}',
        ],
    )

    session = Orchestrator().run_fix("owner/repo", "add() returns the wrong result", max_attempts=1)

    assert session.status == "failed"
    verification = session.verification
    assert verification["exit_code"] != 0
    assert "FAILED" in verification["test_output"] or "failures=1" in verification["test_output"]
    assert "Tests failed" in verification["summary"]
