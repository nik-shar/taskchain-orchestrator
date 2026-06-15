import logging
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from utils.logging_config import setup_logging
from utils.db import get_db, RepoIngestion, OnboardingGuide, UserFeedback, ChatMessage, OnboardingSessionState, HandoffSession
from ingestion.ingestion_pipeline import ingest_repository
from agent.onboarding_workflow import run_onboarding_workflow
from agent.onboarding_agent import get_onboarding_agent
from langchain_core.messages import HumanMessage, AIMessage

# Configure structured JSON logging
setup_logging()
logger = logging.getLogger(__name__)

UI_DIR = Path(__file__).resolve().parents[1] / "ui"

app = FastAPI(
    title="GitHub Contributor Onboarding Agent",
    description="RAG-powered GitHub repository onboarding checklist assistant",
    version="0.1.0"
)
app.mount("/static", StaticFiles(directory=UI_DIR), name="static")


@app.on_event("startup")
def on_startup():
    from utils.db import init_db
    init_db()


class IngestRequest(BaseModel):
    repo_url: str


class OnboardRequest(BaseModel):
    user_background: str


class FeedbackRequest(BaseModel):
    session_id: str | None = None
    rating: int
    background_hash: str


class ChatRequest(BaseModel):
    session_id: str
    user_background: str
    message: str


class HandoffStartRequest(BaseModel):
    session_id: str
    selected_issue: int
    user_background: str
    steering_instructions: str | None = None


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
        
    try:
        from ingestion.github_fetcher import parse_github_url
        owner, repo = parse_github_url(request.repo_url)
        repo_id = f"{owner}/{repo}"
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Check if a recent complete ingestion already exists (cache hit)
    import config
    db = next(get_db())
    try:
        existing = db.query(RepoIngestion).filter_by(owner=owner, repo=repo).first()
        if existing and existing.status == "complete":
            age = datetime.now(timezone.utc) - (existing.ingested_at.replace(tzinfo=timezone.utc) if existing.ingested_at.tzinfo is None else existing.ingested_at)
            if age < timedelta(days=config.INGESTION_REFRESH_DAYS):
                logger.info(f"Ingestion cache hit for {repo_id} (age: {age}). Skipping re-fetch.")
                # Ensure progress shows 100% for the frontend polling
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
            return {"status": "not_found", "ingested_at": None, "progress_pct": 0, "status_message": None}
            
        latency_data = None
        if ingestion.latency_info:
            try:
                latency_data = json.loads(ingestion.latency_info)
            except Exception:
                pass
                
        return {
            "status": ingestion.status,
            "ingested_at": ingestion.ingested_at,
            "progress_pct": ingestion.progress_pct,
            "status_message": ingestion.status_message,
            "issue_count": ingestion.issue_count,
            "pr_count": ingestion.pr_count,
            "latency_info": latency_data
        }
    finally:
        db.close()


@app.post("/repos/{owner}/{repo}/onboard")
def onboard_developer(owner: str, repo: str, request: OnboardRequest):
    repo_id = f"{owner}/{repo}"
    bg_hash = hashlib.sha256(request.user_background.encode("utf-8")).hexdigest()
    
    db = next(get_db())
    try:
        cached_guide = db.query(OnboardingGuide).filter_by(
            repo_id=repo_id,
            background_hash=bg_hash
        ).first()
        
        if cached_guide:
            time_limit = datetime.now(timezone.utc) - timedelta(hours=24)
            created_at_naive = cached_guide.created_at.replace(tzinfo=None) if cached_guide.created_at.tzinfo is not None else cached_guide.created_at
            time_limit_naive = time_limit.replace(tzinfo=None)
            
            if created_at_naive > time_limit_naive:
                logger.info(f"Returning cached onboarding guide for {repo_id}...")
                from agent.onboarding_workflow import OnboardingState, hybrid_search_issues
                state = {
                    "repo_id": repo_id,
                    "user_background": request.user_background,
                    "dna_summary": "",
                    "background_hash": bg_hash,
                    "search_queries": [request.user_background],
                    "retrieved_issues": [],
                    "guide": cached_guide.guide,
                    "error": None
                }
                state = hybrid_search_issues(state)
                
                cached_latency = None
                if cached_guide.latency_info:
                    try:
                        cached_latency = json.loads(cached_guide.latency_info)
                    except Exception:
                        pass
                        
                return {
                    "guide": cached_guide.guide,
                    "issues": state["retrieved_issues"],
                    "trace": {
                        "queries": state["search_queries"],
                        "cached": True,
                        "latency_info": cached_latency
                    }
                }
    finally:
        db.close()
            
    logger.info(f"Cache miss for {repo_id}. Running onboarding workflow...")
    workflow_result = run_onboarding_workflow(repo_id, request.user_background)
    
    if workflow_result.get("error"):
        raise HTTPException(status_code=400, detail=workflow_result["error"])
        
    db = next(get_db())
    try:
        stale_guide = db.query(OnboardingGuide).filter_by(repo_id=repo_id, background_hash=bg_hash).first()
        if stale_guide:
            stale_guide.guide = workflow_result["guide"]
            stale_guide.created_at = datetime.now(timezone.utc)
            stale_guide.latency_info = json.dumps(workflow_result.get("latency_info", {}))
        else:
            new_guide = OnboardingGuide(
                repo_id=repo_id,
                background_hash=bg_hash,
                guide=workflow_result["guide"],
                latency_info=json.dumps(workflow_result.get("latency_info", {}))
            )
            db.add(new_guide)
        db.commit()
    finally:
        db.close()
    
    return {
        "guide": workflow_result["guide"],
        "issues": workflow_result["retrieved_issues"],
        "trace": {
            "queries": workflow_result["search_queries"],
            "cached": False,
            "latency_info": workflow_result.get("latency_info", {})
        }
    }


