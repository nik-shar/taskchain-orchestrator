import pytest
from unittest.mock import patch, MagicMock
import subprocess
from utils.sandbox import is_docker_available, run_sandbox_command

def test_is_docker_available_success():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert is_docker_available() is True
        mock_run.assert_called_once_with(["docker", "info"], capture_output=True, timeout=5)

def test_is_docker_available_failed():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        assert is_docker_available() is False

def test_is_docker_available_exception():
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = FileNotFoundError()
        assert is_docker_available() is False

def test_run_sandbox_command_missing_clone():
    with patch("config.REPOS_CLONE_DIR") as mock_dir:
        # Mock Path.exists to return False
        mock_path = MagicMock()
        mock_path.exists.return_value = False
        mock_dir.__truediv__.return_value.__truediv__.return_value = mock_path
        
        exit_code, stdout, stderr = run_sandbox_command("owner/repo", "echo 'hello'")
        assert exit_code == -1
        assert "Repository clone directory not found" in stderr

def test_run_sandbox_command_docker_success():
    with patch("utils.sandbox.is_docker_available") as mock_docker_check, \
         patch("subprocess.run") as mock_run, \
         patch("config.REPOS_CLONE_DIR") as mock_dir:
         
        mock_docker_check.return_value = True
        
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.resolve.return_value = "/absolute/clone/path"
        mock_dir.__truediv__.return_value.__truediv__.return_value = mock_path
        
        mock_run.return_value = MagicMock(returncode=0, stdout="test stdout", stderr="test stderr")
        
        exit_code, stdout, stderr = run_sandbox_command("owner/repo", "echo 'hello'")
        assert exit_code == 0
        assert stdout == "test stdout"
        assert stderr == "test stderr"
        assert mock_run.called

def test_run_sandbox_command_docker_timeout():
    with patch("utils.sandbox.is_docker_available") as mock_docker_check, \
         patch("subprocess.run") as mock_run, \
         patch("config.REPOS_CLONE_DIR") as mock_dir:
         
        mock_docker_check.return_value = True
        
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_dir.__truediv__.return_value.__truediv__.return_value = mock_path
        
        mock_run.side_effect = subprocess.TimeoutExpired(["docker", "run"], timeout=10)
        
        exit_code, stdout, stderr = run_sandbox_command("owner/repo", "echo 'hello'")
        assert exit_code == -2
        assert "Timed out" in stderr or "timed out" in stderr.lower()

def test_run_sandbox_command_fallback_success():
    with patch("utils.sandbox.is_docker_available") as mock_docker_check, \
         patch("subprocess.run") as mock_run, \
         patch("config.REPOS_CLONE_DIR") as mock_dir:
         
        mock_docker_check.return_value = False
        
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.resolve.return_value = "/absolute/clone/path"
        mock_dir.__truediv__.return_value.__truediv__.return_value = mock_path
        
        mock_run.return_value = MagicMock(returncode=0, stdout="fallback stdout", stderr="fallback stderr")
        
        exit_code, stdout, stderr = run_sandbox_command("owner/repo", "pytest tests/")
        assert exit_code == 0
        assert stdout == "fallback stdout"
        assert stderr == "fallback stderr"
        # Verify it passed the cwd to run locally
        mock_run.assert_called_once_with(
            "pytest tests/",
            shell=True,
            cwd="/absolute/clone/path",
            capture_output=True,
            text=True,
            timeout=120
        )
