import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Force a dummy key: tests must never touch a real provider, even when the
# developer's shell has a live OPENAI_API_KEY exported.
os.environ["OPENAI_API_KEY"] = "sk-test-key"

# Force a temporary SQLite database for tests so they do not depend on
# any external database configured in the environment.
os.environ["DATABASE_URL"] = f"sqlite:///{Path(tempfile.gettempdir()) / 'taskchain_test.sqlite'}"

# Create the test database tables up front. Import order matters: `config` reads
# the environment at import time, so this import has to follow the env setup above.
from utils.db import init_db  # noqa: E402

init_db()


@pytest.fixture
def mock_llm(monkeypatch):
    """Replace the LLM client `api.server` builds, so tests stay offline.

    The Q&A pipeline constructs its own client internally, so patching the class
    reference is the only seam that keeps `/ask` hermetic.
    """
    import api.server as server

    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="Stubbed answer."))]
    )
    monkeypatch.setattr(server, "OpenAI", lambda *args, **kwargs: client)
    return client
