"""Tests for request routing and the plan/execute/verify loop."""
import pytest

import agent.orchestrator as orchestrator_module
from agent.orchestrator import (
    ROUTE_FIX,
    ROUTE_QUESTION,
    Orchestrator,
    clear_sessions,
    retry_feedback,
    route,
    session_payload,
)


@pytest.fixture(autouse=True)
def _clean_sessions():
    clear_sessions()
    yield
    clear_sessions()


def _execution(files=("src/app.py",), status="applied", errors=None, attempt=1):
    return {
        "status": status,
        "repo_id": "owner/repo",
        "attempt": attempt,
        "files_changed": list(files),
        "diff": "--- a/src/app.py\n+++ b/src/app.py\n",
        "errors": list(errors or []),
        "worktree": "/tmp/worktree",
    }


def _verification(status, test_output="", summary=None):
    return {
        "status": status,
        "test_output": test_output,
        "test_command": "python -m pytest -q",
        "exit_code": 0 if status == "passed" else 1,
        "review": "advisory",
        "concerns": [],
        "summary": summary or f"status {status}",
    }


class FakePlanner:
    def __init__(self, *args, **kwargs):
        self.calls = []

    def plan(self, repo_id, issue_description, context=None):
        FakePlanner.last_context = context
        return {"repo_id": repo_id, "issue": issue_description, "plan": "do the thing"}


class FakeExecutor:
    """Returns a canned execution per attempt and records the feedback it received."""

    attempts: list[dict] = []

    def __init__(self, *args, **kwargs):
        self.feedback_seen = []
        FakeExecutor.attempts = []

    def execute(self, plan, feedback=None, attempt=1):
        FakeExecutor.attempts.append({"attempt": attempt, "feedback": feedback})
        return _execution(attempt=attempt)


class FakeVerifier:
    """Returns a queued series of verification results, continuing across instances.

    `_run_loop` builds a new Verifier per call, so the queue position lives on the class.
    """

    statuses: list[str] = ["passed"]
    calls: int = 0

    def __init__(self, *args, **kwargs):
        pass

    def verify(self, execution_result, issue_description=None, test_command=None):
        index = min(FakeVerifier.calls, len(FakeVerifier.statuses) - 1)
        FakeVerifier.calls += 1
        attempt = execution_result.get("attempt")
        return _verification(
            FakeVerifier.statuses[index], test_output=f"pytest run for attempt {attempt}"
        )


@pytest.fixture
def fakes(monkeypatch, tmp_path):
    monkeypatch.setattr(orchestrator_module, "Planner", FakePlanner)
    monkeypatch.setattr(orchestrator_module, "Executor", FakeExecutor)
    monkeypatch.setattr(orchestrator_module, "Verifier", FakeVerifier)
    monkeypatch.setattr(orchestrator_module, "get_workspace", lambda repo_id: tmp_path)
    FakeVerifier.statuses = ["passed"]
    FakeVerifier.calls = 0
    FakeExecutor.attempts = []
    return orchestrator_module



@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("What does this repo do?", ROUTE_QUESTION),
        ("Where is authentication handled?", ROUTE_QUESTION),
        ("How are routes registered?", ROUTE_QUESTION),
        ("Can you explain the ingestion pipeline?", ROUTE_QUESTION),
        ("Fix the broken auth handler", ROUTE_FIX),
        ("There is a bug in the CLI", ROUTE_FIX),
        ("Implement retry logic for uploads", ROUTE_FIX),
        ("Please resolve issue #42", ROUTE_FIX),
        ("", ROUTE_QUESTION),
    ],
)
def test_route_classifies_messages(message, expected):
    assert route(message) == expected


def test_route_prefers_question_wording_over_fix_verbs():
    # An interrogative opener wins, so this is answered rather than patched.
    assert route("What does the fix for issue #12 change?") == ROUTE_QUESTION


def test_orchestrator_exposes_routing():
    assert Orchestrator().route("there is a crash in main.py") == ROUTE_FIX


def test_run_fix_passes_when_verification_passes(fakes):
    FakeVerifier.statuses = ["passed"]
    session = Orchestrator().run_fix("owner/repo", "fix the thing")

    assert session.status == "passed"
    assert session.attempts == 1
    assert len(session.history) == 1
    assert session_payload(session)["files_changed"] == ["src/app.py"]


def test_run_fix_retries_with_test_output_after_failure(fakes):
    FakeVerifier.statuses = ["failed", "passed"]
    session = Orchestrator().run_fix("owner/repo", "fix the thing", max_attempts=2)

    assert session.status == "passed"
    assert session.attempts == 2
    assert len(session.history) == 2
    assert session.history[0]["verification_status"] == "failed"
    # The retry must carry the failure evidence back to the executor.
    retry_note = FakeExecutor.attempts[1]["feedback"]
    assert "failed verification" in retry_note
    assert "pytest run for attempt 1" in retry_note


def test_run_fix_stops_at_max_attempts(fakes):
    FakeVerifier.statuses = ["failed", "failed", "passed"]
    session = Orchestrator().run_fix("owner/repo", "fix the thing", max_attempts=2)

    assert session.attempts == 2
    assert session.status == "failed"
    assert len(FakeExecutor.attempts) == 2


def test_run_fix_does_not_retry_when_tests_cannot_run(fakes):
    """`not_run` means unverified, not failed: retrying would not help."""
    FakeVerifier.statuses = ["not_run"]
    session = Orchestrator().run_fix("owner/repo", "fix the thing", max_attempts=3)

    assert session.attempts == 1
    assert session.status == "not_run"


def test_refine_reuses_the_session_plan(fakes):
    FakeVerifier.statuses = ["failed", "passed"]
    orchestrator = Orchestrator()
    session = orchestrator.run_fix("owner/repo", "add caching", max_attempts=1)
    assert session.status == "failed"

    refined = orchestrator.refine(session.session_id, "only touch the cache module", max_attempts=1)

    assert refined.session_id == session.session_id
    assert refined.status == "passed"
    assert refined.attempts == 2  # continues the same run rather than restarting
    # Refinement feedback reaches the executor verbatim.
    assert FakeExecutor.attempts[-1]["feedback"] == "only touch the cache module"


def test_refine_unknown_session_raises(fakes):
    with pytest.raises(KeyError):
        Orchestrator().refine("does-not-exist", "change something")


def test_summary_is_plain_english_and_names_evidence(fakes):
    FakeVerifier.statuses = ["failed", "passed"]
    session = Orchestrator().run_fix("owner/repo", "fix the thing", max_attempts=2)
    summary = session_payload(session)["summary"]

    assert "Request: fix the thing" in summary
    assert "Attempts: 2" in summary
    assert "src/app.py" in summary
    assert "status passed" in summary


def test_retry_feedback_includes_errors_and_test_output():
    note = retry_feedback(
        "user said: keep it minimal",
        _verification("failed", test_output="AssertionError: nope"),
        _execution(errors=["edit 1: 'find' text not present"]),
    )
    assert "keep it minimal" in note
    assert "edit 1: 'find' text not present" in note
    assert "AssertionError: nope" in note
