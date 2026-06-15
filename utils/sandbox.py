import os
import subprocess
import logging
import config

logger = logging.getLogger(__name__)

def is_docker_available() -> bool:
    """Check if the Docker daemon is running and accessible."""
    try:
        res = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        return res.returncode == 0
    except Exception:
        return False

def run_sandbox_command(repo_id: str, command: str, timeout: int = 120) -> tuple[int, str, str]:
    """Runs a command either in a Docker sandbox container (if available)
    or falls back to local subprocess execution inside the cloned repository.
    
    Returns:
        (exit_code, stdout, stderr)
    """
    try:
        owner, repo = repo_id.split("/")
    except ValueError:
        return -1, "", "Error: Invalid repo_id format. Must be 'owner/repo'."
        
    clone_path = config.REPOS_CLONE_DIR / owner / repo
    if not clone_path.exists():
        return -1, "", f"Error: Repository clone directory not found at {clone_path}"

    if is_docker_available():
        logger.info(f"Running sandbox command in Docker for {repo_id}: {command}")
        docker_cmd = [
            "docker", "run", "--rm",
            "-v", f"{clone_path.resolve()}:/workspace",
            "-w", "/workspace",
            config.DOCKER_SANDBOX_IMAGE,
            "sh", "-c", command
        ]
        try:
            res = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=timeout)
            return res.returncode, res.stdout, res.stderr
        except subprocess.TimeoutExpired:
            return -2, "", "Error: Sandbox execution timed out."
        except Exception as e:
            logger.error(f"Docker sandbox execution failed: {e}")
            return -3, "", f"Error executing sandbox command: {str(e)}"
    else:
        logger.warning(f"Docker is not available. Falling back to local execution for {repo_id}: {command}")
        try:
            res = subprocess.run(
                command,
                shell=True,
                cwd=str(clone_path.resolve()),
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return res.returncode, res.stdout, res.stderr
        except subprocess.TimeoutExpired:
            return -2, "", "Error: Local fallback execution timed out."
        except Exception as e:
            logger.error(f"Local fallback execution failed: {e}")
            return -3, "", f"Error executing fallback command: {str(e)}"
