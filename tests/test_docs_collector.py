"""Tests for Tier 1 docs collection and budgeted injection."""
import config
from ingestion.docs_collector import build_docs_context, collect_docs


def test_collect_and_inject_docs(tmp_path):
    (tmp_path / "README.md").write_text("# My Project\nMain docs." + "x" * 100)
    (tmp_path / "ARCHITECTURE.md").write_text("# Architecture\nLayered design.")
    (tmp_path / "notes.txt").write_text("Random notes.")
    (tmp_path / "app.py").write_text("print('hi')\n")  # not a doc

    repo_id = "docs_test_owner/docs_test_repo"
    count = collect_docs(repo_id, tmp_path)
    assert count == 3

    context = build_docs_context(repo_id)
    assert "# My Project" in context
    assert "# Architecture" in context
    assert "Random notes." in context
    assert "print" not in context

    # README (priority 10) appears before notes.txt (priority 50)
    assert context.index("# My Project") < context.index("Random notes.")


def test_build_docs_context_budget(tmp_path):
    for i in range(5):
        (tmp_path / f"doc_{i}.md").write_text("d" * 2000)
    repo_id = "docs_budget_owner/docs_budget_repo"
    collect_docs(repo_id, tmp_path)

    context = build_docs_context(repo_id, budget_chars=3000)
    assert len(context) < 3600  # at most ~1 full doc + truncation marker
    assert "truncated to fit context budget" in context


def test_build_docs_context_empty(tmp_path):
    assert build_docs_context("nothing/nowhere") == ""


def test_doc_truncation_at_ingestion(tmp_path):
    big = tmp_path / "BIG.md"
    big.write_text("y" * (config.DOC_FILE_MAX_CHARS + 5000))
    repo_id = "docs_trunc_owner/docs_trunc_repo"
    collect_docs(repo_id, tmp_path)
    context = build_docs_context(repo_id, budget_chars=1_000_000)
    assert "truncated at ingestion time" in context
