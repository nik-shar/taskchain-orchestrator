"""Sandboxed execution for agent-authored commands.

The verifier runs the repository's own test/linter command to decide whether a patch
is acceptable. That command is produced by an LLM (or by configuration), so it is
untrusted: it must never execute on the host. Every command runs in a throwaway
container with the worktree bind-mounted, no network, a non-root user, resource caps
and a wall-clock timeout.

The sandbox **fails closed**: when Docker is unavailable the command is refused rather
than silently executed on the host. `SANDBOX_ALLOW_HOST_FALLBACK=1` restores the old
local-execution behaviour for development only.
"""
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import config

logger = logging.getLogger(__name__)

# `docker info` should answer immediately; a hung daemon must not hang ingestion.
DOCKER_PROBE_TIMEOUT_S = 5


@dataclass(frozen=True)
class SandboxResult:
    """Outcome of one sandboxed command."""

    command: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    skipped_reason: str | None = None

    @property
    def ran(self) -> bool:
        """True when the command actually executed (not skipped/refused)."""
        return self.skipped_reason is None

    @property
    def passed(self) -> bool:
        """True only when the command ran and exited zero. Skipped != passed."""
        return self.ran and not self.timed_out and self.exit_code == 0

    def summary(self, max_chars: int = 400) -> str:
        """One-line, human-readable outcome for run summaries."""
        if not self.ran:
            return f"not run ({self.skipped_reason})"
        status = "passed" if self.passed else ("timed out" if self.timed_out else "failed")
        detail = (self.stderr or self.stdout or "").strip().replace("\n", " ")
        if len(detail) > max_chars:
            detail = detail[:max_chars] + "…"
        suffix = f": {detail}" if detail else ""
        return f"{status} (exit {self.exit_code}){suffix}"


def is_docker_available() -> bool:
    """True when the Docker CLI exists and the daemon answers."""
    if shutil.which("docker") is None:
        return False
    try:
        probe = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=DOCKER_PROBE_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0


def build_sandbox_command(
    worktree: Path | str,
    command: str,
    image: str | None = None,
    allow_network: bool | None = None,
) -> list[str]:
    """Build the `docker run` argv for executing `command` in the sandbox.

    Kept separate from execution so the isolation flags are unit-testable without a
    Docker daemon.
    """
    network_allowed = config.SANDBOX_ALLOW_NETWORK if allow_network is None else allow_network
    argv = [
        "docker",
        "run",
        "--rm",
        "--network",
        "bridge" if network_allowed else "none",
        "--user",
        config.SANDBOX_USER,
        "--memory",
        config.SANDBOX_MEMORY,
        "--cpus",
        config.SANDBOX_CPUS,
        "--pids-limit",
        str(config.SANDBOX_PIDS_LIMIT),
        # The image filesystem stays read-only; only the worktree and /tmp are writable.
        "--read-only",
        "--tmpfs",
        "/tmp:rw,size=256m",
        "-e",
        "HOME=/tmp",
        "-v",
        f"{Path(worktree).resolve()}:/workspace",
        "-w",
        "/workspace",
        image or config.DOCKER_SANDBOX_IMAGE,
        "sh",
        "-lc",
        command,
    ]
    return argv


