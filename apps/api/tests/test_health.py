import pytest
from django.db import DatabaseError, connections


@pytest.mark.django_db
def test_root_health_returns_200_with_db_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"database": "ok"}
    assert body["version"]


@pytest.mark.django_db
def test_api_health_is_in_openapi_and_returns_200(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    spec = client.get("/api/v1/openapi.json").json()
    assert "/api/v1/health" in spec["paths"]
    assert spec["paths"]["/api/v1/health"]["get"]["operationId"] == "health"


def test_health_reports_503_when_database_fails(client, monkeypatch):
    class BrokenCursor:
        def __enter__(self):
            raise DatabaseError("boom")

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(connections["default"], "cursor", lambda *a, **k: BrokenCursor())
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["status"] == "degraded"
    assert r.json()["checks"]["database"].startswith("error:")


@pytest.mark.django_db
def test_health_rejects_post(client):
    assert client.post("/health").status_code == 405
