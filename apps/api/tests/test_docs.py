import pytest

pytestmark = pytest.mark.django_db  # ATOMIC_REQUESTS opens a transaction per API request


def test_openapi_ui_is_served(client):
    r = client.get("/api/v1/docs")
    assert r.status_code == 200
    assert b"openapi.json" in r.content


def test_openapi_json_is_3_1(client):
    spec = client.get("/api/v1/openapi.json").json()
    assert spec["openapi"].startswith("3.1")
    assert spec["info"]["title"] == "PreciseCapture API"
