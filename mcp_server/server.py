"""TaskChain MCP server: repository context and a sandboxed execution substrate.

This is the integration surface for this project. TaskChain does **not** decide what to
edit or produce patches; an external agent (Claude, Cline, or anything else speaking MCP)
does that, using the tools here for grounding and for safe execution:

* **Context** — indexed files, issues/PRs, docs, repository summary, and (optionally) a
  suggested plan, all read-only.
* **Execution** — an isolated per-run git worktree plus a hardened Docker sandbox, so the
  agent can change and test a repository without TaskChain ever performing the edit.

Security model: tools never accept a host filesystem path. They accept a `worktree_id`
returned by `create_worktree`, which is validated to live under `config.WORKTREES_DIR`.
That stops a client from pointing `sandbox_run` at an arbitrary host directory.

Run with:
    python -m mcp_server.server                 # stdio (default, for desktop clients)
    python -m mcp_server.server --http          # streamable HTTP (for remote/multi-client)
"""
import argparse
import logging
import uuid
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

import config
from agent.code_tools import CodeReader
from agent.planner import Planner
from agent.worktree import (
    apply_patch as _apply_patch,
)
from agent.worktree import (
    cleanup_worktree,
    worktree_diff,
    worktree_files_changed,
)
from agent.worktree import (
    create_worktree as _create_worktree,
)
from agent.worktree import (
    delete_file as _delete_file,
)
from agent.worktree import (
    write_file as _write_file,
)
from github.pr_client import PullRequestClient
from ingestion.code_indexer import count_indexed_files
from ingestion.code_indexer import search_code as search_code_impl
from ingestion.docs_collector import build_docs_context
from ingestion.github_indexer import parse_github_url
from ingestion.ingestion_pipeline import ingest_repository
from ingestion.sqlite_indexer import keyword_search
from ingestion.workspace import get_workspace
from utils.db import RepoIngestion, SessionLocal
from utils.logging_config import setup_logging
from utils.sandbox import detect_test_command, run_sandbox_command

setup_logging()
logger = logging.getLogger(__name__)

mcp = FastMCP(
    "taskchain",
    instructions=(
        "Repository context and sandboxed execution for an external coding agent. "
        "Index a repository first, then search/read it for grounding, create a worktree, "
        "make changes with write_file/apply_patch, and verify them with sandbox_run. "
        "TaskChain never edits files itself."
    ),
)

MAX_OUTPUT_CHARS = 8000


def _repo_id(repo_id: str) -> tuple[str, str]:
    """Split and validate an `owner/repo` identifier."""
    owner, sep, repo = repo_id.partition("/")
    if not sep or not owner or not repo:
        raise ValueError(f"Expected 'owner/repo', got {repo_id!r}")
    return owner, repo


def _resolve_worktree(worktree_id: str) -> Path:
    """Map a `worktree_id` to a directory, refusing anything outside WORKTREES_DIR.

    Tools take this id rather than a path so a client cannot aim the sandbox at an
    arbitrary host directory.
    """
    candidate = (config.WORKTREES_DIR / worktree_id).resolve()
    root = config.WORKTREES_DIR.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise ValueError(f"worktree_id must live under {root}: {worktree_id!r}") from None
    if not candidate.is_dir():
        raise ValueError(
            f"Unknown worktree_id {worktree_id!r}. Call create_worktree first."
        )
    return candidate


