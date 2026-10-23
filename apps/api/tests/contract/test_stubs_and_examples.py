"""M4: stubs answer 501 problem JSON; examples match packages/schema; the contract is stable."""

import json
from pathlib import Path

import pytest
from django.conf import settings as dj_settings

from config.api import api
from precisecapture.attachments.schemas import ATTACHMENT_UPLOAD_EXAMPLE, AttachmentUploadOut
from precisecapture.common.schema_validation import validate_sync_document
from precisecapture.sync.schemas import (
    PULL_RESPONSE_EXAMPLE,
    PUSH_REQUEST_EXAMPLE,
    PUSH_RESPONSE_EXAMPLE,
    PullResponse,
    PushRequest,
    PushResponse,
)
from tests.projects.conftest import Api

pytestmark = pytest.mark.django_db

CONTRACT = Path(dj_settings.BASE_DIR).parent.parent / "contract" / "openapi.json"


@pytest.fixture
def api_client(client, people):
    return people["collector"]["api"]


def test_stubs_return_501_problem_json(api_client: Api):
    """Sync is real since M6 (404: example project absent here); attachments stay stubbed."""
    assert api_client.post("/api/v1/sync/push", PUSH_REQUEST_EXAMPLE).status_code == 404
    assert (
        api_client.get(
            "/api/v1/sync/pull?project=01a16990-2368-7736-9254-4cbea027a751&cursor=0"
        ).status_code
        == 404
    )
    r = api_client.post(
        "/api/v1/attachments",
        {
            "id": "0192f0c1-1234-7abc-8def-0000000000cc",
            "feature_id": "0192f0c1-1234-7abc-8def-000000000001",
            "field_key": "photos",
            "content_type": "image/jpeg",
            "size": 10,
            "checksum_sha256": "a" * 64,
        },
    )
    assert r.status_code == 501 and r["Content-Type"] == "application/problem+json"
    assert r.json()["type"].endswith("/not-implemented")
    assert (
        api_client.post(
            "/api/v1/attachments",
            {
                "id": "0192f0c1-1234-7abc-8def-0000000000cc",
                "feature_id": "0192f0c1-1234-7abc-8def-000000000001",
                "field_key": "photos",
                "content_type": "image/jpeg",
                "size": 10,
                "checksum_sha256": "a" * 64,
            },
        ).status_code
        == 501
    )
    assert (
        api_client.get("/api/v1/attachments/0192f0c1-1234-7abc-8def-0000000000cc").status_code
        == 501
    )


def test_stubs_still_validate_input_and_require_tenant_auth(api_client: Api, client):
    r = api_client.post("/api/v1/sync/push", {"project_id": "x", "changes": []})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "payload.project_id"
    assert (
        client.post(
            "/api/v1/sync/push",
            data=json.dumps(PUSH_REQUEST_EXAMPLE),
            content_type="application/json",
        ).status_code
        == 401
    )
    assert api_client.post("/api/v1/sync/push", PUSH_REQUEST_EXAMPLE, org=False).status_code == 400


@pytest.mark.parametrize(
    ("document", "example", "model"),
    [
        ("PushRequest", PUSH_REQUEST_EXAMPLE, PushRequest),
        ("PushResponse", PUSH_RESPONSE_EXAMPLE, PushResponse),
        ("PullResponse", PULL_RESPONSE_EXAMPLE, PullResponse),
    ],
)
def test_examples_match_the_shared_sync_schema_both_ways(document, example, model):
    # 1. the example is valid under packages/schema/schemas/sync.schema.json
    assert validate_sync_document(document, example) == []
    # 2. the Pydantic model accepts it and re-serialises to something still valid
    parsed = model.model_validate(example)
    round_trip = json.loads(parsed.model_dump_json(exclude_unset=True))
    assert validate_sync_document(document, round_trip) == []


def test_attachment_example_matches_its_model():
    AttachmentUploadOut.model_validate(ATTACHMENT_UPLOAD_EXAMPLE)


def test_openapi_document_is_complete():
    doc = api.get_openapi_schema()
    assert doc["openapi"].startswith("3.1")
    ops = [
        (p, m, op)
        for p, ms in doc["paths"].items()
        for m, op in ms.items()
        if m in ("get", "post", "put", "patch", "delete")
    ]
    ids = [op.get("operationId") for _, _, op in ops]
    assert all(ids) and len(ids) == len(set(ids)), "every operation needs a unique operationId"
    assert all(op.get("tags") for _, _, op in ops)
    for path, _method, op in ops:
        assert "422" in op["responses"] or path.endswith("/health"), path
        if op.get("security") and any("TenantAuth" in s for s in op["security"]):
            assert any(p["name"] == "X-Org-Id" for p in op["parameters"]), path
    assert "Problem" in doc["components"]["schemas"]
    phone = [
        "login",
        "refresh",
        "logout",
        "otpRequest",
        "otpVerify",
        "me",
        "myProjects",
        "registerDevice",
        "getProjectBundle",
        "syncPush",
        "syncPull",
        "createAttachment",
        "completeAttachment",
        "getAttachment",
        "wellKnown",
    ]
    assert set(phone) <= set(ids)
    # examples on the request bodies the phone sends
    for name in ("PushRequest", "LoginIn", "DeviceIn", "AttachmentCreateIn", "OtpVerifyIn"):
        assert doc["components"]["schemas"][name].get("example"), name


def test_committed_contract_matches_the_live_export():
    """`make contract` must be run (and committed) after any API change."""
    live = json.loads(json.dumps(api.get_openapi_schema(), default=str))
    committed = json.loads(CONTRACT.read_text())
    assert committed == live, "contract/openapi.json is stale: run `make contract` and commit it"


@pytest.mark.parametrize(
    ("name", "example"),
    [
        ("push-request", PUSH_REQUEST_EXAMPLE),
        ("push-response", PUSH_RESPONSE_EXAMPLE),
        ("pull-response", PULL_RESPONSE_EXAMPLE),
    ],
)
def test_contract_example_files_match_the_code(name, example):
    """contract/examples/*.json are consumed by the mock smoke test and by Selorm."""
    path = CONTRACT.parent / "examples" / f"{name}.json"
    assert json.loads(path.read_text()) == example, f"regenerate {path} (make contract)"
