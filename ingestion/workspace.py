"""Tier 2 workspace: download a repo's code to disk for read-only agent access.

The workspace is the filesystem the code-reading tools operate on. Nothing in
the query pipeline ever writes here after ingestion completes — the LLM only
ever reads files or searches text.
"""
import io
import logging
import tarfile
from pathlib import Path

import httpx

import config
from ingestion.github_indexer import parse_github_url, should_skip_file

logger = logging.getLogger(__name__)

TARBALL_URL = "https://codeload.github.com/{owner}/{repo}/tar.gz/HEAD"

TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".rb",
    ".c", ".h", ".cpp", ".hpp", ".cs", ".php", ".sh", ".sql",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env.example",
    ".html", ".css", ".md", ".rst", ".txt", ".xml", ".tf", ".proto",
}

# Always allow these even though they have no typical text extension
DOCS_EXTENSIONS = {".md", ".rst", ".txt"}
DOCS_BASENAMES = {
    "README", "CONTRIBUTING", "CHANGELOG", "LICENSE", "CODE_OF_CONDUCT",
    "ARCHITECTURE", "SECURITY",
}


def workspace_path(owner: str, repo: str) -> Path:
    """Local directory where a repo's code snapshot lives."""
    return config.DATA_DIR / "workspaces" / owner / repo


def get_workspace(repo_id: str) -> Path | None:
    """Return the workspace directory for a repo_id, or None if not ingested."""
    if "/" not in repo_id:
        return None
    owner, repo = repo_id.split("/", 1)
    ws = workspace_path(owner, repo)
    return ws if ws.is_dir() else None


def _is_text_file(path: str) -> bool:
    from os.path import basename, splitext
    name = basename(path)
    stem, ext = splitext(name)
    if ext.lower() in TEXT_EXTENSIONS:
        return True
    # Config files without extensions (Dockerfile, Makefile, etc.)
    if stem.upper() in DOCS_BASENAMES or name in {
        "Dockerfile", "Makefile", "Procfile", ".gitignore", ".env.example",
    }:
        return True
    return False


def download_workspace(repo_url: str) -> Path:
    """Download the repo tarball and extract relevant text files read-only.

    Files are filtered with the same skip rules as indexing (binaries, large
    files, build/data dirs are excluded). Extraction is path-safe: members are
    resolved inside the workspace directory before writing.
    """
    owner, repo = parse_github_url(repo_url)
    ws = workspace_path(owner, repo)

    # Idempotent: a fresh ingest replaces the old snapshot atomically.
    staging = ws.parent / f".{repo}.staging"
    if staging.exists():
        import shutil
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    url = TARBALL_URL.format(owner=owner, repo=repo)
    logger.info(f"Downloading workspace tarball for {owner}/{repo}")
    extracted = 0
    with httpx.Client(follow_redirects=True, timeout=120.0) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            buffer = io.BytesIO()
            for chunk in response.iter_bytes():
                buffer.write(chunk)
            buffer.seek(0)

            with tarfile.open(fileobj=buffer, mode="r:gz") as tar:
                for member in tar.getmembers():
                    if not member.isfile():
                        continue
                    # Strip the top-level "<repo>-<sha>/" prefix from tar paths.
                    parts = member.name.split("/", 1)
                    if len(parts) < 2 or not parts[1]:
                        continue
                    rel_path = parts[1]
                    if should_skip_file(rel_path, member.size):
                        continue
                    if not _is_text_file(rel_path):
                        continue

                    target = (staging / rel_path).resolve()
                    if not str(target).startswith(str(staging.resolve())):
                        # Path traversal attempt in the tarball — skip.
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with tar.extractfile(member) as src, open(target, "wb") as dst:
                        dst.write(src.read())
                    extracted += 1

    # Swap into place.
    if ws.exists():
        import shutil
        shutil.rmtree(ws)
    ws.parent.mkdir(parents=True, exist_ok=True)
    staging.rename(ws)
    logger.info(f"Extracted {extracted} files into workspace for {owner}/{repo}")
    return ws
