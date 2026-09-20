"""Verifier agent: runs the repository's own tests in the sandbox and reviews the diff.

Verification has two parts with different authority:

* **Tests/lint** run inside the sandbox against the patched worktree. Their exit code is
  the gate — a patch is only `passed` if the repository's own suite exits zero.
* **LLM review** of the diff is advisory. It explains the change and can raise concerns,
  but it never decides `status`, because a model grading its own patch is not evidence.

When no test command can be determined the result is `not_run`: the caller should treat
that as "unverified", not as success.
"""
import logging
from pathlib import Path
from typing import Any

from llm.client import build_llm_client, resolve_llm_settings
from utils.sandbox import SandboxResult, detect_test_command, run_sandbox_command

logger = logging.getLogger(__name__)

REVIEW_PROMPT = (
    "You are a rigorous code reviewer. Given an issue description and a proposed patch, "
    "summarise what the patch does, whether it addresses the issue, and any risks or "
    "missing cases. Be concise and concrete. Do not claim tests passed; you cannot run them."
)


class Verifier:
    """Reviews a patch against the issue and runs the repository's test suite or linter."""

    def __init__(self, repo_id: str, model: str | None = None):
        self.repo_id = repo_id
        settings = resolve_llm_settings()
        self.model = model or settings.model
        self.client = build_llm_client(settings)

    def run_tests(
        self,
        worktree: Path | str | None,
        test_command: str | None = None,
        timeout: int | None = None,
    ) -> tuple[str | None, SandboxResult | None]:
        """Resolve a test command and run it in the sandbox. Returns (command, result)."""
        if worktree is None:
            return None, None

        command = test_command or detect_test_command(worktree)
        if not command:
            logger.info("No test command detected for %s", self.repo_id)
            return None, None

        result = run_sandbox_command(worktree, command, timeout=timeout)
        return command, result

    def _review(self, diff: str, execution_result: dict[str, Any], issue: str | None) -> str:
        user_prompt = f"Repository: {self.repo_id}\n"
        if issue:
            user_prompt += f"Issue: {issue}\n"
        files = execution_result.get("files_changed") or []
        if files:
            user_prompt += f"Files changed: {', '.join(files)}\n"
        user_prompt += f"Patch:\n{diff or '(no changes produced)'}\n"

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": REVIEW_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=1024,
        )
        return response.choices[0].message.content or ""

    def verify(
        self,
        execution_result: dict[str, Any],
        issue_description: str | None = None,
        test_command: str | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Run the tests, review the diff, and gate the status on the test exit code."""
        logger.info("Verifying changes for %s", self.repo_id)

        diff = execution_result.get("diff", "")
        worktree = execution_result.get("worktree")

        command, sandbox = self.run_tests(worktree, test_command, timeout)

        if sandbox is None:
            status = "not_run"
            test_output = (
                "No test command could be determined for this repository."
                if execution_result.get("status") != "failed"
                else "Executor produced no changes to verify."
            )
            exit_code = None
        else:
            status = "passed" if sandbox.passed else "failed"
            exit_code = sandbox.exit_code
            test_output = _format_sandbox_output(sandbox)

        try:
            review = self._review(diff, execution_result, issue_description)
        except Exception as exc:  # noqa: BLE001 - review is advisory only
            logger.warning("LLM review failed (%s)", exc)
            review = "Advisory review unavailable (LLM call failed)."

        result = {
            "status": status,
            "repo_id": self.repo_id,
            "test_command": command,
            "test_output": test_output,
            "exit_code": exit_code,
            "review": review,
            "concerns": list(execution_result.get("errors") or []),
        }
        result["summary"] = summarize_verification(result)
        logger.info("Verification for %s: %s", self.repo_id, result["status"])
        return result


def _format_sandbox_output(sandbox: SandboxResult, max_chars: int = 4000) -> str:
    """Tail of the sandbox output, where test runners put their verdict."""
    if sandbox.timed_out:
        return f"timed out after {sandbox.exit_code} (no verdict)"
    combined = (sandbox.stdout or "") + (("\n" + sandbox.stderr) if sandbox.stderr else "")
    combined = combined.strip()
    if len(combined) > max_chars:
        combined = "…" + combined[-max_chars:]
    return combined or f"no output (exit {sandbox.exit_code})"


def summarize_verification(result: dict[str, Any]) -> str:
    """Plain-English one-liner describing what verification established."""
    status = result["status"]
    command = result.get("test_command") or "no command"
    if status == "passed":
        return f"Tests passed: `{command}` exited 0."
    if status == "failed":
        return f"Tests failed: `{command}` exited {result.get('exit_code')}."
    if status == "not_run":
        return "Tests not run: no test command was determined, so the patch is unverified."
    return f"Verification status: {status}."
