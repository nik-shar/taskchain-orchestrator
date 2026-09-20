import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Provide a dummy OpenAI key so tests can instantiate the client without
# making real network requests (all LLM calls are mocked).
os.environ.setdefault("OPENAI_API_KEY", "sk-test-key")

# Force a temporary SQLite database for tests so they do not depend on
# any external database configured in the environment.
os.environ["DATABASE_URL"] = f"sqlite:///{Path(tempfile.gettempdir()) / 'taskchain_test.sqlite'}"

# Create the test database tables up front.
from utils.db import init_db

init_db()
