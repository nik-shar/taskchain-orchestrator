"""Tests for patch application in an isolated worktree."""
import subprocess
from unittest.mock import MagicMock, patch

import pytest

import config
from agent.executor import Executor
from agent.patch_tools import (
    apply_edits,
    apply_unified_diff,
    cleanup_worktree,
    create_worktree,
    worktree_diff,
    worktree_files_changed,
)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A small workspace plus an isolated worktree root."""
    monkeypatch.setattr(config, "WORKTREES_DIR", tmp_path / "worktrees")
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "app.py").write_text("def run():\n    return 1\n")
    (ws / "README.md").write_text("# Demo\n")
    return ws


@pytest.fixture
def worktree(workspace):
    return create_worktree(workspace, "owner/repo", "run1")


def _git_log(worktree) -> str:
    return subprocess.run(
        ["git", "-C", str(worktree), "log", "--oneline"],
        capture_output=True,
        text=True,
    ).stdout


def test_create_worktree_copies_workspace_and_commits_baseline(worktree):
    assert (worktree / "src" / "app.py").read_text() == "def run():\n    return 1\n"
    assert "baseline" in _git_log(worktree)


def test_workspace_is_never_mutated(worktree, workspace):
    apply_edits(worktree, [{"path": "src/app.py", "content": "changed\n"}])
    # The invariant from code_tools: the indexed workspace stays read-only.
    assert (workspace / "src" / "app.py").read_text() == "def run():\n    return 1\n"
    assert (worktree / "src" / "app.py").read_text() == "changed\n"


def test_content_edit_writes_file(worktree):
    result = apply_edits(worktree, [{"path": "src/new.py", "content": "x = 1\n"}])
    assert result.ok is True
    assert result.applied == ["src/new.py"]
    assert (worktree / "src" / "new.py").read_text() == "x = 1\n"


def test_find_replace_edit(worktree):
    result = apply_edits(
        worktree,
        [{"path": "src/app.py", "find": "return 1", "replace": "return 2"}],
    )
    assert result.ok is True
    assert "return 2" in (worktree / "src" / "app.py").read_text()


def test_find_replace_requires_exact_match(worktree):
    result = apply_edits(
        worktree,
        [{"path": "src/app.py", "find": "return 999", "replace": "return 2"}],
    )
    assert result.applied == []
    assert "'find' text not present" in result.errors[0]


def test_delete_edit(worktree):
    result = apply_edits(worktree, [{"path": "README.md", "delete": True}])
    assert result.applied == ["README.md"]
    assert not (worktree / "README.md").exists()


def test_path_escape_is_rejected(worktree):
    result = apply_edits(worktree, [{"path": "../../etc/passwd", "content": "x"}])
    assert result.applied == []
    assert "escapes worktree" in result.errors[0]


def test_good_edits_survive_bad_ones(worktree):
    result = apply_edits(
        worktree,
        [
            {"path": "src/new.py", "content": "ok\n"},
            {"path": "../../evil.py", "content": "no\n"},
            {"path": "src/app.py"},
        ],
    )
    assert result.applied == ["src/new.py"]
    assert len(result.errors) == 2



def test_worktree_diff_only_shows_agent_edits(worktree):
    apply_edits(worktree, [{"path": "src/app.py", "find": "return 1", "replace": "return 42"}])
    diff = worktree_diff(worktree)
    assert "+    return 42" in diff
    assert "-    return 1" in diff
    assert worktree_files_changed(worktree) == ["src/app.py"]


def test_apply_unified_diff(worktree):
    diff = (
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def run():\n"
        "-    return 1\n"
        "+    return 3\n"
    )
    result = apply_unified_diff(worktree, diff)
    assert result.applied == ["src/app.py"]
    assert "return 3" in (worktree / "src" / "app.py").read_text()


def test_apply_unified_diff_rejects_bad_patch(worktree):
    result = apply_unified_diff(worktree, "--- a/nope.py\n+++ b/nope.py\n@@\n-x\n+y\n")
    assert result.applied == []
    assert "failed" in result.errors[0]


def test_cleanup_worktree(worktree):
    cleanup_worktree(worktree)
    assert not worktree.exists()


def test_executor_applies_llm_edits(workspace):
    executor = Executor(
        repo_id="owner/repo", model="gpt-4o-mini", workspace=workspace, run_id="r1"
    )
    with patch.object(executor.client.chat.completions, "create") as mock_create:
        mock_create.return_value = MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        content=(
                            '{"edits": [{"path": "src/app.py", "find": "return 1",'
                            ' "replace": "return 99"}], "rationale": "fix"}'
                        )
                    )
                )
            ]
        )
        result = executor.execute({"plan": "make run return 99", "issue": "bug"}, attempt=1)

    assert result["status"] == "applied"
    assert result["files_changed"] == ["src/app.py"]
    assert "+    return 99" in result["diff"]
    assert result["errors"] == []


def test_executor_retry_restarts_from_baseline(workspace):
    """Each attempt gets a fresh copy, so diffs never stack across attempts."""
    executor = Executor(
        repo_id="owner/repo", model="gpt-4o-mini", workspace=workspace, run_id="r2"
    )
    with patch.object(executor.client.chat.completions, "create") as mock_create:
        mock_create.return_value = MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(content='{"edits": [{"path": "a.txt", "content": "1"}]}')
                )
            ]
        )
        first = executor.execute({"plan": "p"}, attempt=1)

        mock_create.return_value = MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(content='{"edits": [{"path": "b.txt", "content": "2"}]}')
                )
            ]
        )
        second = executor.execute({"plan": "p"}, attempt=2)

    assert first["files_changed"] == ["a.txt"]
    assert second["files_changed"] == ["b.txt"]
    assert "a.txt" not in second["diff"]
