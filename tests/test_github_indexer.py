from unittest.mock import MagicMock, patch

from ingestion.github_indexer import (
    GitHubIndexer,
    chunk_text,
    detect_tech_stack,
    parse_github_url,
    should_skip_file,
)


def test_parse_github_url():
    assert parse_github_url("https://github.com/tiangolo/fastapi") == ("tiangolo", "fastapi")
    assert parse_github_url("https://github.com/tiangolo/fastapi.git") == ("tiangolo", "fastapi")
    assert parse_github_url("https://github.com/tiangolo/fastapi/") == ("tiangolo", "fastapi")


def test_should_skip_file():
    assert should_skip_file("README.md", 1_000_000) is False
    assert should_skip_file("pyproject.toml", 500_000) is False
    assert should_skip_file("weights.pt", 100) is True
    assert should_skip_file("data/raw.json", 100) is True
    assert should_skip_file("src/main.py", 100_001) is True
    assert should_skip_file("src/main.py", 500) is False


def test_chunk_text():
    assert chunk_text("Hello World") == ["Hello World"]
    long_text = "a" * 1500
    chunks = chunk_text(long_text, chunk_size=500, overlap=100)
    assert len(chunks) > 1
    assert all(len(c) == 500 for c in chunks[:-1])
    assert len(chunks[-1]) <= 500


def test_detect_tech_stack():
    js_files = {"package.json": '{"dependencies": {"react": "^18.0.0"}}'}
    assert detect_tech_stack(js_files)["language"] == "JavaScript/TypeScript"
    assert "react" in detect_tech_stack(js_files)["frameworks"]

    py_files = {
        "requirements.txt": "fastapi>=0.100.0\nsqlalchemy",
        "Dockerfile": "FROM python",
    }
    tech = detect_tech_stack(py_files)
    assert tech["language"] == "Python"
    assert "fastapi" in tech["frameworks"]
    assert "Docker" in tech["build_tools"]


@patch("ingestion.github_indexer.check_rate_limit")
@patch("httpx.Client.get")
def test_fetcher_invokes_endpoints(mock_get, mock_check_rate_limit):
    def make_mock(status_code, json_data=None, text=""):
        m = MagicMock()
        m.status_code = status_code
        if json_data is not None:
            m.json.return_value = json_data
        m.text = text
        return m

    mock_meta = make_mock(200, {
        "stargazers_count": 10,
        "language": "Python",
        "description": "Test Repo",
        "topics": ["test"],
    })
    mock_readme = make_mock(200, {"content": "UkVBRE1FIGluZm8="})
    mock_contrib = make_mock(404)
    mock_contents = make_mock(200, [
        {"path": "requirements.txt", "type": "file", "url": "https://api.github.com/file/reqs"},
        {"path": "src", "type": "dir"},
    ])
    mock_reqs = make_mock(200, {"content": "ZmFzdGFwaQ=="})
    mock_github_dir = make_mock(404)
    mock_issues = make_mock(200, [
        {
            "number": 1,
            "title": "Bug 1",
            "body": "This is a bug report",
            "state": "open",
            "labels": [{"name": "bug"}, {"name": "good first issue"}],
            "created_at": "2026-06-08T12:00:00Z",
            "closed_at": None,
        }
    ])
    mock_comments = make_mock(200, [{"body": "Comment 1"}])
    mock_prs = make_mock(200, [
        {
            "number": 2,
            "title": "PR 1",
            "body": "Fixes #1",
            "state": "closed",
            "merged_at": "2026-06-08T12:30:00Z",
            "created_at": "2026-06-08T12:15:00Z",
        }
    ])

    mock_get.side_effect = [
        mock_meta,
        mock_readme,
        mock_contrib,
        mock_contents,
        mock_reqs,
        mock_github_dir,
        mock_issues,
        mock_issues,
        mock_issues,
        mock_comments,
        mock_comments,
        mock_comments,
        mock_prs,
    ]

    fetcher = GitHubIndexer(github_token="dummy")
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


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = ""

    def json(self):
        return self._payload


def _fake_request(self, client, url, params=None):
    """Canned GitHub responses, enough for fetch_repo to run to completion."""
    if url.endswith("/repos/null_owner/null_description"):
        # What GitHub actually returns for a repository with no description or topics.
        return _FakeResponse(
            {"stargazers_count": 0, "language": None, "description": None, "topics": None}
        )
    if "/readme" in url or "/contents/CONTRIBUTING.md" in url or "/contents/.github" in url:
        return _FakeResponse({}, 404)
    if url.endswith("/contents/"):
        return _FakeResponse([{"path": "README.md", "type": "file", "url": "u"}])
    if "/issues" in url or "/pulls" in url:
        return _FakeResponse([])
    return _FakeResponse({}, 404)


def test_fetch_repo_normalises_null_description_and_topics(monkeypatch):
    """A null description must not survive as None.

    `.get(key, default)` only falls back when the key is absent, so `None` would be kept
    and later break the DNA summary join -- the failure reported as
    "sequence item 3: expected str instance, NoneType found".
    """
    from ingestion.ingestion_pipeline import generate_repo_dna_summary

    monkeypatch.setattr(GitHubIndexer, "_request", _fake_request)
    snapshot = GitHubIndexer(github_token="dummy").fetch_repo(
        "https://github.com/null_owner/null_description"
    )

    assert snapshot.metadata["description"] == ""
    assert snapshot.metadata["topics"] == []

    # The consumer must survive it end to end.
    summary = generate_repo_dna_summary(snapshot)
    assert "No description available." in summary
    assert "null_owner/null_description" in summary
