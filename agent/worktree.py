"""Isolated worktrees: the safe place for an external agent to make changes.

`agent/code_tools.py` guarantees the indexed workspace is never written to. A caller that
wants to modify a repository therefore works on a per-run copy under
``data/worktrees/<owner>/<repo>/<run_id>`` that is initialised as a git repository, so the
change can be captured as a real unified diff and discarded afterwards.

This module is substrate only: it creates the copy, applies whatever it is told to apply,
and reports what changed. Deciding *what* to edit belongs to the caller (TaskChain exposes
these as MCP tools rather than implementing an editing agent).
"""
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import config

logger = logging.getLogger(__name__)

GIT_TIMEOUT_S = 60


@dataclass
class PatchResult:
    """Outcome of a write/delete/patch operation against a worktree."""

    applied: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.applied) and not self.errors


def _git(worktree: Path, *args: str) -> subprocess.CompletedProcess:
    """Run a git command inside the worktree."""
    return subprocess.run(
        ["git", "-C", str(worktree), *args],
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_S,
    )


def safe_resolve(worktree: Path | str, rel_path: str) -> Path | None:
    """Resolve a relative path, refusing anything that escapes the worktree.

    The single chokepoint for path safety: every tool that touches a path goes through it.
    """
    root = Path(worktree).resolve()
    candidate = (root / rel_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def create_worktree(workspace: Path | str, repo_id: str, run_id: str) -> Path:
    """Copy the workspace into a fresh git-initialised worktree and return its path.

    A baseline commit is created so `worktree_diff()` reports only the caller's changes,
    and so a fresh run always starts from the unmodified repository.
    """
    workspace_path = Path(workspace).resolve()
    if not workspace_path.is_dir():
        raise FileNotFoundError(f"Workspace not found: {workspace_path}")

    owner, _, repo = repo_id.partition("/")
    worktree = config.WORKTREES_DIR / owner / repo / run_id
    if worktree.exists():
        shutil.rmtree(worktree)
    worktree.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(workspace_path, worktree)

    _git(worktree, "init", "-q")
    _git(worktree, "add", "-A")
    _git(
        worktree,
        "-c",
        "user.email=agent@taskchain.local",
        "-c",
        "user.name=TaskChain Agent",
        "commit",
        "-q",
        "-m",
        "baseline",
    )
    logger.info("Created worktree %s", worktree)
    return worktree



def write_file(worktree: Path | str, rel_path: str, content: str) -> PatchResult:
    """Write a file inside the worktree, creating parent directories as needed."""
    target = safe_resolve(worktree, rel_path)
    if target is None:
        return PatchResult(errors=[f"path escapes worktree ({rel_path})"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return PatchResult(applied=[rel_path])


def delete_file(worktree: Path | str, rel_path: str) -> PatchResult:
    """Delete a file inside the worktree."""
    target = safe_resolve(worktree, rel_path)
    if target is None:
        return PatchResult(errors=[f"path escapes worktree ({rel_path})"])
    if not target.is_file():
        return PatchResult(errors=[f"cannot delete missing file ({rel_path})"])
    target.unlink()
    return PatchResult(applied=[rel_path])


def apply_patch(worktree: Path | str, diff_text: str) -> PatchResult:
    """Apply a unified diff with `git apply`, after a dry run so a bad patch is a no-op."""
    worktree_path = Path(worktree)
    if not diff_text.strip():
        return PatchResult(errors=["empty diff"])

    check = subprocess.run(
        ["git", "-C", str(worktree_path), "apply", "--check", "-"],
        input=diff_text,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_S,
    )
    if check.returncode != 0:
        return PatchResult(errors=[f"git apply --check failed: {check.stderr.strip()[:400]}"])

    applied = subprocess.run(
        ["git", "-C", str(worktree_path), "apply", "-"],
        input=diff_text,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_S,
    )
    if applied.returncode != 0:
        return PatchResult(errors=[f"git apply failed: {applied.stderr.strip()[:400]}"])

    return PatchResult(applied=worktree_files_changed(worktree_path))


def worktree_diff(worktree: Path | str) -> str:
    """Unified diff of everything changed since the baseline commit."""
    completed = _git(Path(worktree), "diff", "--no-color")
    if completed.returncode != 0:
        logger.warning("git diff failed: %s", completed.stderr.strip())
        return ""
    return completed.stdout


def worktree_files_changed(worktree: Path | str) -> list[str]:
    """Relative paths of files changed since the baseline commit."""
    completed = _git(Path(worktree), "diff", "--name-only")
    if completed.returncode != 0:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def cleanup_worktree(worktree: Path | str) -> None:
    """Best-effort removal of a worktree directory."""
    path = Path(worktree)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
