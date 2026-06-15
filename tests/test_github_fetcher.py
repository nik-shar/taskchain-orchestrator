import pytest
import time
import httpx
from unittest.mock import MagicMock, patch
from ingestion.github_fetcher import (
    parse_github_url,
    should_skip_file,
    chunk_text,
    detect_tech_stack,
    GitHubFetcher
)

def test_parse_github_url():
    assert parse_github_url("https://github.com/tiangolo/fastapi") == ("tiangolo", "fastapi")
    assert parse_github_url("https://github.com/tiangolo/fastapi.git") == ("tiangolo", "fastapi")
    assert parse_github_url("https://github.com/tiangolo/fastapi/") == ("tiangolo", "fastapi")

def test_should_skip_file():
    # Always keep
    assert should_skip_file("README.md", 1000000) is False
    assert should_skip_file("pyproject.toml", 500000) is False
    # Skip extensions
    assert should_skip_file("weights.pt", 100) is True
    # Skip path
    assert should_skip_file("data/raw.json", 100) is True
    # Max size
    assert should_skip_file("src/main.py", 100001) is True
    # Keep normal file
    assert should_skip_file("src/main.py", 500) is False

def test_chunk_text():
    short_text = "Hello World"
    assert chunk_text(short_text) == [short_text]
    
    long_text = "a" * 1500
    chunks = chunk_text(long_text, chunk_size=500, overlap=100)
    assert len(chunks) > 1
    assert all(len(c) == 500 for c in chunks[:-1])
    assert len(chunks[-1]) <= 500

def test_detect_tech_stack():
    # Javascript
    js_files = {"package.json": '{"dependencies": {"react": "^18.0.0"}}'}
    assert detect_tech_stack(js_files)["language"] == "JavaScript/TypeScript"
    assert "react" in detect_tech_stack(js_files)["frameworks"]
    
    # Python
    py_files = {"requirements.txt": "fastapi>=0.100.0\nsqlalchemy", "Dockerfile": "FROM python"}
    tech = detect_tech_stack(py_files)
    assert tech["language"] == "Python"
    assert "fastapi" in tech["frameworks"]
    assert "Docker" in tech["build_tools"]

@patch("ingestion.github_fetcher.check_rate_limit")
@patch("httpx.Client.get")
def test_fetcher_invokes_endpoints(mock_get, mock_check_rate_limit):
    # Setup response mocks
    mock_meta = MagicMock()
    mock_meta.status_code = 200
    mock_meta.json.return_value = {
        "stargazers_count": 10,
        "language": "Python",
        "description": "Test Repo",
        "topics": ["test"]
    }
    
    mock_readme = MagicMock()
    mock_readme.status_code = 200
    # base64 encoded readme: "README info"
    mock_readme.json.return_value = {"content": "UkVBRE1FIGluZm8="}
    
    mock_contrib = MagicMock()
    mock_contrib.status_code = 404 # No contributing doc
    
    mock_contents = MagicMock()
    mock_contents.status_code = 200
    mock_contents.json.return_value = [
        {"path": "requirements.txt", "type": "file", "url": "https://api.github.com/file/reqs"},
        {"path": "src", "type": "dir"}
    ]
    
    mock_reqs = MagicMock()
    mock_reqs.status_code = 200
    # base64 encoded reqs: "fastapi"
    mock_reqs.json.return_value = {"content": "ZmFzdGFwaQ=="}

    mock_github_dir = MagicMock()
    mock_github_dir.status_code = 404
    
    mock_issues = MagicMock()
    mock_issues.status_code = 200
    mock_issues.json.return_value = [
        {
            "number": 1,
            "title": "Bug 1",
            "body": "This is a bug report",
            "state": "open",
            "labels": [{"name": "bug"}, {"name": "good first issue"}],
            "created_at": "2026-06-08T12:00:00Z",
            "closed_at": None
        }
    ]
    
    mock_comments = MagicMock()
    mock_comments.status_code = 200
    mock_comments.json.return_value = [{"body": "Comment 1"}]
    
    mock_prs = MagicMock()
    mock_prs.status_code = 200
    mock_prs.json.return_value = [
        {
            "number": 2,
            "title": "PR 1",
            "body": "Fixes #1",
            "state": "closed",
            "merged_at": "2026-06-08T12:30:00Z",
            "created_at": "2026-06-08T12:15:00Z"
        }
    ]
    
    # Side effects to match fetcher requests order
    mock_get.side_effect = [
        mock_meta,       # meta
        mock_readme,     # readme
        mock_contrib,    # contributing
        mock_contents,   # contents list
        mock_reqs,       # reqs content
        mock_github_dir, # .github dir check
        mock_issues,     # open issues
        mock_issues,     # closed issues p1
        mock_issues,     # closed issues p2 (empty or same)
        mock_comments,   # comments for issue 1 (from open)
        mock_comments,   # comments for issue 1 (from closed p1)
        mock_comments,   # comments for issue 1 (from closed p2)
        mock_prs,        # closed pulls
    ]
    
    fetcher = GitHubFetcher(github_token="dummy")
    snapshot = fetcher.fetch_repo("https://github.com/owner/repo")
    
    assert snapshot.owner == "owner"
    assert snapshot.repo == "repo"
    assert snapshot.metadata["stars"] == 10
    assert "README info" in snapshot.readme
    assert snapshot.tech_stack["language"] == "Python"
    assert "fastapi" in snapshot.tech_stack["frameworks"]
    assert len(snapshot.issues) > 0
    assert snapshot.issues[0].title == "Bug 1"
    assert snapshot.issues[0].is_good_first_issue is True
    assert len(snapshot.pull_requests) == 1
    assert snapshot.pull_requests[0].linked_issue == 1