def run_sandbox_command(
    worktree: Path | str,
    command: str,
    timeout: int | None = None,
    image: str | None = None,
    allow_network: bool | None = None,
) -> SandboxResult:
    """Run `command` in the sandbox against `worktree`. Never raises on failure."""
    worktree_path = Path(worktree)
    if not worktree_path.is_dir():
        return SandboxResult(
            command=command,
            exit_code=-1,
            skipped_reason=f"worktree not found: {worktree_path}",
        )

    if not command.strip():
        return SandboxResult(command=command, exit_code=-1, skipped_reason="empty command")

    if not is_docker_available():
        if not config.SANDBOX_ALLOW_HOST_FALLBACK:
            logger.error(
                "Docker unavailable; refusing to run %r. Start a Docker daemon, or set "
                "SANDBOX_ALLOW_HOST_FALLBACK=1 to run on the host (development only).",
                command,
            )
            return SandboxResult(
                command=command,
                exit_code=-1,
                skipped_reason="docker unavailable (host fallback disabled)",
            )
        logger.warning("Docker unavailable; running %r on the host (UNSANDBOXED).", command)
        return _run_on_host(worktree_path, command, timeout)

    argv = build_sandbox_command(worktree_path, command, image, allow_network)
    limit = timeout if timeout is not None else config.SANDBOX_TIMEOUT_S
    logger.info("Sandboxed run in %s: %s", worktree_path, command)
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=limit)
    except subprocess.TimeoutExpired:
        logger.warning("Sandboxed command timed out after %ss: %s", limit, command)
        return SandboxResult(command=command, exit_code=-2, timed_out=True)
    except OSError as exc:
        logger.error("Failed to start sandboxed command: %s", exc)
        return SandboxResult(command=command, exit_code=-3, stderr=str(exc))

    return SandboxResult(
        command=command,
        exit_code=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


def _run_on_host(worktree: Path, command: str, timeout: int | None) -> SandboxResult:
    """Unsandboxed fallback. Only reachable behind SANDBOX_ALLOW_HOST_FALLBACK."""
    limit = timeout if timeout is not None else config.SANDBOX_TIMEOUT_S
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=str(worktree),
            capture_output=True,
            text=True,
            timeout=limit,
        )
    except subprocess.TimeoutExpired:
        return SandboxResult(command=command, exit_code=-2, timed_out=True)
    except OSError as exc:
        return SandboxResult(command=command, exit_code=-3, stderr=str(exc))
    return SandboxResult(
        command=command,
        exit_code=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


def detect_test_command(worktree: Path | str) -> str | None:
    """Best-effort test command for a repository, or None when none is obvious.

    Only inspects well-known manifests. `SANDBOX_TEST_COMMAND` takes precedence, which
    is the lever the API layer should expose.
    """
    if config.SANDBOX_TEST_COMMAND:
        return config.SANDBOX_TEST_COMMAND

    root = Path(worktree)
    if (root / "pyproject.toml").exists() or (root / "pytest.ini").exists():
        return "python -m pytest -q"
    if (root / "tests").is_dir():
        return "python -m pytest -q"
    if (root / "package.json").exists():
        return "npm test --silent"
    if (root / "go.mod").exists():
        return "go test ./..."
    if (root / "Makefile").exists():
        return "make test"
    return None


def build_repo_image(
    repo_dir: Path | str, tag: str, base_image: str | None = None
) -> SandboxResult:
    """Build an image with the repo's dependencies installed.

    `run_sandbox_command` executes with `--network none`, so dependencies have to be
    baked in at build time, where network is available. Failures are reported, not raised.
    """
    repo_path = Path(repo_dir)
    if not repo_path.is_dir():
        return SandboxResult(
            command=f"docker build -t {tag}",
            exit_code=-1,
            skipped_reason=f"repo dir not found: {repo_path}",
        )
    if not (repo_path / "requirements.txt").exists():
        return SandboxResult(
            command=f"docker build -t {tag}",
            exit_code=-1,
            skipped_reason="no requirements.txt to install",
        )

    base = base_image or config.DOCKER_SANDBOX_IMAGE
    if not is_docker_available():
        return SandboxResult(
            command=f"docker build -t {tag}",
            exit_code=-1,
            skipped_reason="docker unavailable",
        )

    with tempfile.TemporaryDirectory() as tmp:
        dockerfile_path = Path(tmp) / "Dockerfile.sandbox"
        dockerfile_path.write_text(
            f"FROM {base}\n"
            "WORKDIR /workspace\n"
            "COPY requirements.txt /tmp/requirements.txt\n"
            "RUN pip install --no-cache-dir -r /tmp/requirements.txt\n"
        )
        argv = ["docker", "build", "-f", str(dockerfile_path), "-t", tag, str(repo_path)]
        try:
            completed = subprocess.run(argv, capture_output=True, text=True, timeout=900)
        except subprocess.TimeoutExpired:
            return SandboxResult(command=" ".join(argv), exit_code=-2, timed_out=True)
        except OSError as exc:
            return SandboxResult(command=" ".join(argv), exit_code=-3, stderr=str(exc))

    return SandboxResult(
        command=" ".join(argv),
        exit_code=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )

