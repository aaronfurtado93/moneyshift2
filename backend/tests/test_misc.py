def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_info_reports_lan_url(client):
    data = client.get("/api/info").json()
    assert data["base_url"].startswith("http://") and str(data["port"]) in data["base_url"]


def test_app_answers_503_while_frontend_is_being_rebuilt(tmp_path):
    """A rebuild wipes index.html for a few seconds; phones should get a polite retry page, not an error."""
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app

    static = tmp_path / "browser"
    static.mkdir()
    with TestClient(create_app(Settings(database_url="sqlite://", static_dir=static))) as c:
        r = c.get("/join/ABCD")
        assert r.status_code == 503 and r.headers["retry-after"] == "3"
        (static / "index.html").write_text("<html>app</html>")
        assert c.get("/join/ABCD").status_code == 200
        assert c.get("/api/health").status_code == 200  # the API is unaffected
