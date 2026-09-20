"""Executor agent: applies code edits based on a plan and user feedback."""
import logging
from typing import Any

from openai import OpenAI

import config

logger = logging.getLogger(__name__)


class Executor:
    """Applies code edits based on a plan and conversational refinement feedback."""

    def __init__(self, repo_id: str, model: str | None = None):
        self.repo_id = repo_id
        self.model = model or config.LLM_MODEL
        self.client = OpenAI(api_key=config.OPENAI_API_KEY)

    def execute(
        self,
        plan: dict[str, Any],
        feedback: str | None = None,
    ) -> dict[str, Any]:
        logger.info(f"Executing plan for {self.repo_id}")
        if feedback:
            logger.info(f"Incorporating feedback: {feedback[:80]}...")

        system_prompt = (
            "You are an expert coding agent. Given a plan and optional user feedback, "
            "produce a unified diff that implements the fix. If no specific file content "
            "is available, describe the exact changes in plain English and include a "
            "representative diff block."
        )

        user_prompt = f"Repository: {self.repo_id}\nPlan:\n{plan.get('plan', '')}\n"
        if feedback:
            user_prompt += f"\nUser feedback (incorporate this): {feedback}\n"

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                max_tokens=2048,
            )
            diff = response.choices[0].message.content or ""
        except Exception as exc:
            logger.warning(f"LLM execution failed ({exc}); returning empty diff.")
            diff = ""

        return {
            "status": "pending_verification",
            "repo_id": self.repo_id,
            "files_changed": [],
            "diff": diff,
            "feedback": feedback,
        }
