import os
import re
import time
import logging
from datetime import datetime, timezone
import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# File filtering rules
SKIP_EXTENSIONS = [
    ".bin", ".pt", ".ckpt", ".h5", ".pkl",
    ".parquet", ".csv", ".zip", ".tar", ".gz",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".mp4", ".mp3", ".woff", ".woff2"
]

SKIP_PATHS = ["data/", "datasets/", "weights/", "checkpoints/", "dist/", "build/"]

MAX_FILE_SIZE_BYTES = 100_000  # 100KB

ALWAYS_KEEP = [
    "README.md", "CONTRIBUTING.md", "CHANGELOG.md",
    "pyproject.toml", "requirements.txt", "package.json",
    "Dockerfile", "docker-compose.yml"
]

class Issue(BaseModel):
    number: int
    title: str
    body: str
    state: str              # open | closed
    labels: list[str]
    comments: list[str]     # comment bodies only
    created_at: datetime
    closed_at: datetime | None
    is_good_first_issue: bool  # derived from labels

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
    metadata: dict          # stars, language, description, topics
    readme: str
    contributing: str | None
    file_tree: list[str]    # relative paths only
    tech_stack: dict        # detected from config files
    issues: list[Issue]
    pull_requests: list[PR]


def parse_github_url(url: str) -> tuple[str, str]:
    """Parse owner and repo name from GitHub URL."""
    match = re.search(r"github\.com/([^/]+)/([^/]+)", url)
    if not match:
        raise ValueError(f"Invalid GitHub URL: {url}")
    owner = match.group(1)
    repo = match.group(2)
    # Remove trailing .git or slashes if any
    if repo.endswith(".git"):
        repo = repo[:-4]
    return owner, repo.strip("/")


def check_rate_limit(headers: httpx.Headers) -> None:
    """Check rate limit headers and sleep if remaining quota is low."""
    remaining = headers.get("X-RateLimit-Remaining")
    reset_time = headers.get("X-RateLimit-Reset")
    if remaining is not None:
        try:
            rem = int(remaining)
            if rem < 100 and reset_time is not None:
                reset_at = float(reset_time)
                sleep_duration = max(0.0, reset_at - time.time()) + 1.0
                logger.warning(
                    f"GitHub API Rate Limit low (Remaining: {rem}). Sleeping for {sleep_duration:.1f}s until reset."
                )
                time.sleep(sleep_duration)
        except ValueError:
            pass


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
    """Split long text > 1000 characters into overlapping chunks."""
    if not text:
        return [""]
    if len(text) <= 1000:
        return [text]
        
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start += (chunk_size - overlap)
        if start >= len(text):
            break
    return chunks


def detect_tech_stack(file_contents: dict[str, str]) -> dict:
    """Analyze root-level config files to detect programming language and frameworks."""
    tech = {
        "language": None,
        "frameworks": [],
        "build_tools": [],
        "config_files": list(file_contents.keys())
    }
    
    if "package.json" in file_contents:
        tech["language"] = "JavaScript/TypeScript"
        try:
            import json
            data = json.loads(file_contents["package.json"])
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            for fw in ["react", "next", "vue", "svelte", "express", "nest", "typescript"]:
                if fw in deps:
                    tech["frameworks"].append(fw)
        except Exception:
            pass
            
    elif "requirements.txt" in file_contents or "pyproject.toml" in file_contents or "setup.py" in file_contents:
        tech["language"] = "Python"
        all_text = (file_contents.get("requirements.txt", "") + "\n" + file_contents.get("pyproject.toml", "")).lower()
        for fw in ["fastapi", "django", "flask", "streamlit", "langchain", "langgraph", "sqlalchemy", "numpy", "pandas"]:
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
    """Parse ISO datetime string from GitHub API."""
    if not dt_str:
        return None
    # GitHub ISO strings end with 'Z', python datetime.fromisoformat supports it in 3.11+
    dt_str = dt_str.replace("Z", "+00:00")
    return datetime.fromisoformat(dt_str)


