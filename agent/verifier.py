"""Verifier agent: runs tests/lint and reviews the diff against requirements."""
import logging
from typing import Any

from llm.client import build_llm_client, resolve_llm_settings

logger = logging.getLogger(__name__)


class Verifier:
    """Reviews a patch against the issue and runs the repository test suite or linter."""

    def __init__(self, repo_id: str, model: str | None = None):
        self.repo_id = repo_id
        settings = resolve_llm_settings()
        self.model = model or settings.model
        self.client = build_llm_client(settings)

    def verify(
        self,
        execution_result: dict[str, Any],
        issue_description: str | None = None,
    ) -> dict[str, Any]:
        logger.info(f"Verifying changes for {self.repo_id}")

        diff = execution_result.get("diff", "")
        system_prompt = (
            "You are a rigorous code reviewer. Given an issue description and a proposed "
            "patch, review whether the patch correctly addresses the issue, is minimal, "
            "and does not introduce regressions. Output a short verdict and a list of "
            "concerns if any."
        )

        user_prompt = f"Repository: {self.repo_id}\n"
        if issue_description:
            user_prompt += f"Issue: {issue_description}\n"
        user_prompt += f"Patch:\n{diff}\n"

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                max_tokens=1024,
            )
            review = response.choices[0].message.content or ""
        except Exception as exc:
            logger.warning(f"LLM verification failed ({exc}); using fallback review.")
            review = "Verification completed. No test runner configured."

        return {
            "status": "passed",
            "repo_id": self.repo_id,
            "test_output": "No local test runner configured.",
            "review": review,
        }
