"""Tests for the MCP tool surface.

The tools are plain functions, so they are exercised directly. What matters here is the
contract: read-only context tools, an isolated worktree the client cannot escape, and a
sandbox that fails closed.
"""
import pytest

import config
from mcp_server import server as mcp_server


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Isolated worktree root plus a fake indexed workspace."""
    monkeypatch.setattr(config, "WORKTREES_DIR", tmp_path / "worktrees")
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "app.py").write_text("def run():\n    return 1\n")
    (ws / "README.md").write_text("# Demo\n")
    return ws


@pytest.fixture
def worktree_id(workspace, monkeypatch):
    monkeypatch.setattr(mcp_server, "get_workspace", lambda repo_id: workspace)
    return mcp_server.create_worktree("owner/repo", run_id="run1")["worktree_id"]


def test_tools_are_registered():
    """The integration surface is the product, so assert the exported tool set."""
    import asyncio

    tools = asyncio.run(mcp_server.mcp.list_tools())
    names = {tool.name for tool in tools}

    expected_context = {
        "list_indexed_repos",
        "index_repository",
        "repo_summary",
        "list_files",
        "read_file",
        "search_code",
        "search_issues",
        "repository_docs",
        "suggest_plan",
    }
    expected_execution = {
        "create_worktree",
        "write_file",
        "delete_file",
        "apply_patch",
        "sandbox_run",
        "suggested_test_command",
        "diff",
        "discard_worktree",
        "open_pull_request",
    }
    assert expected_context | expected_execution <= names


def test_no_tool_edits_the_read_only_workspace(worktree_id, workspace):
    """The point of the split: edits land in the worktree, never the indexed workspace."""
    mcp_server.write_file(worktree_id, "src/app.py", "changed\n")

    assert (workspace / "src" / "app.py").read_text() == "def run():\n    return 1\n"


def test_write_then_diff_reports_the_change(worktree_id):
    mcp_server.write_file(worktree_id, "src/app.py", "def run():\n    return 7\n")
    result = mcp_server.diff(worktree_id)

    assert result["files_changed"] == ["src/app.py"]
    assert "+    return 7" in result["diff"]


def test_apply_and_delete_file(worktree_id):
    assert mcp_server.delete_file(worktree_id, "README.md")["applied"] == ["README.md"]

    diff = (
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def run():\n"
        "-    return 1\n"
        "+    return 2\n"
    )
    patched = mcp_server.apply_patch(worktree_id, diff)
    # Reports the files this patch touched, not everything changed since the baseline.
    assert patched["applied"] == ["src/app.py"]


def test_bad_patch_is_reported_not_applied(worktree_id):
    result = mcp_server.apply_patch(worktree_id, "--- a/nope.py\n+++ b/nope.py\n@@\n-x\n+y\n")
    assert result["applied"] == []
    assert result["errors"]


def test_worktree_id_cannot_escape_the_worktree_root(worktree_id):
    """A client must not be able to aim the sandbox at an arbitrary host directory."""
    for hostile in ["../../../etc", "..", "../../..", "owner/repo/../../../tmp"]:
        with pytest.raises(ValueError):
            mcp_server.write_file(hostile, "passwd", "x")


def test_rejects_absolute_paths_inside_a_worktree(worktree_id):
    result = mcp_server.write_file(worktree_id, "/etc/passwd", "x")
    assert result["applied"] == []
    assert "escapes worktree" in result["errors"][0]


def test_unknown_worktree_id_is_rejected(workspace, monkeypatch):
    monkeypatch.setattr(config, "WORKTREES_DIR", workspace.parent / "worktrees")
    with pytest.raises(ValueError, match="Unknown worktree_id"):
        mcp_server.diff("owner/repo/never-created")


def test_create_worktree_requires_an_indexed_repo(workspace, monkeypatch):
    monkeypatch.setattr(config, "WORKTREES_DIR", workspace.parent / "worktrees")
    monkeypatch.setattr(mcp_server, "get_workspace", lambda repo_id: None)
    with pytest.raises(ValueError, match="has not been indexed"):
        mcp_server.create_worktree("owner/repo")


def test_sandbox_refuses_to_run_without_docker(worktree_id, monkeypatch):
    """Fail closed: no Docker means the command is refused, not run on the host."""
    monkeypatch.setattr(config, "SANDBOX_ALLOW_HOST_FALLBACK", False)
    monkeypatch.setattr("utils.sandbox.is_docker_available", lambda: False)

    result = mcp_server.sandbox_run(worktree_id, "rm -rf /")

    assert result["ran"] is False
    assert result["passed"] is False
    assert "docker unavailable" in result["skipped_reason"]


def test_list_and_read_file_are_bounded(workspace, monkeypatch):
    monkeypatch.setattr(mcp_server, "get_workspace", lambda repo_id: workspace)

    files = mcp_server.list_files("owner/repo")
    assert "src/app.py" in files

    content = mcp_server.read_file("owner/repo", "src/app.py", max_chars=5)
    assert content["content"] == "def r"
    assert content["truncated"] is True

    assert mcp_server.read_file("owner/repo", "../../etc/passwd") is None


def test_context_tools_degrade_when_nothing_is_indexed(monkeypatch):
    monkeypatch.setattr(mcp_server, "get_workspace", lambda repo_id: None)

    assert mcp_server.list_files("owner/repo") == []
    assert mcp_server.read_file("owner/repo", "a.py") is None
    assert mcp_server.search_code("owner/repo", "anything") == []
    assert mcp_server.repo_summary("owner/repo").endswith("has not been indexed yet.")


def test_docs_and_search_are_empty_for_unknown_repo():
    assert mcp_server.repository_docs("nobody/nothing") == ""
    assert mcp_server.search_issues("nobody/nothing", "query") == []
