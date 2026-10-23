import pytest


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path", ["/.well-known/precisecapture", "/api/v1/.well-known/precisecapture"]
)
def test_well_known_document(client, settings, path):
    settings.INSTANCE_NAME = "Ghana Cocoa Board"
    settings.INSTANCE_LOGO_URL = "https://cdn.example/logo.png"
    settings.PUBLIC_BASE_URL = "https://capture.example.org/"
    settings.MIN_APP_VERSION = "0.3.0"
    r = client.get(path)
    assert r.status_code == 200
    assert r.json() == {
        "name": "Ghana Cocoa Board",
        "logo_url": "https://cdn.example/logo.png",
        "api_version": "1",
        "min_app_version": "0.3.0",
        "auth_methods": ["password"],
        "api_base_url": "https://capture.example.org/api/v1",
    }


def test_well_known_needs_no_database(client, django_db_blocker):
    # A phone checks compatibility before login; this must not touch tenant data at all.
    with django_db_blocker.block():
        assert client.get("/.well-known/precisecapture").status_code == 200
