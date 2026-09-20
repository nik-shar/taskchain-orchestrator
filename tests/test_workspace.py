"""Tests for the Tier 2 workspace helper (no network — pure path logic)."""
from ingestion.workspace import _is_text_file, workspace_path


def test_is_text_file():
    assert _is_text_file("src/main.py") is True
    assert _is_text_file("config/settings.yaml") is True
    assert _is_text_file("Dockerfile") is True
    assert _is_text_file("README.md") is True
    assert _is_text_file("model.bin") is False
    assert _is_text_file("assets/logo.png") is False


def test_workspace_path_layout():
    ws = workspace_path("owner", "repo")
    assert str(ws).endswith("workspaces/owner/repo")
