"""FastAPI application for the TaskChain autonomous repository agent."""
import json
import logging
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
from agent.code_tools import CodeReader, build_code_context
from agent.executor import Executor
from agent.planner import Planner
from agent.verifier import Verifier
from github.pr_client import PullRequestClient
from ingestion.docs_collector import build_docs_context
from ingestion.ingestion_pipeline import ingest_repository
from ingestion.sqlite_indexer import keyword_search
from ingestion.workspace import get_workspace
from llm.client import build_llm_client, resolve_llm_settings
from utils.db import RepoIngestion, get_db, init_db
from utils.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

UI_DIR = Path(__file__).resolve().parents[1] / "ui"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="TaskChain — Autonomous Repository Agent",
    description="RAG-powered GitHub repository Q&A and issue-to-PR automation.",
    version="1.0.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=UI_DIR), name="static")


class IngestRequest(BaseModel):
    repo_url: str


class AskRequest(BaseModel):
    question: str


class FixRequest(BaseModel):
    issue_description: str


class RefineRequest(BaseModel):
    session_id: str
    feedback: str


class PROpenRequest(BaseModel):
    title: str
    body: str
    head_branch: str
    base_branch: str = "main"


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(UI_DIR / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/repos/ingest")
def trigger_ingestion(request: IngestRequest, background_tasks: BackgroundTasks):
    if not request.repo_url.strip():
        raise HTTPException(status_code=400, detail="Repository URL cannot be empty")

    from ingestion.github_indexer import parse_github_url
    try:
        owner, repo = parse_github_url(request.repo_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    repo_id = f"{owner}/{repo}"
    db = next(get_db())
    try:
        existing = db.query(RepoIngestion).filter_by(owner=owner, repo=repo).first()
        if existing and existing.status == "complete":
            ingested_at = existing.ingested_at or datetime.now(UTC)
            if ingested_at.tzinfo is None:
                ingested_at = ingested_at.replace(tzinfo=UTC)
            age = datetime.now(UTC) - ingested_at
            if age < timedelta(days=config.INGESTION_REFRESH_DAYS):
                existing.progress_pct = 100
                existing.status_message = "Complete!"
                db.commit()
                return {"repo_id": repo_id, "status": "cached"}
    finally:
        db.close()

    background_tasks.add_task(ingest_repository, request.repo_url)
    return {"repo_id": repo_id, "status": "queued"}


@app.get("/repos/{owner}/{repo}/status")
def get_ingestion_status(owner: str, repo: str):
    db = next(get_db())
    try:
        ingestion = db.query(RepoIngestion).filter_by(owner=owner, repo=repo).first()
        if not ingestion:
            return {
                "status": "not_found",
                "ingested_at": None,
                "progress_pct": 0,
                "status_message": None,
            }
        return {
            "status": ingestion.status,
            "ingested_at": ingestion.ingested_at,
            "progress_pct": ingestion.progress_pct,
            "status_message": ingestion.status_message,
            "issue_count": ingestion.issue_count,
            "pr_count": ingestion.pr_count,
        }
    finally:
        db.close()


ASK_STAGES = ["summary", "docs", "history", "file_selection", "code_read", "answering"]


def _ask_event(stage: str, status: str, **extra) -> dict:
    event = {"stage": stage, "status": status, "ts": datetime.now(UTC).isoformat()}
    event.update(extra)
    return event


def _select_code_files(repo_id: str, question: str, file_tree: list[str]) -> list[str]:
    """Tier 2 step 1: ask the LLM which files to read (read-only selection)."""
    if not file_tree:
        return []
    settings = resolve_llm_settings()
    client = build_llm_client(settings)
    tree_text = "\n".join(file_tree)
    response = client.chat.completions.create(
        model=settings.model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a code exploration assistant. Given a repository file "
                    "tree and a question, list up to "
                    f"{config.MAX_SELECTED_FILES} file paths most likely to contain "
                    "the answer. Respond with ONLY a JSON array of path strings, "
                    "no explanations."
                ),
            },
            {
                "role": "user",
                "content": f"File tree:\n{tree_text}\n\nQuestion: {question}",
            },
        ],
        temperature=0.0,
        max_tokens=512,
    )
    raw = response.choices[0].message.content or "[]"
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        return []
    selected = json.loads(match.group(0))
    tree_set = set(file_tree)
    return [p for p in selected if isinstance(p, str) and p in tree_set]


