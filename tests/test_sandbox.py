"""Tests for sandboxed command execution (no Docker daemon required)."""
import subprocess

import pytest

import config
from utils.sandbox import (
    SandboxResult,
    build_repo_image,
    build_sandbox_command,
    detect_test_command,
    is_docker_available,
    run_sandbox_command,
)


@pytest.fixture
def worktree(tmp_path):
    directory = tmp_path / "worktree"
    directory.mkdir()
    return directory


def test_build_command_applies_isolation_flags(worktree):
    argv = build_sandbox_command(worktree, "pytest -q")
    joined = " ".join(argv)

    assert argv[:3] == ["docker", "run", "--rm"]
    assert "--network none" in joined          # no egress for untrusted commands
    assert "--read-only" in argv               # image filesystem is immutable
    assert "--user" in argv
    assert f"--memory {config.SANDBOX_MEMORY}" in joined
    assert f"--cpus {config.SANDBOX_CPUS}" in joined
    assert f"--pids-limit {config.SANDBOX_PIDS_LIMIT}" in joined
    assert f"{worktree.resolve()}:/workspace" in argv
    assert argv[-3:] == ["sh", "-lc", "pytest -q"]


def test_build_command_network_is_opt_in(worktree):
    assert "--network bridge" in " ".join(
        build_sandbox_command(worktree, "pip install -r requirements.txt", allow_network=True)
    )


def test_docker_absent_refuses_to_run_on_host(worktree, monkeypatch):
    """Fail closed: no Docker means no execution, not a host fallback."""
    monkeypatch.setattr(config, "SANDBOX_ALLOW_HOST_FALLBACK", False)
    monkeypatch.setattr("utils.sandbox.is_docker_available", lambda: False)

    result = run_sandbox_command(worktree, "rm -rf /")

    assert result.ran is False
    assert result.passed is False
    assert "docker unavailable" in result.skipped_reason
    assert result.exit_code == -1


def test_host_fallback_is_opt_in(worktree, monkeypatch):
    monkeypatch.setattr(config, "SANDBOX_ALLOW_HOST_FALLBACK", True)
    monkeypatch.setattr("utils.sandbox.is_docker_available", lambda: False)

    result = run_sandbox_command(worktree, "echo hi")

    assert result.ran is True
    assert result.passed is True
    assert "hi" in result.stdout


def test_missing_worktree_is_skipped(tmp_path):
    result = run_sandbox_command(tmp_path / "nope", "echo hi")
    assert result.ran is False
    assert "worktree not found" in result.skipped_reason


def test_empty_command_is_skipped(worktree):
    assert run_sandbox_command(worktree, "   ").ran is False


def test_exit_code_is_propagated(worktree, monkeypatch):
    monkeypatch.setattr("utils.sandbox.is_docker_available", lambda: True)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 1, stdout="", stderr="1 failed"),
    )

    result = run_sandbox_command(worktree, "pytest -q")

    assert result.ran is True
    assert result.passed is False          # non-zero exit must not pass verification
    assert result.exit_code == 1
    assert result.summary().startswith("failed")


def test_timeout_is_reported_not_raised(worktree, monkeypatch):
    monkeypatch.setattr("utils.sandbox.is_docker_available", lambda: True)

    def _timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="docker", timeout=1)

    monkeypatch.setattr(subprocess, "run", _timeout)
    result = run_sandbox_command(worktree, "sleep 999", timeout=1)

    assert result.timed_out is True
    assert result.passed is False
    assert result.exit_code == -2
    assert "timed out" in result.summary()


def test_zero_exit_passes(worktree, monkeypatch):
    monkeypatch.setattr("utils.sandbox.is_docker_available", lambda: True)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, stdout="3 passed", stderr=""),
    )
    assert run_sandbox_command(worktree, "pytest -q").passed is True


def test_detect_test_command_prefers_config(worktree, monkeypatch):
    monkeypatch.setattr(config, "SANDBOX_TEST_COMMAND", "make lint")
    assert detect_test_command(worktree) == "make lint"


def test_detect_test_command_infers_from_manifests(worktree, monkeypatch):
    monkeypatch.setattr(config, "SANDBOX_TEST_COMMAND", None)
    assert detect_test_command(worktree) is None

    (worktree / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    assert detect_test_command(worktree) == "python -m pytest -q"


def test_build_repo_image_skips_without_requirements(worktree):
    result = build_repo_image(worktree, "taskchain-sandbox-test:latest")
    assert result.ran is False
    assert "no requirements.txt" in result.skipped_reason


def test_sandbox_result_summary_is_readable():
    skipped = SandboxResult(command="pytest", exit_code=-1, skipped_reason="docker unavailable")
    assert skipped.summary() == "not run (docker unavailable)"
    long_output = SandboxResult(command="pytest", exit_code=1, stderr="x" * 5000)
    assert len(long_output.summary(max_chars=50)) < 100


@pytest.mark.docker
@pytest.mark.skipif(not is_docker_available(), reason="requires a running Docker daemon")
def test_real_sandbox_run_has_no_network(worktree):
    """Integration: prove the container actually runs and egress is blocked."""
    (worktree / "check.py").write_text(
        "import urllib.request\n"
        "try:\n"
        "    urllib.request.urlopen('http://example.com', timeout=2)\n"
        "    print('NETWORK REACHABLE')\n"
        "except Exception as exc:\n"
        "    print('network blocked:', type(exc).__name__)\n"
    )
    result = run_sandbox_command(worktree, "python check.py", timeout=120)

    assert result.ran is True, result.summary()
    assert "NETWORK REACHABLE" not in result.stdout
