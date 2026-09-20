"""Patch application in an isolated worktree.

`agent/code_tools.py` guarantees the model never writes to the indexed workspace. Patch
edits therefore land in a per-run copy under `data/worktrees/<owner>/<repo>/<run_id>`
that is initialised as a git repository, so the agent's change can be captured as a real
unified diff and cleaned up afterwards.

    worktree = create_worktree(workspace, repo_id, run_id)
    result = apply_edits(worktree, edits)      # Executor output
    diff = worktree_diff(worktree)
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
    """Outcome of applying a batch of edits."""

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


def _safe_resolve(worktree: Path, rel_path: str) -> Path | None:
    """Resolve a relative path, refusing anything that escapes the worktree."""
    candidate = (worktree / rel_path).resolve()
    try:
        candidate.relative_to(worktree.resolve())
    except ValueError:
        return None
    return candidate


def create_worktree(workspace: Path | str, repo_id: str, run_id: str) -> Path:
    """Copy the workspace into a fresh git-initialised worktree and return its path.

    A baseline commit is created so `worktree_diff()` reports only agent edits.
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


def apply_edits(worktree: Path | str, edits: list[dict]) -> PatchResult:
    """Apply edit operations to a worktree.

    Supported operations (each a dict with a `path`):
      * ``{"path": p, "content": "..."}``   write/replace the whole file
      * ``{"path": p, "find": "a", "replace": "b"}``  targeted replacement
      * ``{"path": p, "delete": true}``     remove the file

    A bad edit is recorded in `errors` and skipped rather than aborting the batch, so the
    caller can feed the errors back to the model for a repair attempt.
    """
    worktree_path = Path(worktree)
    result = PatchResult()

    for index, edit in enumerate(edits or []):
        if not isinstance(edit, dict):
            result.errors.append(f"edit {index}: not an object")
            continue

        rel_path = edit.get("path")
        if not isinstance(rel_path, str) or not rel_path.strip():
            result.errors.append(f"edit {index}: missing 'path'")
            continue

        target = _safe_resolve(worktree_path, rel_path)
        if target is None:
            result.errors.append(f"edit {index}: path escapes worktree ({rel_path})")
            continue

        if edit.get("delete"):
            if target.is_file():
                target.unlink()
                result.applied.append(rel_path)
            else:
                result.errors.append(f"edit {index}: cannot delete missing file ({rel_path})")
            continue

        if "content" in edit:
            content = edit["content"]
            if not isinstance(content, str):
                result.errors.append(f"edit {index}: 'content' must be a string")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            result.applied.append(rel_path)
            continue

        if "find" in edit and "replace" in edit:
            find_text, replace_text = edit["find"], edit["replace"]
            if not isinstance(find_text, str) or not isinstance(replace_text, str):
                result.errors.append(f"edit {index}: 'find'/'replace' must be strings")
                continue
            if not target.is_file():
                result.errors.append(f"edit {index}: cannot patch missing file ({rel_path})")
                continue
            original = target.read_text(encoding="utf-8", errors="replace")
            if find_text not in original:
                result.errors.append(f"edit {index}: 'find' text not present in {rel_path}")
                continue
            target.write_text(original.replace(find_text, replace_text, 1), encoding="utf-8")
            result.applied.append(rel_path)
            continue

        result.errors.append(
            f"edit {index}: expected 'content', 'find'+'replace', or 'delete' ({rel_path})"
        )

    return result


def worktree_diff(worktree: Path | str) -> str:
    """Unified diff of every change made since the baseline commit."""
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


def apply_unified_diff(worktree: Path | str, diff_text: str) -> PatchResult:
    """Apply a unified diff with `git apply` (fallback when the model emits a patch)."""
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


def cleanup_worktree(worktree: Path | str) -> None:
    """Best-effort removal of a worktree directory."""
    path = Path(worktree)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
