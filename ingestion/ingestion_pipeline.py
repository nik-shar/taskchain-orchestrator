"""End-to-end ingestion pipeline for a GitHub repository."""
import logging
import time
from datetime import UTC, datetime

from ingestion.code_indexer import index_source_files
from ingestion.docs_collector import collect_docs
from ingestion.github_indexer import GitHubIndexer, parse_github_url
from ingestion.sqlite_indexer import index_issues_and_prs
from ingestion.workspace import download_workspace
from utils.db import RepoIngestion, SessionLocal

logger = logging.getLogger(__name__)


def update_progress(owner: str, repo: str, progress_pct: int, status_message: str) -> None:
    """Persist intermediate progress for a repository ingestion."""
    db = SessionLocal()
    try:
        ingestion = db.query(RepoIngestion).filter_by(owner=owner, repo=repo).first()
        if ingestion:
            ingestion.progress_pct = progress_pct
            ingestion.status_message = status_message
            db.commit()
    except Exception as exc:
        logger.error(f"Failed to update progress for {owner}/{repo}: {exc}")
    finally:
        db.close()


def generate_repo_dna_summary(snapshot) -> str:
    """Generate a concise repository DNA summary from the fetched snapshot.

    Every field is coerced to a string. A repository with no description reports it as
    null from the GitHub API, and `.get(key, default)` does not cover that case, so a
    `None` here would otherwise break the `join` below.
    """
    description = snapshot.metadata.get("description") or "No description available."
    top_level = ", ".join(str(path) for path in snapshot.file_tree[:10]) or "none"
    lines = [
        f"## {snapshot.owner}/{snapshot.repo}",
        "",
        "### What this repo does",
        description,
        "",
        "### Tech stack",
        f"- Primary language: {snapshot.tech_stack.get('language') or 'unknown'}",
    ]
    if snapshot.tech_stack.get("frameworks"):
        frameworks = ", ".join(str(f) for f in snapshot.tech_stack["frameworks"])
        lines.append(f"- Frameworks/libraries: {frameworks}")
    if snapshot.tech_stack.get("build_tools"):
        build_tools = ", ".join(str(t) for t in snapshot.tech_stack["build_tools"])
        lines.append(f"- Build tools: {build_tools}")
    lines.extend([
        "",
        "### Entry points",
        f"- Top-level files: {top_level}",
        "",
        "### Recent activity",
        f"- Open issues: {sum(1 for i in snapshot.issues if i.state == 'open')}",
        f"- Closed issues/PRs indexed: {len(snapshot.issues) + len(snapshot.pull_requests)}",
    ])
    return "\n".join(lines)


def ingest_repository(repo_url: str) -> dict:
    """Run the end-to-end ingestion pipeline for a given repository URL."""
    owner, repo = parse_github_url(repo_url)
    repo_id = f"{owner}/{repo}"

    db = SessionLocal()
    try:
        ingestion = db.query(RepoIngestion).filter_by(owner=owner, repo=repo).first()
        if not ingestion:
            ingestion = RepoIngestion(
                owner=owner,
                repo=repo,
                status="pending",
                progress_pct=5,
                status_message="Parsing repository URL...",
            )
            db.add(ingestion)
        else:
            ingestion.status = "pending"
            ingestion.progress_pct = 5
            ingestion.status_message = "Parsing repository URL..."
            ingestion.ingested_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:
        # If we cannot even record state, there is nothing the UI can poll.
        logger.exception(f"Ingestion aborted for {repo_id}: cannot update DB: {exc}")
        raise
    finally:
        db.close()

    def progress_callback(pct, msg):
        update_progress(owner, repo, pct, msg)

    start_time = time.time()
    try:
        logger.info(f"Starting GitHub indexer for {repo_url}...")
        indexer = GitHubIndexer()
        snapshot = indexer.fetch_repo(repo_url, progress_callback=progress_callback)
        fetch_latency = time.time() - start_time

        logger.info("Generating repository DNA summary...")
        progress_callback(75, "Generating repository DNA summary...")
        dna_start = time.time()
        dna_summary = generate_repo_dna_summary(snapshot)
        dna_latency = time.time() - dna_start

        logger.info("Indexing in SQLite FTS5...")
        progress_callback(85, "Building keyword search index...")
        fts_start = time.time()
        index_issues_and_prs(repo_id, snapshot)
        fts_latency = time.time() - fts_start

        progress_callback(90, "Downloading code workspace for read-only access...")
        ws_start = time.time()
        workspace = download_workspace(repo_url)
        collect_docs(repo_id, workspace)

        progress_callback(95, "Indexing repository source files for search...")
        files_indexed = index_source_files(repo_id, workspace)
        ws_latency = time.time() - ws_start

        total_latency = time.time() - start_time
        latency_info = {
            "fetch_repo": fetch_latency,
            "generate_dna_summary": dna_latency,
            "index_fts": fts_latency,
            "download_workspace_index_code_and_docs": ws_latency,
            "total_ingestion": total_latency,
        }

        db = SessionLocal()
        try:
            ingestion = db.query(RepoIngestion).filter_by(owner=owner, repo=repo).first()
            if ingestion:
                ingestion.dna_summary = dna_summary
                ingestion.issue_count = len(snapshot.issues)
                ingestion.pr_count = len(snapshot.pull_requests)
                ingestion.status = "complete"
                ingestion.progress_pct = 100
                ingestion.status_message = "Complete!"
                db.commit()
        finally:
            db.close()

        # Emit the latency breakdown as a structured log field instead of a DB
        # column: JSONFormatter consumes `custom_fields`, and persisting it would
        # need a migration for databases created before such a column existed.
        logger.info(
            "Ingestion latency for %s: %s",
            repo_id,
            ", ".join(f"{name}={value:.2f}s" for name, value in latency_info.items()),
            extra={"custom_fields": {"latency_info": latency_info}},
        )

        logger.info(f"Ingestion completed successfully for {repo_id}!")
        return {
            "status": "complete",
            "repo_id": repo_id,
            "issue_count": len(snapshot.issues),
            "pr_count": len(snapshot.pull_requests),
            "files_indexed": files_indexed,
        }

    except Exception as exc:
        logger.exception(f"Ingestion failed for {repo_id}: {exc}")
        db = SessionLocal()
        try:
            ingestion = db.query(RepoIngestion).filter_by(owner=owner, repo=repo).first()
            if ingestion:
                ingestion.status = "failed"
                ingestion.status_message = f"Failed: {exc}"
                db.commit()
        except Exception as db_err:
            logger.error(f"Failed to record ingestion failure in DB: {db_err}")
        finally:
            db.close()
        raise
