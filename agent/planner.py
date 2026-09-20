"""Planner agent: turns an issue or feature request into an execution plan."""
import logging
from typing import Any

import config
from openai import OpenAI

logger = logging.getLogger(__name__)


class Planner:
    """Analyzes an issue or feature request and produces a structured plan."""

    def __init__(self, model: str | None = None):
        self.model = model or config.LLM_MODEL
        self.client = OpenAI(api_key=config.OPENAI_API_KEY)

    def plan(
        self,
        repo_id: str,
        issue_description: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        logger.info(f"Planning fix for {repo_id}: {issue_description[:80]}...")

        system_prompt = (
            "You are a senior software engineer planning a minimal, safe patch for a "
            "GitHub issue. Given the issue description and repository context, output a "
            "concise plan with: (1) the likely files to modify, (2) the specific changes, "
            "and (3) how to verify the fix. Be specific and avoid over-engineering."
        )

        user_prompt = f"Repository: {repo_id}\nIssue: {issue_description}\n"
        if context:
            user_prompt += f"Context: {context}\n"

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=1024,
            )
            plan_text = response.choices[0].message.content or ""
        except Exception as exc:
            logger.warning(f"LLM planning failed ({exc}); using fallback plan.")
            plan_text = (
                "1. Locate the files most relevant to the issue.\n"
                "2. Apply the smallest change that addresses the issue.\n"
                "3. Run the repository test suite or linter to verify."
            )

        return {
            "repo_id": repo_id,
            "issue": issue_description,
            "plan": plan_text,
            "context": context or {},
        }
