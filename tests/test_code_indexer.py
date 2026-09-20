"""Tests for Tier 2 source-file indexing and search."""
import config
from ingestion.code_indexer import count_indexed_files, index_source_files, search_code


def _setup(tmp_path, monkeypatch):
    """Point DATABASE_URL at a scratch DB and build a scratch workspace."""
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{db_dir / 'idx.sqlite'}")

    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "auth.py").write_text(
        "def verify_token(token):\n    return check(token)\n"
    )
    (ws / "src" / "db.py").write_text("def connect():\n    return sqlite3.connect('x')\n")
    (ws / "README.md").write_text("# Project\nDocs here.\n")
    (ws / "logo.png").write_bytes(b"\x89PNG\r\n")
    return ws


def test_index_counts_text_files_only(tmp_path, monkeypatch):
    ws = _setup(tmp_path, monkeypatch)
    indexed = index_source_files("o/r", ws)
    assert indexed == 3  # auth.py, db.py, README.md — logo.png is not text
    assert count_indexed_files("o/r") == 3


def test_count_is_scoped_per_repo(tmp_path, monkeypatch):
    ws = _setup(tmp_path, monkeypatch)
    index_source_files("o/r", ws)
    assert count_indexed_files("other/repo") == 0


def test_search_finds_matching_file(tmp_path, monkeypatch):
    ws = _setup(tmp_path, monkeypatch)
    index_source_files("o/r", ws)

    hits = search_code("o/r", "where is a token verified?")
    assert hits
    assert hits[0]["path"] == "src/auth.py"
    assert "token" in hits[0]["snippet"]


def test_search_survives_question_punctuation(tmp_path, monkeypatch):
    """Bare questions used to break FTS5 MATCH and silently return nothing."""
    ws = _setup(tmp_path, monkeypatch)
    index_source_files("o/r", ws)

    # "DB" survives tokenization and matches the indexed `path` column of src/db.py.
    db_hits = search_code("o/r", "What does this DB do?")
    assert [hit["path"] for hit in db_hits] == ["src/db.py"]

    # FTS5 syntax characters in the question must not raise or match everything.
    assert isinstance(search_code("o/r", 'sqlite3 OR "x" -y:z*'), list)
    assert search_code("o/r", "") == []
    assert search_code("o/r", "a b") == []  # nothing tokenizable


def test_reindex_replaces_previous_rows(tmp_path, monkeypatch):
    ws = _setup(tmp_path, monkeypatch)
    index_source_files("o/r", ws)

    (ws / "src" / "extra.py").write_text("X = 1\n")
    assert index_source_files("o/r", ws) == 4
    assert count_indexed_files("o/r") == 4


def test_max_files_limit_is_respected(tmp_path, monkeypatch):
    ws = _setup(tmp_path, monkeypatch)
    assert index_source_files("o/r", ws, max_files=2) == 2
    assert count_indexed_files("o/r") == 2


def test_missing_workspace_is_not_an_error(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert index_source_files("o/r", tmp_path / "nope") == 0


def test_non_sqlite_backend_degrades_gracefully(tmp_path, monkeypatch):
    ws = _setup(tmp_path, monkeypatch)
    # Non-SQLite backends have no FTS5: every entry point must degrade, not raise.
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql://user:pw@localhost/db")
    assert index_source_files("o/r", ws) == 0
    assert count_indexed_files("o/r") == 0
    assert search_code("o/r", "token") == []
