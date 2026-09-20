"""Multi-agent orchestrator: routes requests and drives the fix loop.

Two paths exist for an ingested repository:

* **Q&A (onboarding)** — read-only retrieval over docs, code and issue history.
* **Fixing (coding)** — Planner -> Executor -> Verifier, where verification runs the
  repository's own test suite in the sandbox.

`route()` decides which path a message belongs to; `run_fix()` drives the bounded
verify-and-retry loop, feeding test failures back to the executor; `refine()` re-enters
that loop with user feedback instead of regenerating from scratch.

Sessions live in memory, which is enough to make refinement work within one process but
is *not* durable across restarts or across Cloud Run instances.
"""
import logging
import re
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

import config
from agent.executor import Executor
from agent.planner import Planner
from agent.verifier import Verifier
from ingestion.workspace import get_workspace

logger = logging.getLogger(__name__)

ROUTE_QUESTION = "question"
ROUTE_FIX = "fix"

# Interrogative openers win over fix verbs, so "what does the fix for #12 do?" is a question.
_QUESTION_RE = re.compile(
    r"^\s*(what|where|how|why|who|when|which|does|do|is|are|can|could|should|explain|summar)",
    re.IGNORECASE,
)
_FIX_RE = re.compile(
    r"\b(fix|fixes|fixing|bug|broken|crash|error|regression|implement|patch|refactor|"
    r"resolve|solve|issue\s*#?\d+|pull request)\b",
    re.IGNORECASE,
)


def route(message: str) -> str:
    """Classify a message as a fix request or a question."""
    text = (message or "").strip()
    if not text:
        return ROUTE_QUESTION
    if _QUESTION_RE.search(text):
        return ROUTE_QUESTION
    if _FIX_RE.search(text):
        return ROUTE_FIX
    return ROUTE_QUESTION


@dataclass
class FixSession:
    """State for one plan/execute/verify run, plus any refinements applied to it."""

    session_id: str
    repo_id: str
    issue: str
    plan: dict[str, Any]
    attempts: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)
    last: dict[str, Any] | None = None

    @property
    def verification(self) -> dict[str, Any] | None:
        return self.last["verification"] if self.last else None

    @property
    def execution(self) -> dict[str, Any] | None:
        return self.last["execution"] if self.last else None

    @property
    def status(self) -> str:
        verification = self.verification or {}
        return verification.get("status", "unknown")


_SESSIONS: dict[str, FixSession] = {}
_SESSIONS_LOCK = threading.Lock()


def get_session(session_id: str) -> FixSession | None:
    with _SESSIONS_LOCK:
        return _SESSIONS.get(session_id)


def clear_sessions() -> None:
    """Drop all sessions (used by tests and after a re-ingest)."""
    with _SESSIONS_LOCK:
        _SESSIONS.clear()



def retry_feedback(
    base_feedback: str | None,
    verification: dict[str, Any],
    execution: dict[str, Any],
) -> str:
    """Build the instruction the executor gets after a failed verification."""
    parts: list[str] = []
    if base_feedback:
        parts.append(base_feedback)
    if execution.get("errors"):
        parts.append("The previous attempt had problems: " + "; ".join(execution["errors"][:5]))
    parts.append(
        "The previous attempt failed verification. Test output:\n"
        + (verification.get("test_output") or "no output")[-2000:]
    )
    return "\n\n".join(parts)


def run_summary(session: FixSession) -> str:
    """Plain-English summary of a run: what was attempted, what changed, what proved it."""
    execution = session.execution or {}
    verification = session.verification or {}
    files = execution.get("files_changed") or []
    lines = [
        f"Request: {session.issue}",
        f"Attempts: {session.attempts}",
        f"Files changed: {', '.join(files) if files else 'none'}",
        f"Verification: {verification.get('summary', 'not verified')}",
    ]
    if execution.get("status") == "failed" and execution.get("errors"):
        lines.append("Executor errors: " + "; ".join(execution["errors"][:3]))
    return "\n".join(lines)


