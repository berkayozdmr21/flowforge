import os, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).absolute().parents[2]
sys.path.insert(0, str(ROOT))
(ROOT / ".tmp").mkdir(exist_ok=True)
TEMP = tempfile.TemporaryDirectory(prefix="flowforge-tests-", dir=ROOT / ".tmp")
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(TEMP.name) / "tests.db")
os.environ["FLOWFORGE_DATA"] = str(Path(TEMP.name) / "data")
import pytest
from fastapi.testclient import TestClient
from backend.app.api import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c
    from backend.app.store import engine

    engine.dispose()
