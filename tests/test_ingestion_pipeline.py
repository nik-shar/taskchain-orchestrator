"""Regression tests for the repository DNA summary.

The bug these cover: a repository with **no description** returns `"description": null`
from the GitHub API. `.get(key, default)` only falls back when the key is *absent*, so the
description stayed `None`, became element 3 of the summary lines, and `"\\n".join(lines)`
raised:

    TypeError: sequence item 3: expected str instance, NoneType found

Ingestion failed at 75% — after all the expensive fetching had already succeeded.
"""
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ingestion.github_indexer import RepoSnapshot
from ingestion.ingestion_pipeline import generate_repo_dna_summary


def _snapshot(description=None, file_tree=None, tech=None):
    return RepoSnapshot(
        owner="nik-shar",
        repo="IoT-sensor-collector",
        fetched_at=datetime.now(UTC),
        metadata={"description": description, "language": None, "stars": 0, "topics": []},
        readme="",
        contributing=None,
        file_tree=(
            file_tree
            if file_tree is not None
            else ["README.md", "src", "tests", ".gitignore"]
        ),
        tech_stack=(
            tech
            if tech is not None
            else {"language": "Python", "frameworks": [], "build_tools": [], "config_files": []}
        ),
        issues=[],
        pull_requests=[],
    )


def test_missing_description_does_not_break_the_summary():
    """The exact reported failure: description is None."""
    summary = generate_repo_dna_summary(_snapshot(description=None))
    assert "No description available." in summary


def test_empty_description_falls_back_too():
    assert "No description available." in generate_repo_dna_summary(_snapshot(description=""))


def test_file_tree_none_entries_are_blocked_at_the_model_boundary():
    """`RepoSnapshot.file_tree` is a typed `list[str]`, so pydantic rejects None entries
    before the summary ever sees them.

    Only the untyped `metadata` and `tech_stack` dicts can leak a None -- which is exactly
    how this bug reached production. The `str()` coercion in the summary is belt-and-braces.
    """
    with pytest.raises(ValidationError):
        _snapshot(description="x", file_tree=["a", None, "c"])


def test_empty_file_tree_reports_none():
    summary = generate_repo_dna_summary(_snapshot(description="x", file_tree=[]))
    assert "Top-level files: none" in summary


def test_summary_includes_description_and_tech_stack():
    summary = generate_repo_dna_summary(
        _snapshot(
            description="Collects IoT sensor data",
            tech={
                "language": "Python",
                "frameworks": ["fastapi"],
                "build_tools": ["Docker"],
                "config_files": [],
            },
        )
    )
    assert "Collects IoT sensor data" in summary
    assert "fastapi" in summary
    assert "Docker" in summary


def test_null_language_and_null_stack_entries_are_handled():
    summary = generate_repo_dna_summary(
        _snapshot(
            description=None,
            tech={
                "language": None,
                "frameworks": [None],
                "build_tools": [None],
                "config_files": [],
            },
        )
    )
    assert "Primary language: unknown" in summary
    # str(None) is "None", so these must render rather than raise.
    assert "None" in summary