class GitHubFetcher:
    def __init__(self, github_token: str | None = None):
        self.github_token = github_token or os.getenv("GITHUB_TOKEN")
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
        }
        if self.github_token:
            self.headers["Authorization"] = f"token {self.github_token}"
            
    def _request(self, client: httpx.Client, url: str, params: dict | None = None) -> httpx.Response:
        """Helper to make requests and check rate limits."""
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
            # 1. Repo metadata
            meta_res = self._request(client, base_api_url)
            if meta_res.status_code == 404:
                raise ValueError(f"GitHub repository not found: {owner}/{repo}")
            meta_data = meta_res.json()
            metadata = {
                "stars": meta_data.get("stargazers_count", 0),
                "language": meta_data.get("language"),
                "description": meta_data.get("description", ""),
                "topics": meta_data.get("topics", []),
            }
            
            if progress_callback:
                progress_callback(15, "Fetching README and CONTRIBUTING guidelines...")
                
            # 2. README.md
            readme = ""
            readme_res = self._request(client, f"{base_api_url}/readme")
            if readme_res.status_code == 200:
                try:
                    # readme content is base64 encoded or sometimes raw
                    readme_data = readme_res.json()
                    import base64
                    readme = base64.b64decode(readme_data.get("content", "")).decode("utf-8")
                except Exception as e:
                    logger.warning(f"Failed to decode readme: {e}")
                    readme = readme_res.text
                    
            # 3. CONTRIBUTING.md
            contributing = None
            contrib_res = self._request(client, f"{base_api_url}/contents/CONTRIBUTING.md")
            if contrib_res.status_code == 200:
                try:
                    contrib_data = contrib_res.json()
                    import base64
                    contributing = base64.b64decode(contrib_data.get("content", "")).decode("utf-8")
                except Exception as e:
                    logger.warning(f"Failed to decode CONTRIBUTING.md: {e}")
                    contributing = contrib_res.text
                    
            # 4. Top-level file tree
            if progress_callback:
                progress_callback(20, "Scanning top-level repository structures...")
                
            file_tree = []
            tech_stack_files = {}
            contents_res = self._request(client, f"{base_api_url}/contents/")
            if contents_res.status_code == 200:
                for item in contents_res.json():
                    path = item.get("path", "")
                    file_tree.append(path)
                    
                    # Fetch short tech stack files for detection
                    filename = os.path.basename(path)
                    if filename in ALWAYS_KEEP and item.get("type") == "file":
                        file_res = self._request(client, item.get("url"))
                        if file_res.status_code == 200:
                            try:
                                import base64
                                content_decoded = base64.b64decode(file_res.json().get("content", "")).decode("utf-8")
                                tech_stack_files[filename] = content_decoded
                            except Exception:
                                pass

            # 5. Check if .github/ exists and fetch top-level content inside it
            github_res = self._request(client, f"{base_api_url}/contents/.github")
            if github_res.status_code == 200:
                for item in github_res.json():
                    file_tree.append(item.get("path", ""))

            tech_stack = detect_tech_stack(tech_stack_files)
            
            if progress_callback:
                progress_callback(30, "Downloading open issues from GitHub...")
                
            # 6. Fetch Open Issues (top 100)
            issues_list = []
            open_issues_res = self._request(client, f"{base_api_url}/issues", params={"state": "open", "per_page": 100})
            if open_issues_res.status_code == 200:
                raw_open_issues = open_issues_res.json()
                for issue_data in raw_open_issues:
                    if "pull_request" in issue_data:
                        continue
                    issues_list.append(issue_data)
                    
            # 7. Fetch Closed Issues (top 200, pages 1 & 2)
            if progress_callback:
                progress_callback(35, "Downloading closed issues from GitHub...")
                
            for page in [1, 2]:
                closed_issues_res = self._request(client, f"{base_api_url}/issues", params={"state": "closed", "per_page": 100, "page": page})
                if closed_issues_res.status_code == 200:
                    raw_closed_issues = closed_issues_res.json()
                    if not raw_closed_issues:
                        break
                    for issue_data in raw_closed_issues:
                        if "pull_request" in issue_data:
                            continue
                        issues_list.append(issue_data)
                else:
                    break
                    
            # Process and chunk issues
            issues = []
            total_issues = len(issues_list)
            if progress_callback:
                progress_callback(40, f"Processing comments for {total_issues} issues...")
                
            for idx, issue_data in enumerate(issues_list):
                num = issue_data.get("number")
                title = issue_data.get("title", "")
                body_raw = issue_data.get("body") or ""
                state = issue_data.get("state", "open")
                
                # Fetch comments
                comments = []
                comments_res = self._request(client, f"{base_api_url}/issues/{num}/comments")
                if comments_res.status_code == 200:
                    comments = [c.get("body", "") for c in comments_res.json() if c.get("body")]
                    
                labels = [l.get("name", "") for l in issue_data.get("labels", [])]
                is_gfi = any("good first issue" in l.lower() or "beginner" in l.lower() or "easy" in l.lower() for l in labels)
                
                created_at = parse_datetime(issue_data.get("created_at")) or datetime.now(timezone.utc)
                closed_at = parse_datetime(issue_data.get("closed_at"))
                
                # Update progress incrementally inside comments processing loop
                if progress_callback and idx % max(1, total_issues // 5) == 0:
                    progress_callback(40 + int((idx / total_issues) * 15), f"Processing comments for issue {idx+1}/{total_issues}...")
                
                # Apply chunking to issue body if > 1000 characters
                body_chunks = chunk_text(body_raw)
                for c_idx, chunk in enumerate(body_chunks):
                    # For chunks, append suffix to title to distinguish them
                    chunk_title = title if len(body_chunks) == 1 else f"{title} (Chunk {c_idx+1})"
                    issues.append(Issue(
                        number=num,
                        title=chunk_title,
                        body=chunk,
                        state=state,
                        labels=labels,
                        comments=comments,
                        created_at=created_at,
                        closed_at=closed_at,
                        is_good_first_issue=is_gfi
                    ))

            # 8. Fetch Closed/Merged PRs (top 100)
            if progress_callback:
                progress_callback(55, "Downloading closed pull requests from GitHub...")
                
            pull_requests = []
            prs_res = self._request(client, f"{base_api_url}/pulls", params={"state": "closed", "per_page": 100})
            if prs_res.status_code == 200:
                raw_prs = prs_res.json()
                for pr_data in raw_prs:
                    num = pr_data.get("number")
                    title = pr_data.get("title", "")
                    body = pr_data.get("body") or ""
                    state = pr_data.get("state", "closed")
                    merged = pr_data.get("merged_at") is not None
                    
                    # Try to find a linked issue number in the PR body (e.g. "fixes #123", "closes #456")
                    linked_issue = None
                    issue_match = re.search(r"(?:close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)\s+#(\d+)", body, re.IGNORECASE)
                    if issue_match:
                        linked_issue = int(issue_match.group(1))
                        
                    created_at = parse_datetime(pr_data.get("created_at")) or datetime.now(timezone.utc)
                    
                    pull_requests.append(PR(
                        number=num,
                        title=title,
                        body=body,
                        state=state,
                        merged=merged,
                        linked_issue=linked_issue,
                        created_at=created_at
                    ))
                    
            return RepoSnapshot(
                owner=owner,
                repo=repo,
                fetched_at=datetime.now(timezone.utc),
                metadata=metadata,
                readme=readme,
                contributing=contributing,
                file_tree=file_tree,
                tech_stack=tech_stack,
                issues=issues,
                pull_requests=pull_requests
            )
