"""GitHub API client for opening and updating pull requests."""
import logging
import os

import httpx

logger = logging.getLogger(__name__)


class PullRequestClient:
    """Open or update pull requests via the GitHub REST API."""

    def __init__(self, token: str | None = None):
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            self.headers["Authorization"] = f"Bearer {self.token}"

    def open_pr(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str = "main",
    ) -> dict:
        logger.info(f"Opening PR on {owner}/{repo}: {title}")
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
        payload = {
            "title": title,
            "body": body,
            "head": head_branch,
            "base": base_branch,
        }
        with httpx.Client() as client:
            response = client.post(
                url, headers=self.headers, json=payload, timeout=30.0
            )
            response.raise_for_status()
            return response.json()

    def update_pr(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        title: str | None = None,
        body: str | None = None,
    ) -> dict:
        logger.info(f"Updating PR #{pr_number} on {owner}/{repo}")
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
        payload = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["body"] = body
        with httpx.Client() as client:
            response = client.patch(
                url, headers=self.headers, json=payload, timeout=30.0
            )
            response.raise_for_status()
            return response.json()
