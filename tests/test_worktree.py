"""Tests for the isolated-worktree substrate."""
import subprocess

import pytest

import config
from agent.worktree import (
    apply_patch,
    cleanup_worktree,
    create_worktree,
    delete_file,
    safe_resolve,
    worktree_diff,
    worktree_files_changed,
    write_file,
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
    write_file(worktree, "src/app.py", "changed\n")
    # The invariant from code_tools: the indexed workspace stays read-only.
    assert (workspace / "src" / "app.py").read_text() == "def run():\n    return 1\n"
    assert (worktree / "src" / "app.py").read_text() == "changed\n"


def test_create_worktree_requires_an_existing_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKTREES_DIR", tmp_path / "worktrees")
    with pytest.raises(FileNotFoundError):
        create_worktree(tmp_path / "nope", "owner/repo", "run1")


def test_write_file_creates_parents(worktree):
    result = write_file(worktree, "src/deep/new.py", "x = 1\n")
    assert result.ok is True
    assert (worktree / "src" / "deep" / "new.py").read_text() == "x = 1\n"


def test_delete_file(worktree):
    result = delete_file(worktree, "README.md")
    assert result.applied == ["README.md"]
    assert not (worktree / "README.md").exists()


def test_delete_missing_file_is_an_error(worktree):
    result = delete_file(worktree, "nope.py")
    assert result.applied == []
    assert "cannot delete missing file" in result.errors[0]


@pytest.mark.parametrize("bad_path", ["../../etc/passwd", "../evil.py", "/etc/passwd"])
def test_path_escape_is_rejected(worktree, bad_path):
    assert write_file(worktree, bad_path, "x").applied == []
    assert delete_file(worktree, bad_path).applied == []
    assert safe_resolve(worktree, bad_path) is None


def test_apply_patch(worktree):
    diff = (
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def run():\n"
        "-    return 1\n"
        "+    return 3\n"
    )
    result = apply_patch(worktree, diff)
    assert result.applied == ["src/app.py"]
    assert "return 3" in (worktree / "src" / "app.py").read_text()


def test_apply_patch_rejects_bad_patch_without_writing(worktree):
    before = (worktree / "src" / "app.py").read_text()
    result = apply_patch(worktree, "--- a/nope.py\n+++ b/nope.py\n@@\n-x\n+y\n")
    assert result.applied == []
    assert "failed" in result.errors[0]
    assert (worktree / "src" / "app.py").read_text() == before


def test_worktree_diff_reports_only_caller_changes(worktree):
    write_file(worktree, "src/app.py", "def run():\n    return 42\n")
    diff = worktree_diff(worktree)
    assert "+    return 42" in diff
    assert "-    return 1" in diff
    assert worktree_files_changed(worktree) == ["src/app.py"]


def test_cleanup_worktree(worktree):
    cleanup_worktree(worktree)
    assert not worktree.exists()
