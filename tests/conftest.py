import os
import sys
import tempfile
from pathlib import Path

# Point the app at a throwaway database and a fixed secret BEFORE app.config is
# imported anywhere (its settings are evaluated at import time).
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_TMP_DB_DIR = tempfile.mkdtemp(prefix="pycompiler_tests_")
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["DB_PATH"] = str(Path(_TMP_DB_DIR) / "test.db")
os.environ["WORKSPACE_ROOT"] = str(Path(_TMP_DB_DIR) / "workspaces")
os.environ["CELL_TIMEOUT_SEC"] = "60"

import shutil  # noqa: E402

import pytest  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import get_conn, init_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    init_db()
    with get_conn() as conn:
        conn.execute("DELETE FROM cells")
        conn.execute("DELETE FROM notebooks")
        conn.execute("DELETE FROM users")
    # User ids restart at 1 each test, so stale workspace files would leak across.
    shutil.rmtree(settings.WORKSPACE_ROOT, ignore_errors=True)

    with TestClient(app) as test_client:
        yield test_client


def register(client, email="user@example.com", password="password123"):
    response = client.post("/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    return response
