import pytest
from fastapi.testclient import TestClient
from gridsense.api import create_app
from gridsense.config import Settings


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}", demo_mode=True))
    with TestClient(app) as client:
        yield client
