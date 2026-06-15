import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from pathlib import Path
import tempfile
import shutil

from api.server import app

client = TestClient(app)

@pytest.fixture
def temp_workspace():
    # Setup temporary directory representing local cloned repo
    temp_dir = tempfile.mkdtemp()
    
    # We want owner/repo subdirectories
    owner_dir = Path(temp_dir) / "owner"
    repo_dir = owner_dir / "repo"
    repo_dir.mkdir(parents=True)
    
    src_dir = repo_dir / "src"
    src_dir.mkdir()
    
    with open(src_dir / "core.py", "w") as f:
        f.write("def core_func():\n    return 42\n")
        
    with open(repo_dir / "README.md", "w") as f:
        f.write("# Test Repo\n")
        
    # Create heavy folder that should be ignored
    node_dir = repo_dir / "node_modules"
    node_dir.mkdir()
    with open(node_dir / "index.js", "w") as f:
        f.write("console.log('heavy');\n")
        
    yield Path(temp_dir) # this is the REPOS_CLONE_DIR
    shutil.rmtree(temp_dir)

def test_file_tree_api(temp_workspace):
    with patch("config.REPOS_CLONE_DIR", temp_workspace):
        response = client.get("/repos/owner/repo/files/tree")
        assert response.status_code == 200
        tree = response.json()
        
        # Verify node_modules is ignored
        names = [node["name"] for node in tree]
        assert "node_modules" not in names
        assert "README.md" in names
        assert "src" in names
        
        # Verify nested directory children
        src_node = next(n for n in tree if n["name"] == "src")
        assert src_node["type"] == "directory"
        assert len(src_node["children"]) == 1
        assert src_node["children"][0]["name"] == "core.py"
        assert src_node["children"][0]["type"] == "file"

def test_file_content_read_api(temp_workspace):
    with patch("config.REPOS_CLONE_DIR", temp_workspace):
        # Read standard file
        response = client.get("/repos/owner/repo/files/content", params={"path": "src/core.py"})
        assert response.status_code == 200
        assert response.json()["path"] == "src/core.py"
        assert "def core_func():" in response.json()["content"]

def test_file_content_write_api(temp_workspace):
    with patch("config.REPOS_CLONE_DIR", temp_workspace):
        # Edit existing file
        payload = {
            "path": "src/core.py",
            "content": "def core_func():\n    return 99\n"
        }
        response = client.post("/repos/owner/repo/files/content", json=payload)
        assert response.status_code == 200
        assert response.json()["saved"] is True
        
        # Verify changes on disk
        with open(temp_workspace / "owner" / "repo" / "src" / "core.py", "r") as f:
            content = f.read()
        assert "return 99" in content

def test_file_apis_traversal_blocked(temp_workspace):
    with patch("config.REPOS_CLONE_DIR", temp_workspace):
        # Read request with path traversal
        response = client.get("/repos/owner/repo/files/content", params={"path": "../secret.txt"})
        assert response.status_code == 400
        assert "Path traversal attempt blocked" in response.json()["detail"]
        
        # Write request with path traversal
        payload = {
            "path": "../hacked.py",
            "content": "print('malicious')"
        }
        response = client.post("/repos/owner/repo/files/content", json=payload)
        assert response.status_code == 400
        assert "Path traversal attempt blocked" in response.json()["detail"]