def _ask_pipeline(owner: str, repo: str, question: str):
    """Run the three-tier Q&A pipeline, yielding progress events as it goes.

    Events are dicts: {"stage", "status", "ts", ...stage-specific detail}.
    The final event is stage="done" and carries the full answer payload.
    On failure, a stage="error" event is yielded and the generator stops.
    """
    repo_id = f"{owner}/{repo}"
    logger.info(f"Q&A for {repo_id}: {question[:80]}...")

    # ---- Tier 0: repository summary (DNA) ----
    yield _ask_event("summary", "started")
    db = next(get_db())
    try:
        ingestion = db.query(RepoIngestion).filter_by(owner=owner, repo=repo).first()
        dna_summary = ingestion.dna_summary if ingestion else ""
    finally:
        db.close()
    yield _ask_event("summary", "done", has_summary=bool(dna_summary))

    # ---- Tier 1: docs, injected directly under a character budget ----
    yield _ask_event("docs", "started")
    docs_context = build_docs_context(repo_id)
    yield _ask_event("docs", "done", chars=len(docs_context))

    # ---- Tier 3: history (issues/PRs) via keyword RAG ----
    yield _ask_event("history", "started")
    history = keyword_search(repo_id, question, top_k=config.KEYWORD_TOP_K)
    yield _ask_event("history", "done", hits=len(history))

    # ---- Tier 2: code, read-only tool access on the local workspace ----
    files_read: list[str] = []
    code_context = ""
    workspace = get_workspace(repo_id)
    if workspace:
        try:
            reader = CodeReader(workspace)
            file_tree = reader.list_files()
            yield _ask_event("file_selection", "started", candidates=len(file_tree))
            selected = _select_code_files(repo_id, question, file_tree)
            yield _ask_event("file_selection", "done", selected=selected)

            yield _ask_event("code_read", "started")
            code_context, files_read = build_code_context(workspace, selected)
            yield _ask_event("code_read", "done", files=files_read)
        except Exception as exc:
            logger.warning(f"Code retrieval skipped for {repo_id}: {exc}")
            yield _ask_event("code_read", "skipped", detail=str(exc))
    else:
        yield _ask_event("code_read", "skipped", detail="no workspace (not ingested)")

    # ---- Compose the three tiers into one prompt ----
    system_prompt = (
        "You are a helpful repository assistant. Answer the user's question using "
        "only the provided repository context. Cite specific files or issue numbers "
        "when possible. If you do not know, say so."
    )

    context_text = f"Repository: {repo_id}\n\n## Repository summary\n"
    context_text += dna_summary or "No repository summary available."
    if docs_context:
        context_text += f"\n\n## Documentation\n{docs_context}"
    if code_context:
        context_text += f"\n\n## Code (files read: {', '.join(files_read)})\n{code_context}"
    if history:
        history_lines = "\n".join(
            f"- #{item['number']} ({item['type']}, {item['state']}): {item['title']}"
            for item in history
        )
        context_text += f"\n\n## Related issues and pull requests\n{history_lines}"

    user_prompt = f"{context_text}\n\nQuestion: {question}"

    yield _ask_event("answering", "started")
    try:
        settings = resolve_llm_settings()
        client = build_llm_client(settings)
        response = client.chat.completions.create(
            model=settings.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=1024,
        )
        answer = response.choices[0].message.content or ""
    except Exception as exc:
        logger.exception(f"Q&A failed for {repo_id}: {exc}")
        yield _ask_event("error", "failed", detail=f"Q&A failed: {exc}")
        return

    result = {
        "repo_id": repo_id,
        "question": question,
        "answer": answer,
        "sources": {
            "docs_chars": len(docs_context),
            "code_files_read": files_read,
            "history": history,
        },
    }
    yield _ask_event("done", "done", result=result)