def _truncate(text: str, max_chars: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n... [truncated, {len(text)} chars total]"


# --------------------------------------------------------------------------------------
# Context tools (read-only)
# --------------------------------------------------------------------------------------


@mcp.tool()
def list_indexed_repos() -> list[dict[str, Any]]:
    """List repositories that have been ingested, with index sizes."""
    db = SessionLocal()
    try:
        rows = db.query(RepoIngestion).order_by(RepoIngestion.owner, RepoIngestion.repo).all()
        results = []
        for row in rows:
            repo_id = f"{row.owner}/{row.repo}"
            results.append(
                {
                    "repo_id": repo_id,
                    "status": row.status,
                    "issues": row.issue_count or 0,
                    "pull_requests": row.pr_count or 0,
                    "files_indexed": count_indexed_files(repo_id),
                }
            )
        return results
    finally:
        db.close()


@mcp.tool()
def index_repository(repo_url: str) -> dict[str, Any]:
    """Ingest a public GitHub repository: metadata, docs, file tree, issues and PRs.

    Long-running (it fetches from the GitHub API and downloads the tarball) and requires
    GITHUB_TOKEN in the server environment.
    """
    owner, repo = parse_github_url(repo_url)
    result = ingest_repository(repo_url)
    return {"repo_id": f"{owner}/{repo}", **result}


@mcp.tool()
def repo_summary(repo_id: str) -> str:
    """The stored repository summary (what it does, tech stack, activity)."""
    owner, repo = _repo_id(repo_id)
    db = SessionLocal()
    try:
        row = db.query(RepoIngestion).filter_by(owner=owner, repo=repo).first()
        if row is None:
            return f"{repo_id} has not been indexed yet."
        return row.dna_summary or f"{repo_id} has no summary yet."
    finally:
        db.close()


@mcp.tool()
def list_files(repo_id: str, limit: int = 500) -> list[str]:
    """List the text files available in a repository's read-only workspace."""
    workspace = get_workspace(repo_id)
    if workspace is None:
        return []
    return CodeReader(workspace).list_files()[: max(1, limit)]


@mcp.tool()
def read_file(repo_id: str, path: str, max_chars: int | None = None) -> dict[str, Any] | None:
    """Read one file from a repository, bounded by a character cap and path-checked."""
    workspace = get_workspace(repo_id)
    if workspace is None:
        return None
    return CodeReader(workspace).read_file(path, max_chars=max_chars)


@mcp.tool()
def search_code(repo_id: str, query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """Keyword-search indexed repository source files. Returns [{path, snippet}]."""
    return search_code_impl(repo_id, query, top_k)


@mcp.tool()
def search_issues(repo_id: str, query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """Keyword-search indexed issues and pull requests."""
    return keyword_search(repo_id, query, top_k=max(1, top_k))


@mcp.tool()
def repository_docs(repo_id: str) -> str:
    """Curated documentation (README and friends) injected under a character budget."""
    return build_docs_context(repo_id)


@mcp.tool()
def suggest_plan(repo_id: str, issue_description: str) -> dict[str, Any]:
    """Ask the LLM for a suggested approach to an issue.

    Advisory context only: TaskChain returns the plan and stops. Acting on it is the
    calling agent's job.
    """
    related = keyword_search(repo_id, issue_description, top_k=config.KEYWORD_TOP_K)
    owner, repo = _repo_id(repo_id)
    db = SessionLocal()
    try:
        row = db.query(RepoIngestion).filter_by(owner=owner, repo=repo).first()
        dna_summary = (row.dna_summary or "") if row else ""
    finally:
        db.close()

    return Planner().plan(
        repo_id=repo_id,
        issue_description=issue_description,
        context={"dna_summary": dna_summary, "related_issues": related},
    )


# --------------------------------------------------------------------------------------
# Execution substrate: isolated worktree + hardened sandbox
# --------------------------------------------------------------------------------------


@mcp.tool()
def create_worktree(repo_id: str, run_id: str | None = None) -> dict[str, Any]:
    """Create an isolated, git-initialised copy of a repository to work in.

    Returns the `worktree_id` that every other execution tool takes. The repository's
    indexed workspace is never modified.
    """
    workspace = get_workspace(repo_id)
    if workspace is None:
        raise ValueError(f"{repo_id} has not been indexed; call index_repository first.")

    owner, _, repo = repo_id.partition("/")
    run = run_id or uuid.uuid4().hex[:8]
    path = _create_worktree(workspace, repo_id, run)
    return {
        "worktree_id": f"{owner}/{repo}/{run}",
        "files": len(worktree_files_changed(path)) or len(CodeReader(path).list_files()),
    }


@mcp.tool()
def write_file(worktree_id: str, path: str, content: str) -> dict[str, Any]:
    """Write a file inside the worktree (creates parent directories)."""
    result = _write_file(_resolve_worktree(worktree_id), path, content)
    return {"applied": result.applied, "errors": result.errors}


@mcp.tool()
def delete_file(worktree_id: str, path: str) -> dict[str, Any]:
    """Delete a file inside the worktree."""
    result = _delete_file(_resolve_worktree(worktree_id), path)
    return {"applied": result.applied, "errors": result.errors}


@mcp.tool()
def apply_patch(worktree_id: str, unified_diff: str) -> dict[str, Any]:
    """Apply a unified diff to the worktree; validated with a dry run first."""
    result = _apply_patch(_resolve_worktree(worktree_id), unified_diff)
    return {"applied": result.applied, "errors": result.errors}


@mcp.tool()
def sandbox_run(worktree_id: str, command: str, timeout: int | None = None) -> dict[str, Any]:
    """Run a shell command in the sandboxed container against the worktree.

    No network, non-root, memory/CPU/PID caps, wall-clock timeout. Fails closed: if Docker
    is unavailable the command is refused rather than executed on the host.
    """
    worktree = _resolve_worktree(worktree_id)
    result = run_sandbox_command(worktree, command, timeout=timeout)
    return {
        "command": result.command,
        "ran": result.ran,
        "passed": result.passed,
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "skipped_reason": result.skipped_reason,
        "stdout": _truncate(result.stdout),
        "stderr": _truncate(result.stderr),
    }


@mcp.tool()
def suggested_test_command(worktree_id: str) -> str | None:
    """The test command TaskChain would use for this repository, if it can tell."""
    return detect_test_command(_resolve_worktree(worktree_id))


@mcp.tool()
def diff(worktree_id: str) -> dict[str, Any]:
    """Unified diff of everything the agent has changed in the worktree."""
    worktree = _resolve_worktree(worktree_id)
    return {
        "files_changed": worktree_files_changed(worktree),
        "diff": _truncate(worktree_diff(worktree)),
    }


@mcp.tool()
def discard_worktree(worktree_id: str) -> str:
    """Delete the worktree and everything in it."""
    cleanup_worktree(_resolve_worktree(worktree_id))
    return f"Discarded {worktree_id}"


@mcp.tool()
def open_pull_request(
    owner: str,
    repo: str,
    title: str,
    body: str,
    head_branch: str,
    base_branch: str = "main",
) -> dict[str, Any]:
    """Open a pull request via the GitHub API. Requires GITHUB_TOKEN with repo scope."""
    pr = PullRequestClient().open_pr(
        owner=owner,
        repo=repo,
        title=title,
        body=body,
        head_branch=head_branch,
        base_branch=base_branch,
    )
    return {"pr_number": pr.get("number"), "html_url": pr.get("html_url")}


def main() -> None:
    parser = argparse.ArgumentParser(description="TaskChain MCP server")
    parser.add_argument(
        "--http",
        action="store_true",
        help="Serve streamable HTTP instead of stdio (for remote clients).",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    if args.http:
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        logger.info("Serving MCP over streamable HTTP on %s:%s", args.host, args.port)
        mcp.run(transport="streamable-http")
    else:
        logger.info("Serving MCP over stdio")
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()