@app.post("/repos/{owner}/{repo}/feedback")
def submit_onboarding_feedback(owner: str, repo: str, request: FeedbackRequest):
    repo_id = f"{owner}/{repo}"
    db = next(get_db())
    try:
        feedback = UserFeedback(
            repo_id=repo_id,
            background_hash=request.background_hash,
            rating=request.rating,
            session_id=request.session_id
        )
        db.add(feedback)
        db.commit()
    finally:
        db.close()
    return {"saved": True}


@app.get("/repos/{owner}/{repo}/chat/history")
def get_chat_history(owner: str, repo: str, session_id: str):
    db = next(get_db())
    try:
        messages = db.query(ChatMessage).filter_by(session_id=session_id).order_by(ChatMessage.created_at.asc()).all()
        return [{"role": m.role, "content": m.content, "created_at": m.created_at} for m in messages]
    finally:
        db.close()


@app.post("/repos/{owner}/{repo}/chat")
def chat_with_agent(owner: str, repo: str, request: ChatRequest, background_tasks: BackgroundTasks):
    repo_id = f"{owner}/{repo}"
    
    db = next(get_db())
    try:
        user_msg = ChatMessage(
            session_id=request.session_id,
            role="user",
            content=request.message
        )
        db.add(user_msg)
        db.commit()
        
        db_history = db.query(ChatMessage).filter_by(session_id=request.session_id).order_by(ChatMessage.created_at.asc()).all()
    finally:
        db.close()
        
    # Check rule-based Orchestrator first
    db_orch = next(get_db())
    try:
        from agent.orchestrator import get_orchestrator
        orchestrator = get_orchestrator()
        route_result = orchestrator.route_message(
            session_id=request.session_id,
            repo_id=repo_id,
            message=request.message,
            user_background=request.user_background,
            db=db_orch,
            background_tasks=background_tasks
        )
    finally:
        db_orch.close()

    if route_result is not None:
        def orchestrator_event_generator():
            if route_result["type"] == "handoff_triggered":
                yield f"data: {json.dumps(route_result)}\n\n"
            elif route_result["type"] == "chat_response":
                msg_content = route_result["message"]
                # Stream the message back as tokens
                for i in range(0, len(msg_content), 6):
                    yield f"data: {json.dumps({'type': 'token', 'content': msg_content[i:i+6]})}\n\n"
                yield f"data: {json.dumps({'type': 'final_answer', 'content': msg_content})}\n\n"
                
                # Save assistant response to DB
                db_save = next(get_db())
                try:
                    assistant_msg = ChatMessage(
                        session_id=request.session_id,
                        role="assistant",
                        content=msg_content
                    )
                    db_save.add(assistant_msg)
                    db_save.commit()
                finally:
                    db_save.close()
        return StreamingResponse(orchestrator_event_generator(), media_type="text/event-stream")

    # Regular onboarding agent workflow
    langchain_messages = []
    for msg in db_history:
        if msg.role == "user":
            langchain_messages.append(HumanMessage(content=msg.content))
        else:
            langchain_messages.append(AIMessage(content=msg.content))
            
    import json
    
    def sse_event_generator():
        try:
            agent = get_onboarding_agent()
            stream = agent.invoke_stream({
                "messages": langchain_messages,
                "repo_id": repo_id,
                "user_background": request.user_background
            })
            
            final_answer = ""
            for event in stream:
                if event["type"] == "final_state":
                    continue
                if event["type"] == "session_summary":
                    logger.info(f"Session summary for {repo_id}: selected_issue={event['payload'].get('selected_issue')}, files_explored={len(event['payload'].get('files_explored', []))}")
                    
                    # Persist the onboarding session state to db
                    db_state = next(get_db())
                    try:
                        payload = event["payload"]
                        state = db_state.query(OnboardingSessionState).filter_by(session_id=request.session_id).first()
                        if not state:
                            state = OnboardingSessionState(session_id=request.session_id)
                            db_state.add(state)
                        state.repo_id = repo_id
                        state.user_background = request.user_background
                        state.dna_summary = payload.get("dna_summary")
                        state.selected_issue = payload.get("selected_issue")
                        state.files_explored = json.dumps(payload.get("files_explored", []))
                        state.issues_mentioned = json.dumps(payload.get("issues_mentioned", []))
                        db_state.commit()
                    except Exception as err:
                        logger.error(f"Failed to save OnboardingSessionState: {err}")
                    finally:
                        db_state.close()
                    continue
                
                if event["type"] == "final_answer":
                    final_answer = event["content"]
                elif event["type"] == "token":
                    final_answer += event["content"]
                
                yield f"data: {json.dumps(event)}\n\n"
                
            if final_answer:
                db_save = next(get_db())
                try:
                    assistant_msg = ChatMessage(
                        session_id=request.session_id,
                        role="assistant",
                        content=final_answer
                    )
                    db_save.add(assistant_msg)
                    db_save.commit()
                finally:
                    db_save.close()
                    
        except Exception as e:
            logger.exception(f"Chat agent streaming failed for {repo_id}: {e}")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
            
    return StreamingResponse(sse_event_generator(), media_type="text/event-stream")