@app.post("/repos/{owner}/{repo}/ask")
def ask_about_repo(owner: str, repo: str, request: AskRequest):
    """Non-streaming Q&A: runs the pipeline and returns only the final result."""
    final = None
    error_detail = "Q&A failed"
    for event in _ask_pipeline(owner, repo, request.question):
        if event["stage"] == "done":
            final = event["result"]
        elif event["stage"] == "error":
            error_detail = event.get("detail", error_detail)
    if final is None:
        raise HTTPException(status_code=500, detail=error_detail)
    return final


@app.get("/repos/{owner}/{repo}/ask/stream")
def ask_about_repo_stream(owner: str, repo: str, question: str):
    """Server-Sent Events endpoint: streams live pipeline progress + answer."""
    from fastapi.responses import StreamingResponse

    def event_stream():
        for event in _ask_pipeline(owner, repo, question):
            yield f"data: {json.dumps(event)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/repos/{owner}/{repo}/fix")
def fix_issue(owner: str, repo: str, request: FixRequest):
    repo_id = f"{owner}/{repo}"
    logger.info(f"Issue→PR for {repo_id}: {request.issue_description[:80]}...")

    db = next(get_db())
    try:
        ingestion = db.query(RepoIngestion).filter_by(owner=owner, repo=repo).first()
        if not ingestion or ingestion.status != "complete":
            raise HTTPException(
                status_code=400,
                detail="Repository has not been ingested yet. Call /repos/ingest first.",
            )
        dna_summary = ingestion.dna_summary or ""
    finally:
        db.close()

    context = keyword_search(repo_id, request.issue_description, top_k=config.KEYWORD_TOP_K)
    planner = Planner()
    plan = planner.plan(
        repo_id=repo_id,
        issue_description=request.issue_description,
        context={"dna_summary": dna_summary, "related_issues": context},
    )

    executor = Executor(repo_id=repo_id)
    execution_result = executor.execute(plan)

    verifier = Verifier(repo_id=repo_id)
    verification_result = verifier.verify(
        execution_result, issue_description=request.issue_description
    )

    summary = (
        f"Planned a fix for: {request.issue_description}\n\n"
        f"Plan:\n{plan['plan']}\n\n"
        f"Verification:\n{verification_result['review']}"
    )

    return {
        "repo_id": repo_id,
        "issue": request.issue_description,
        "plan": plan["plan"],
        "diff": execution_result["diff"],
        "verification": verification_result,
        "summary": summary,
    }


@app.post("/repos/{owner}/{repo}/refine")
def refine_fix(owner: str, repo: str, request: RefineRequest):
    repo_id = f"{owner}/{repo}"
    logger.info(f"Refinement for {repo_id}: {request.feedback[:80]}...")

    # In a full implementation, session state would be persisted and re-executed.
    # Here we return a structured response that the frontend can use to re-run /fix.
    return {
        "repo_id": repo_id,
        "session_id": request.session_id,
        "feedback": request.feedback,
        "message": "Incorporate this feedback and re-submit the issue description to /fix.",
    }


@app.post("/repos/{owner}/{repo}/pulls")
def open_pull_request(owner: str, repo: str, request: PROpenRequest):
    repo_id = f"{owner}/{repo}"
    logger.info(f"Opening PR for {repo_id}: {request.title}")
    try:
        client = PullRequestClient()
        pr = client.open_pr(
            owner=owner,
            repo=repo,
            title=request.title,
            body=request.body,
            head_branch=request.head_branch,
            base_branch=request.base_branch,
        )
        return {
            "repo_id": repo_id,
            "pr_number": pr.get("number"),
            "html_url": pr.get("html_url"),
        }
    except Exception as exc:
        logger.exception(f"Failed to open PR for {repo_id}: {exc}")
        raise HTTPException(status_code=500, detail=f"Failed to open PR: {exc}") from exc
