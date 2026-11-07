import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture()
def client(tmp_path):
    settings = Settings(database_url="sqlite://", static_dir=tmp_path / "none")
    with TestClient(create_app(settings)) as c:
        yield c


def auth(token: str) -> dict:
    return {"X-Player-Token": token}


@pytest.fixture()
def game(client):
    """A game with a host (Hana) and two players (Ana, Ben), each with 1000."""
    r = client.post("/api/games", json={"host_name": "Hana", "starting_balance": 1000})
    assert r.status_code == 201
    host = r.json()
    code = host["code"]
    players = {}
    for name in ("Ana", "Ben"):
        j = client.post(f"/api/games/{code}/join", json={"name": name})
        assert j.status_code == 201
        players[name] = j.json()
    return {"code": code, "host": host, **players}