@app.post("/repos/{owner}/{repo}/handoff")
def start_handoff(owner: str, repo: str, request: HandoffStartRequest, background_tasks: BackgroundTasks):
    repo_id = f"{owner}/{repo}"
    db = next(get_db())
    try:
        from agent.orchestrator import get_orchestrator
        orchestrator = get_orchestrator()
        orchestrator.trigger_handoff(
            session_id=request.session_id,
            repo_id=repo_id,
            selected_issue=request.selected_issue,
            user_background=request.user_background,
            db=db,
            background_tasks=background_tasks,
            steering_instructions=request.steering_instructions
        )
        return {"status": "started", "session_id": request.session_id}
    except Exception as e:
        logger.exception(f"Handoff trigger failed for {repo_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@app.get("/repos/{owner}/{repo}/handoff/status")
def get_handoff_status(owner: str, repo: str, session_id: str):
    repo_id = f"{owner}/{repo}"
    db = next(get_db())
    try:
        handoff = db.query(HandoffSession).filter_by(session_id=session_id).first()
        if not handoff:
            return {"status": "not_found", "progress_pct": 0, "logs": "", "patch_diff": None}
        return {
            "status": handoff.status,
            "progress_pct": handoff.progress_pct,
            "logs": handoff.logs,
            "patch_diff": handoff.patch_diff,
            "selected_issue": handoff.selected_issue
        }
    finally:
        db.close()


class FileSaveRequest(BaseModel):
    path: str
    content: str

def build_file_tree(dir_path: Path, root_path: Path) -> list[dict]:
    import os
    items = []
    try:
        for entry in os.scandir(dir_path):
            name = entry.name
            
            # Filter heavy folders
            skip_names = {
                ".git", "node_modules", "venv", ".venv", "__pycache__", 
                ".pytest_cache", ".egg-info", "dist", "build", ".chroma_db",
                ".gemini", ".system_generated", "logs"
            }
            if name in skip_names:
                continue
            if name.startswith("."):
                if name not in (".env", ".env.example", ".gitignore"):
                    continue
                    
            rel_path = os.path.relpath(entry.path, root_path)
            
            if entry.is_dir(follow_symlinks=False):
                children = build_file_tree(Path(entry.path), root_path)
                items.append({
                    "name": name,
                    "path": rel_path,
                    "type": "directory",
                    "children": children
                })
            else:
                items.append({
                    "name": name,
                    "path": rel_path,
                    "type": "file"
                })
    except Exception as e:
        logger.error(f"Error building file tree for {dir_path}: {e}")
        
    items.sort(key=lambda x: (x["type"] != "directory", x["name"].lower()))
    return items


@app.get("/repos/{owner}/{repo}/files/tree")
def get_repo_file_tree(owner: str, repo: str):
    import config
    owner_repo_dir = config.REPOS_CLONE_DIR / owner / repo
    if not owner_repo_dir.exists():
        from ingestion.ingestion_pipeline import clone_repository_locally
        clone_repository_locally(owner, repo)
        
    if not owner_repo_dir.exists():
        raise HTTPException(status_code=404, detail="Repository clone directory not found.")
    
    tree = build_file_tree(owner_repo_dir, owner_repo_dir)
    return tree


@app.get("/repos/{owner}/{repo}/files/content")
def get_repo_file_content(owner: str, repo: str, path: str):
    import config
    owner_repo_dir = (config.REPOS_CLONE_DIR / owner / repo).resolve()
    if not owner_repo_dir.exists():
        raise HTTPException(status_code=404, detail="Repository clone directory not found.")
        
    target_path = (owner_repo_dir / path.strip("/")).resolve()
    if not target_path.is_relative_to(owner_repo_dir):
        raise HTTPException(status_code=400, detail="Path traversal attempt blocked.")
        
    if not target_path.exists():
        raise HTTPException(status_code=404, detail=f"File '{path}' not found.")
        
    if target_path.is_dir():
        raise HTTPException(status_code=400, detail=f"'{path}' is a directory.")
        
    try:
        with open(target_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return {"path": path, "content": content}
    except Exception as e:
        logger.error(f"Error reading file {path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to read file: {str(e)}")


@app.post("/repos/{owner}/{repo}/files/content")
def save_repo_file_content(owner: str, repo: str, request: FileSaveRequest):
    import config
    owner_repo_dir = (config.REPOS_CLONE_DIR / owner / repo).resolve()
    if not owner_repo_dir.exists():
        raise HTTPException(status_code=404, detail="Repository clone directory not found.")
        
    target_path = (owner_repo_dir / request.path.strip("/")).resolve()
    if not target_path.is_relative_to(owner_repo_dir):
        raise HTTPException(status_code=400, detail="Path traversal attempt blocked.")
        
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(request.content)
        return {"saved": True, "path": request.path}
    except Exception as e:
        logger.error(f"Error saving file {request.path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")


class SandboxRunRequest(BaseModel):
    session_id: str
    command: str

def execute_sandbox_run_task(repo_id: str, session_id: str, command: str):
    from utils.sandbox import run_sandbox_command
    from datetime import datetime, timezone
    
    db = SessionLocal()
    try:
        handoff = db.query(HandoffSession).filter_by(session_id=session_id).first()
        if handoff:
            timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
            handoff.status = "verification"
            handoff.logs = (handoff.logs or "") + f"[{timestamp}] [USER COMMAND] Running command: {command}\n"
            db.commit()
    finally:
        db.close()
        
    exit_code, stdout, stderr = run_sandbox_command(repo_id, command)
    
    db = SessionLocal()
    try:
        handoff = db.query(HandoffSession).filter_by(session_id=session_id).first()
        if handoff:
            timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
            output = stdout or stderr or "(No output)"
            handoff.logs = (handoff.logs or "") + f"[{timestamp}] Command output (exit code {exit_code}):\n{output}\n"
            handoff.status = "completed" if exit_code == 0 else "failed"
            db.commit()
    finally:
        db.close()

@app.post("/repos/{owner}/{repo}/sandbox/run")
def run_sandbox_cmd_endpoint(owner: str, repo: str, request: SandboxRunRequest, background_tasks: BackgroundTasks):
    repo_id = f"{owner}/{repo}"
    
    # Initialize handoff session if not exists
    db = next(get_db())
    try:
        handoff = db.query(HandoffSession).filter_by(session_id=request.session_id).first()
        if not handoff:
            handoff = HandoffSession(
                session_id=request.session_id,
                repo_id=repo_id,
                selected_issue=0,
                user_background="User sandbox test run",
                status="pending",
                logs=""
            )
            db.add(handoff)
            db.commit()
    finally:
        db.close()
        
    background_tasks.add_task(execute_sandbox_run_task, repo_id, request.session_id, request.command)
    return {"status": "started"}
