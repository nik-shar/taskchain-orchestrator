"""Fetch repository metadata, issues, and pull requests from GitHub."""
import logging
import os
import re
import time
from datetime import UTC, datetime

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

SKIP_EXTENSIONS = [
    ".bin", ".pt", ".ckpt", ".h5", ".pkl",
    ".parquet", ".csv", ".zip", ".tar", ".gz",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".mp4", ".mp3", ".woff", ".woff2",
]

SKIP_PATHS = ["data/", "datasets/", "weights/", "checkpoints/", "dist/", "build/"]

MAX_FILE_SIZE_BYTES = 100_000  # 100KB

# Max time check_rate_limit will sleep before failing the ingestion instead.
MAX_RATE_LIMIT_WAIT_SECONDS = 60.0

ALWAYS_KEEP = [
    "README.md", "CONTRIBUTING.md", "CHANGELOG.md",
    "pyproject.toml", "requirements.txt", "package.json",
    "Dockerfile", "docker-compose.yml",
]


class Issue(BaseModel):
    number: int
    title: str
    body: str
    state: str
    labels: list[str]
    comments: list[str]
    created_at: datetime
    closed_at: datetime | None
    is_good_first_issue: bool


class PR(BaseModel):
    number: int
    title: str
    body: str
    state: str
    merged: bool
    linked_issue: int | None
    created_at: datetime


class RepoSnapshot(BaseModel):
    owner: str
    repo: str
    fetched_at: datetime
    metadata: dict
    readme: str
    contributing: str | None
    file_tree: list[str]
    tech_stack: dict
    issues: list[Issue]
    pull_requests: list[PR]


def parse_github_url(url: str) -> tuple[str, str]:
    """Parse owner and repo name from a GitHub URL."""
    match = re.search(r"github\.com/([^/]+)/([^/]+)", url)
    if not match:
        raise ValueError(f"Invalid GitHub URL: {url}")
    owner = match.group(1)
    repo = match.group(2)
    if repo.endswith(".git"):
        repo = repo[:-4]
    return owner, repo.strip("/")


def check_rate_limit(headers: httpx.Headers) -> None:
    """Check rate limit headers and sleep if remaining quota is low.

    A short wait is acceptable inside an ingestion run; a long one (e.g. the
    hourly unauthenticated limit) would silently freeze the pipeline, so we
    fail fast with a clear, actionable error instead.
    """
    remaining = headers.get("X-RateLimit-Remaining")
    reset_time = headers.get("X-RateLimit-Reset")
    if remaining is None:
        return
    try:
        rem = int(remaining)
    except ValueError:
        return
    if rem >= 100 or reset_time is None:
        return

    try:
        reset_at = float(reset_time)
    except ValueError:
        return

    sleep_duration = max(0.0, reset_at - time.time()) + 1.0
    if sleep_duration <= MAX_RATE_LIMIT_WAIT_SECONDS:
        logger.warning(
            f"GitHub API rate limit low ({rem} remaining). "
            f"Sleeping for {sleep_duration:.1f}s until reset."
        )
        time.sleep(sleep_duration)
    else:
        raise RuntimeError(
            f"GitHub API rate limit exhausted ({rem} remaining, resets in "
            f"{sleep_duration:.0f}s). Set a valid GITHUB_TOKEN to raise the "
            "limit to 5000 requests/hour."
        )


def should_skip_file(path: str, size_bytes: int) -> bool:
    """Apply file filtering rules based on file path and size."""
    filename = os.path.basename(path)
    if filename in ALWAYS_KEEP:
        return False
    for skip_p in SKIP_PATHS:
        if path.startswith(skip_p):
            return True
    _, ext = os.path.splitext(filename)
    if ext.lower() in SKIP_EXTENSIONS:
        return True
    if size_bytes > MAX_FILE_SIZE_BYTES:
        return True
    return False


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 100) -> list[str]:
    """Split long text into overlapping chunks."""
    if not text:
        return [""]
    if len(text) <= 1000:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
        if start >= len(text):
            break
    return chunks


