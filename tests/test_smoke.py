from fastapi.testclient import TestClient

from api.main import app


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_frontend_served() -> None:
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert b"CraniumPy" in response.content
