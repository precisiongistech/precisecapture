"""Every error leaves the API as RFC 9457 problem JSON, with no stack trace."""

from http import HTTPStatus

import pytest
from django.http import HttpRequest
from django.test import Client
from django.urls import path
from ninja import NinjaAPI, Schema

from precisecapture.common.errors import (
    PROBLEM_CONTENT_TYPE,
    NotFound,
    UnprocessableEntity,
    register_exception_handlers,
)

pytestmark = pytest.mark.django_db  # ATOMIC_REQUESTS opens a transaction per API request

api = NinjaAPI(urls_namespace="errors-test")
register_exception_handlers(api)


class In(Schema):
    count: int
    name: str


@api.post("/validate", auth=None)
def validate(request: HttpRequest, payload: In) -> dict[str, object]:
    return {"ok": True}


@api.get("/not-found", auth=None)
def not_found(request: HttpRequest) -> None:
    raise NotFound("Feature 123 does not exist")


@api.get("/unprocessable", auth=None)
def unprocessable(request: HttpRequest) -> None:
    raise UnprocessableEntity(
        "Schema invalid",
        errors=[{"field": "fields.0.key", "code": "duplicate", "message": "Key already used"}],
    )


@api.get("/boom", auth=None)
def boom(request: HttpRequest) -> None:
    raise RuntimeError("secret internal detail")


urlpatterns = [path("t/", api.urls)]
handler404 = "precisecapture.common.errors.handler404"
handler500 = "precisecapture.common.errors.handler500"


@pytest.fixture
def tclient(settings) -> Client:
    settings.ROOT_URLCONF = __name__
    return Client(raise_request_exception=False)


def test_validation_error_is_422_problem_with_per_field_errors(tclient):
    r = tclient.post("/t/validate", data='{"count": "x"}', content_type="application/json")
    assert r.status_code == 422
    assert r["Content-Type"] == PROBLEM_CONTENT_TYPE
    body = r.json()
    assert body["type"].endswith("/validation-failed")
    assert body["status"] == 422
    assert body["instance"] == "/t/validate"
    fields = {e["field"] for e in body["errors"]}
    assert fields == {"payload.count", "payload.name"}
    assert all(e["code"] and e["message"] for e in body["errors"])


def test_problem_exception_maps_status_slug_and_detail(tclient):
    r = tclient.get("/t/not-found")
    assert r.status_code == 404
    assert r.json() == {
        "type": "https://precisecapture.app/problems/not-found",
        "title": "Not found",
        "status": 404,
        "detail": "Feature 123 does not exist",
        "instance": "/t/not-found",
        "errors": [],
    }


def test_problem_exception_carries_errors_list(tclient):
    body = tclient.get("/t/unprocessable").json()
    assert body["status"] == 422
    assert body["errors"] == [
        {"field": "fields.0.key", "code": "duplicate", "message": "Key already used"}
    ]


def test_unknown_route_is_404_problem(tclient):
    r = tclient.get("/t/does-not-exist")
    assert r.status_code == 404
    assert r["Content-Type"] == PROBLEM_CONTENT_TYPE


def test_unhandled_exception_is_500_problem_without_stack_trace(tclient, caplog):
    r = tclient.get("/t/boom")
    assert r.status_code == 500
    assert r["Content-Type"] == PROBLEM_CONTENT_TYPE
    assert r.json()["title"] == HTTPStatus.INTERNAL_SERVER_ERROR.phrase
    assert "secret internal detail" not in r.content.decode()
    assert "Traceback" not in r.content.decode()
    assert any("Unhandled error" in rec.message for rec in caplog.records)