def detect_tech_stack(file_contents: dict[str, str]) -> dict:
    """Detect programming language and frameworks from root config files."""
    tech = {
        "language": None,
        "frameworks": [],
        "build_tools": [],
        "config_files": list(file_contents.keys()),
    }
    if "package.json" in file_contents:
        tech["language"] = "JavaScript/TypeScript"
        try:
            import json
            data = json.loads(file_contents["package.json"])
            deps = {
                **(data.get("dependencies") or {}),
                **(data.get("devDependencies") or {}),
            }
            for fw in ["react", "next", "vue", "svelte", "express", "nest", "typescript"]:
                if fw in deps:
                    tech["frameworks"].append(fw)
        except Exception:
            pass
    elif {"requirements.txt", "pyproject.toml", "setup.py"} & set(file_contents):
        tech["language"] = "Python"
        all_text = (
            file_contents.get("requirements.txt", "")
            + "\n"
            + file_contents.get("pyproject.toml", "")
        ).lower()
        for fw in ["fastapi", "django", "flask", "streamlit", "sqlalchemy", "numpy", "pandas"]:
            if fw in all_text:
                tech["frameworks"].append(fw)
    elif "go.mod" in file_contents:
        tech["language"] = "Go"
    if "Dockerfile" in file_contents:
        tech["build_tools"].append("Docker")
    if "docker-compose.yml" in file_contents:
        tech["build_tools"].append("Docker Compose")
    return tech


def parse_datetime(dt_str: str | None) -> datetime | None:
    """Parse ISO datetime strings returned by the GitHub API."""
    if not dt_str:
        return None
    return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))


