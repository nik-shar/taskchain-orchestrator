"""Tests for Tier 2 read-only code access tools."""
import pytest

from agent.code_tools import CodeReader, build_code_context


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "server.py").write_text(
        "def handle_auth(token):\n    return verify(token)\n" * 3
    )
    (tmp_path / "src" / "utils.py").write_text("def verify(token):\n    return True\n")
    (tmp_path / "README.md").write_text("# Test Project\nDocs here.\n")
    (tmp_path / "data.bin").write_bytes(b"\x00\x01\x02")
    return tmp_path


def test_list_files_filters_non_text(workspace):
    reader = CodeReader(workspace)
    files = reader.list_files()
    assert "src/server.py" in files
    assert "README.md" in files
    assert "data.bin" not in files


def test_read_file_returns_content(workspace):
    reader = CodeReader(workspace)
    result = reader.read_file("src/utils.py")
    assert result is not None
    assert "def verify" in result["content"]
    assert result["truncated"] is False


def test_read_file_truncates(workspace):
    reader = CodeReader(workspace)
    result = reader.read_file("src/server.py", max_chars=20)
    assert result["truncated"] is True
    assert len(result["content"]) == 20
    assert result["total_chars"] > 20


def test_read_file_blocks_path_escape(workspace):
    reader = CodeReader(workspace)
    assert reader.read_file("../../etc/passwd") is None
    assert reader.read_file("/etc/passwd") is None
    assert reader.read_file("missing.py") is None


def test_build_code_context_budget(workspace, monkeypatch):
    import config
    monkeypatch.setattr(config, "CODE_FILE_MAX_CHARS", 1000)
    big = workspace / "src" / "big.py"
    big.write_text("x = 1\n" * 5000)
    context, read = build_code_context(
        workspace,
        ["src/big.py", "src/utils.py"],
        total_budget=1100,
    )
    assert "src/big.py" in read  # first file fits (capped to ~1000 chars)
    assert "src/utils.py" not in read  # dropped whole rather than sliced
    assert len(context) <= 1400


def test_build_code_context_respects_max_files(workspace):
    context, read = build_code_context(
        workspace,
        ["src/server.py", "src/utils.py", "README.md"],
        total_budget=1_000_000,
    )
    assert len(read) <= 5
    assert "def verify" in context or "# Test Project" in context


def test_code_reader_requires_existing_workspace(tmp_path):
    with pytest.raises(FileNotFoundError):
        CodeReader(tmp_path / "nope")
