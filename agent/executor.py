"""Executor agent: turns a plan into applied code edits in an isolated worktree.

The model returns edit operations (or a unified diff); they are applied to a per-run
worktree so the result is a real git diff. Every attempt starts from a fresh copy, which
keeps retries independent and the diff representative of the current attempt.
"""
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any

from agent.patch_tools import (
    apply_edits,
    apply_unified_diff,
    create_worktree,
    worktree_diff,
    worktree_files_changed,
)
from llm.client import build_llm_client, resolve_llm_settings

logger = logging.getLogger(__name__)

MAX_TREE_ENTRIES = 200

SYSTEM_PROMPT = (
    "You are an expert coding agent. Given a plan and optional feedback, respond with "
    'ONLY a JSON object: {"edits": [...], "rationale": "..."}. Each edit is one of:\n'
    '  {"path": "relative/path.py", "content": "<entire new file contents>"}\n'
    '  {"path": "relative/path.py", "find": "<exact existing text>", "replace": "<new text>"}\n'
    '  {"path": "relative/path.py", "delete": true}\n'
    "Prefer 'find'/'replace' for small changes; 'find' must match the existing file "
    "exactly. Use repository-relative paths that appear in the provided file list. "
    "Do not wrap the JSON in prose."
)


def parse_model_output(raw: str) -> dict[str, Any]:
    """Extract edits, a rationale, or a unified-diff fallback from a model response.

    Models do not always honour an output format, so this accepts either the requested
    JSON object or a fenced diff block, and reports a clear error otherwise.
    """
    text = (raw or "").strip()

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("edits"), list):
            return {
                "edits": payload["edits"],
                "rationale": str(payload.get("rationale", "")),
                "diff": None,
                "error": None,
            }

    diff_match = re.search(r"```(?:diff)?\n(.*?)```", text, re.DOTALL)
    if diff_match and diff_match.group(1).lstrip().startswith(("---", "diff ")):
        return {"edits": [], "rationale": "", "diff": diff_match.group(1), "error": None}

    return {
        "edits": [],
        "rationale": text[:500],
        "diff": None,
        "error": "model returned no usable edits",
    }


class Executor:
    """Applies code edits based on a plan and conversational refinement feedback."""

    def __init__(
        self,
        repo_id: str,
        model: str | None = None,
        workspace: Path | str | None = None,
        run_id: str | None = None,
    ):
        self.repo_id = repo_id
        settings = resolve_llm_settings()
        self.model = model or settings.model
        self.client = build_llm_client(settings)
        self.workspace = Path(workspace) if workspace is not None else None
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.worktree: Path | None = None

    def _file_tree(self) -> list[str]:
        """Bounded list of paths the model may edit, so it uses real filenames."""
        if self.workspace is None:
            return []
        from agent.code_tools import CodeReader

        try:
            return CodeReader(self.workspace).list_files()[:MAX_TREE_ENTRIES]
        except (FileNotFoundError, OSError):
            return []

    def _request_edits(self, plan: dict[str, Any], feedback: str | None) -> str:
        user_prompt = f"Repository: {self.repo_id}\nPlan:\n{plan.get('plan', '')}\n"
        issue = plan.get("issue")
        if issue:
            user_prompt += f"\nIssue: {issue}\n"
        tree = self._file_tree()
        if tree:
            user_prompt += "\nFiles available to edit:\n" + "\n".join(tree) + "\n"
        if feedback:
            user_prompt += f"\nFeedback to incorporate: {feedback}\n"

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=4096,
        )
        return response.choices[0].message.content or ""

    def _failure(self, attempt: int, feedback: str | None, errors: list[str], worktree=None):
        return {
            "status": "failed",
            "repo_id": self.repo_id,
            "attempt": attempt,
            "files_changed": [],
            "diff": "",
            "errors": errors,
            "rationale": "",
            "worktree": str(worktree) if worktree else None,
            "feedback": feedback,
        }

    def execute(
        self,
        plan: dict[str, Any],
        feedback: str | None = None,
        attempt: int = 1,
    ) -> dict[str, Any]:
        """Plan -> LLM edits -> applied worktree -> unified diff."""
        logger.info("Executing plan for %s (attempt %s)", self.repo_id, attempt)
        if feedback:
            logger.info("Incorporating feedback: %s...", feedback[:80])

        if self.workspace is None or not self.workspace.is_dir():
            return self._failure(
                attempt, feedback, [f"workspace not available for {self.repo_id}"]
            )

        worktree = create_worktree(self.workspace, self.repo_id, f"{self.run_id}-a{attempt}")
        self.worktree = worktree

        try:
            raw = self._request_edits(plan, feedback)
        except Exception as exc:  # noqa: BLE001 - reported to the caller, never fatal
            logger.warning("LLM execution failed (%s)", exc)
            return self._failure(attempt, feedback, [f"LLM call failed: {exc}"], worktree)

        parsed = parse_model_output(raw)
        errors: list[str] = []
        applied: list[str] = []

        if parsed["edits"]:
            patch = apply_edits(worktree, parsed["edits"])
            applied, errors = patch.applied, list(patch.errors)
        elif parsed["diff"]:
            patch = apply_unified_diff(worktree, parsed["diff"])
            applied, errors = patch.applied, list(patch.errors)
        else:
            errors.append(parsed["error"] or "no edits produced")

        diff = worktree_diff(worktree)
        files_changed = worktree_files_changed(worktree) or applied
        status = "applied" if applied and not errors else ("partial" if applied else "failed")

        logger.info(
            "Attempt %s for %s: status=%s files=%s errors=%s",
            attempt,
            self.repo_id,
            status,
            len(files_changed),
            len(errors),
        )
        return {
            "status": status,
            "repo_id": self.repo_id,
            "attempt": attempt,
            "files_changed": files_changed,
            "diff": diff,
            "errors": errors,
            "rationale": parsed["rationale"],
            "worktree": str(worktree),
            "feedback": feedback,
        }