class GitHubIndexer:
    """Fetch public repository metadata, issues, and pull requests."""

    def __init__(self, github_token: str | None = None):
        self.github_token = github_token or os.getenv("GITHUB_TOKEN")
        self.headers = {"Accept": "application/vnd.github.v3+json"}
        if self.github_token:
            self.headers["Authorization"] = f"token {self.github_token}"

    def _request(
        self, client: httpx.Client, url: str, params: dict | None = None
    ) -> httpx.Response:
        response = client.get(url, headers=self.headers, params=params, timeout=10.0)
        check_rate_limit(response.headers)
        if response.status_code == 404:
            return response
        response.raise_for_status()
        return response

    def fetch_repo(self, repo_url: str, progress_callback=None) -> RepoSnapshot:
        """Fetch all relevant onboarding data for a public GitHub repository."""
        owner, repo = parse_github_url(repo_url)
        base_api_url = f"https://api.github.com/repos/{owner}/{repo}"

        if progress_callback:
            progress_callback(10, f"Connecting to repository {owner}/{repo}...")

        with httpx.Client() as client:
            meta_res = self._request(client, base_api_url)
            if meta_res.status_code == 404:
                raise ValueError(f"GitHub repository not found: {owner}/{repo}")
            meta_data = meta_res.json()
            # Note the `or` rather than a `.get(key, default)`: GitHub returns
            # `"description": null` for repos without one, and `.get` only falls back
            # when the key is *absent*, so the default never applies here.
            metadata = {
                "stars": meta_data.get("stargazers_count") or 0,
                "language": meta_data.get("language"),
                "description": meta_data.get("description") or "",
                "topics": meta_data.get("topics") or [],
            }

            if progress_callback:
                progress_callback(15, "Fetching README and CONTRIBUTING guidelines...")

            readme = ""
            readme_res = self._request(client, f"{base_api_url}/readme")
            if readme_res.status_code == 200:
                try:
                    import base64
                    readme = base64.b64decode(
                        readme_res.json().get("content", "")
                    ).decode("utf-8")
                except Exception as exc:
                    logger.warning(f"Failed to decode readme: {exc}")
                    readme = readme_res.text

            contributing = None
            contrib_res = self._request(client, f"{base_api_url}/contents/CONTRIBUTING.md")
            if contrib_res.status_code == 200:
                try:
                    import base64
                    contributing = base64.b64decode(
                        contrib_res.json().get("content", "")
                    ).decode("utf-8")
                except Exception as exc:
                    logger.warning(f"Failed to decode CONTRIBUTING.md: {exc}")
                    contributing = contrib_res.text

            if progress_callback:
                progress_callback(20, "Scanning top-level repository structure...")

            file_tree = []
            tech_stack_files = {}
            contents_res = self._request(client, f"{base_api_url}/contents/")
            if contents_res.status_code == 200:
                for item in contents_res.json():
                    path = item.get("path") or ""
                    file_tree.append(path)
                    filename = os.path.basename(path)
                    if filename in ALWAYS_KEEP and item.get("type") == "file":
                        file_res = self._request(client, item.get("url"))
                        if file_res.status_code == 200:
                            try:
                                import base64
                                content_decoded = base64.b64decode(
                                    file_res.json().get("content", "")
                                ).decode("utf-8")
                                tech_stack_files[filename] = content_decoded
                            except Exception:
                                pass

            github_res = self._request(client, f"{base_api_url}/contents/.github")
            if github_res.status_code == 200:
                for item in github_res.json():
                    file_tree.append(item.get("path") or "")

            tech_stack = detect_tech_stack(tech_stack_files)

            if progress_callback:
                progress_callback(30, "Downloading open issues from GitHub...")

            issues_list = []
            open_issues_res = self._request(
                client, f"{base_api_url}/issues", params={"state": "open", "per_page": 100}
            )
            if open_issues_res.status_code == 200:
                for issue_data in open_issues_res.json():
                    if "pull_request" in issue_data:
                        continue
                    issues_list.append(issue_data)

            if progress_callback:
                progress_callback(35, "Downloading closed issues from GitHub...")

            for page in [1, 2]:
                closed_issues_res = self._request(
                    client,
                    f"{base_api_url}/issues",
                    params={"state": "closed", "per_page": 100, "page": page},
                )
                if closed_issues_res.status_code == 200:
                    raw_closed = closed_issues_res.json()
                    if not raw_closed:
                        break
                    for issue_data in raw_closed:
                        if "pull_request" in issue_data:
                            continue
                        issues_list.append(issue_data)
                else:
                    break

            issues = []
            total_issues = len(issues_list)
            if progress_callback:
                progress_callback(40, f"Processing comments for {total_issues} issues...")

            for idx, issue_data in enumerate(issues_list):
                num = issue_data.get("number")
                title = issue_data.get("title") or ""
                body_raw = issue_data.get("body") or ""
                state = issue_data.get("state") or "open"

                comments = []
                comments_res = self._request(client, f"{base_api_url}/issues/{num}/comments")
                if comments_res.status_code == 200:
                    comments = [
                        c.get("body", "")
                        for c in comments_res.json()
                        if c.get("body")
                    ]

                labels = [
                    label.get("name") or ""
                    for label in issue_data.get("labels") or []
                    if label.get("name")
                ]
                is_gfi = any(
                    "good first issue" in label.lower()
                    or "beginner" in label.lower()
                    or "easy" in label.lower()
                    for label in labels
                )

                created_at = parse_datetime(issue_data.get("created_at")) or datetime.now(UTC)
                closed_at = parse_datetime(issue_data.get("closed_at"))

                if progress_callback and idx % max(1, total_issues // 5) == 0:
                    progress_callback(
                        40 + int((idx / total_issues) * 15),
                        f"Processing comments for issue {idx + 1}/{total_issues}...",
                    )

                body_chunks = chunk_text(body_raw)
                for c_idx, chunk in enumerate(body_chunks):
                    chunk_title = title if len(body_chunks) == 1 else f"{title} (Chunk {c_idx + 1})"
                    issues.append(
                        Issue(
                            number=num,
                            title=chunk_title,
                            body=chunk,
                            state=state,
                            labels=labels,
                            comments=comments,
                            created_at=created_at,
                            closed_at=closed_at,
                            is_good_first_issue=is_gfi,
                        )
                    )

            if progress_callback:
                progress_callback(55, "Downloading closed pull requests from GitHub...")

            pull_requests = []
            prs_res = self._request(
                client, f"{base_api_url}/pulls", params={"state": "closed", "per_page": 100}
            )
            if prs_res.status_code == 200:
                for pr_data in prs_res.json():
                    num = pr_data.get("number")
                    title = pr_data.get("title") or ""
                    body = pr_data.get("body") or ""
                    state = pr_data.get("state") or "closed"
                    merged = pr_data.get("merged_at") is not None
                    linked_issue = None
                    issue_match = re.search(
                        r"(?:close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)\s+#(\d+)",
                        body,
                        re.IGNORECASE,
                    )
                    if issue_match:
                        linked_issue = int(issue_match.group(1))
                    created_at = parse_datetime(pr_data.get("created_at")) or datetime.now(UTC)
                    pull_requests.append(
                        PR(
                            number=num,
                            title=title,
                            body=body,
                            state=state,
                            merged=merged,
                            linked_issue=linked_issue,
                            created_at=created_at,
                        )
                    )

            return RepoSnapshot(
                owner=owner,
                repo=repo,
                fetched_at=datetime.now(UTC),
                metadata=metadata,
                readme=readme,
                contributing=contributing,
                file_tree=file_tree,
                tech_stack=tech_stack,
                issues=issues,
                pull_requests=pull_requests,
            )