class Orchestrator:
    """Routes incoming work and drives the plan/execute/verify loop."""

    def route(self, message: str) -> str:
        """Expose routing as behaviour of the orchestrator object."""
        return route(message)

    def _run_loop(
        self,
        session: FixSession,
        feedback: str | None,
        max_attempts: int,
        test_command: str | None = None,
    ) -> FixSession:
        workspace = get_workspace(session.repo_id)
        executor = Executor(
            repo_id=session.repo_id, workspace=workspace, run_id=session.session_id
        )
        verifier = Verifier(repo_id=session.repo_id)

        note = feedback
        for _ in range(max_attempts):
            attempt = session.attempts + 1
            execution = executor.execute(session.plan, feedback=note, attempt=attempt)
            verification = verifier.verify(
                execution,
                issue_description=session.issue,
                test_command=test_command,
            )
            session.attempts = attempt
            session.last = {"execution": execution, "verification": verification}
            session.history.append(
                {
                    "attempt": attempt,
                    "executor_status": execution.get("status"),
                    "files_changed": execution.get("files_changed", []),
                    "verification_status": verification.get("status"),
                    "test_output": (verification.get("test_output") or "")[-1500:],
                }
            )
            if verification.get("status") != "failed":
                break
            logger.info(
                "Attempt %s for %s failed verification; retrying with feedback",
                attempt,
                session.repo_id,
            )
            note = retry_feedback(feedback, verification, execution)
        return session

    def run_fix(
        self,
        repo_id: str,
        issue_description: str,
        feedback: str | None = None,
        max_attempts: int | None = None,
        test_command: str | None = None,
    ) -> FixSession:
        """Plan a fix, then drive execute/verify until it passes or attempts run out."""
        attempts_allowed = max_attempts or config.MAX_FIX_ATTEMPTS
        logger.info("Fixing %s: %s", repo_id, issue_description[:80])

        try:
            from ingestion.sqlite_indexer import keyword_search

            related = keyword_search(repo_id, issue_description, top_k=config.KEYWORD_TOP_K)
        except Exception as exc:  # noqa: BLE001 - retrieval is best-effort context
            logger.warning("Context retrieval failed for %s (%s)", repo_id, exc)
            related = []

        plan = Planner().plan(
            repo_id=repo_id,
            issue_description=issue_description,
            context={"dna_summary": _repo_dna(repo_id), "related_issues": related},
        )

        session = FixSession(
            session_id=uuid.uuid4().hex[:12],
            repo_id=repo_id,
            issue=issue_description,
            plan=plan,
        )
        with _SESSIONS_LOCK:
            _SESSIONS[session.session_id] = session

        return self._run_loop(session, feedback, attempts_allowed, test_command)

    def refine(
        self,
        session_id: str,
        feedback: str,
        max_attempts: int | None = None,
        test_command: str | None = None,
    ) -> FixSession:
        """Re-run execute/verify for an existing session with user feedback."""
        session = get_session(session_id)
        if session is None:
            raise KeyError(session_id)
        logger.info("Refining session %s: %s", session_id, feedback[:80])
        return self._run_loop(
            session, feedback, max_attempts or config.MAX_FIX_ATTEMPTS, test_command
        )


def _repo_dna(repo_id: str) -> str:
    """Stored repository summary, if the repo was ingested."""
    from utils.db import RepoIngestion, SessionLocal

    owner, _, repo = repo_id.partition("/")
    db = SessionLocal()
    try:
        ingestion = db.query(RepoIngestion).filter_by(owner=owner, repo=repo).first()
        return (ingestion.dna_summary or "") if ingestion else ""
    finally:
        db.close()


def session_payload(session: FixSession) -> dict[str, Any]:
    """Serialisable view of a session for API responses."""
    execution = session.execution or {}
    verification = session.verification or {}
    return {
        "session_id": session.session_id,
        "repo_id": session.repo_id,
        "issue": session.issue,
        "plan": session.plan.get("plan", ""),
        "attempts": session.attempts,
        "status": session.status,
        "files_changed": execution.get("files_changed", []),
        "diff": execution.get("diff", ""),
        "errors": execution.get("errors", []),
        "verification": verification,
        "summary": run_summary(session),
        "history": session.history,
    }

