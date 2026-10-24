"""Resumable uploads, checksum checks, keys, cross-org denial, downloads, report, processing."""

import uuid
from typing import Any
from unittest import mock

import pytest

from precisecapture.attachments import storage
from precisecapture.attachments.models import Attachment
from precisecapture.attachments.tasks import post_process
from precisecapture.common.ids import uuid7
from precisecapture.common.tenancy import tenant_context
from tests.attachments.conftest import jpeg_bytes, sha256, upload_parts
from tests.features.test_features_api import FARMER, create_farm, create_farmer

pytestmark = pytest.mark.django_db


@pytest.fixture
def farm(people, pilot):
    api = people["manager"]["api"]
    farmer = create_farmer(api, pilot).json()
    return create_farm(api, pilot, farmer["id"]).json()


def start(api: Any, farm: dict[str, Any], data: bytes, **over: Any) -> Any:
    body = {
        "id": str(uuid7()),
        "feature_id": farm["id"],
        "field_key": "photos",
        "content_type": "image/jpeg",
        "size": len(data),
        "checksum_sha256": sha256(data),
        "captured_at": "2026-10-22T10:15:02Z",
        **over,
    }
    return api.post("/api/v1/attachments", body)


def test_full_upload_flow_with_download_and_post_processing(people, farm, project, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    api = people["manager"]["api"]
    data = jpeg_bytes()
    r = start(api, farm, data)
    assert r.status_code == 201, r.content
    up = r.json()
    assert up["part_size"] == 8 * 1024 * 1024 and [p["part_number"] for p in up["parts"]] == [1]
    assert "X-Amz-Signature" in up["parts"][0]["url"]
    etags = upload_parts(up["parts"], data, up["part_size"])
    r = api.post(
        f"/api/v1/attachments/{up['id']}/complete", {"upload_id": up["upload_id"], "parts": etags}
    )
    assert r.status_code == 200, r.content
    out = r.json()
    assert (
        out["upload_status"] == "complete"
        and out["download_url"]
        and "X-Amz-Expires=900" in out["download_url"]
    )
    with tenant_context(project.org_id):
        att = Attachment.objects.get(pk=up["id"])
        assert (
            att.storage_key
            == f"org/{project.org_id}/project/{project.id}/feature/{farm['id']}/{up['id']}.jpg"
        )
        head = storage.head(att.storage_key)
        assert head is not None and head["ContentLength"] == len(data)
        # post-processing (eager Celery): EXIF + thumbnail
        assert post_process(str(project.org_id), str(att.id)) in ("ok", "skipped")
        att.refresh_from_db()
        assert att.exif_lat == pytest.approx(6.33, abs=1e-3) and att.exif_lon == pytest.approx(
            -2.83, abs=1e-3
        )
        assert att.exif_time is not None and att.thumbnail_key.endswith(".thumb.jpg")
        assert storage.head(att.thumbnail_key) is not None
    out = api.get(f"/api/v1/attachments/{up['id']}").json()
    assert out["thumbnail_url"] and out["metadata"]["exif_lat"] == pytest.approx(6.33, abs=1e-3)
    listed = api.get(f"/api/v1/features/{farm['id']}/attachments").json()
    assert [a["id"] for a in listed] == [up["id"]]
    # complete is idempotent
    assert (
        api.post(
            f"/api/v1/attachments/{up['id']}/complete", {"upload_id": "", "parts": []}
        ).status_code
        == 200
    )


def test_interrupted_upload_resumes_with_only_the_missing_parts(people, farm, settings):
    api = people["manager"]["api"]
    settings_part = 5 * 1024 * 1024
    data = jpeg_bytes() + b"\0" * (
        2 * settings_part + 123
    )  # 3 parts at 5 MB... but server uses 8 MB parts
    with mock.patch.object(storage, "PART_SIZE", settings_part):
        r = start(api, farm, data)
        assert r.status_code == 201, r.content
        up = r.json()
        assert [p["part_number"] for p in up["parts"]] == [1, 2, 3] and up[
            "part_size"
        ] == settings_part
        upload_parts(up["parts"], data, settings_part, skip={2})  # part 2 "lost"
        r = api.post(
            f"/api/v1/attachments/{up['id']}/complete", {"upload_id": up["upload_id"], "parts": []}
        )
        assert r.status_code == 422 and r.json()["errors"][0]["code"] == "missing_parts"
        r = api.get(f"/api/v1/attachments/{up['id']}/upload")
        assert r.status_code == 200 and [p["part_number"] for p in r.json()["parts"]] == [2]
        upload_parts(r.json()["parts"], data, settings_part)
        # re-posting the create with the same id also resumes (nothing missing now)
        r = start(api, farm, data, id=up["id"])
        assert r.status_code == 201 and r.json()["parts"] == []
        r = api.post(
            f"/api/v1/attachments/{up['id']}/complete", {"upload_id": up["upload_id"], "parts": []}
        )
        assert r.status_code == 200 and r.json()["size"] == len(data)


def test_checksum_mismatch_is_rejected_and_the_object_removed(people, farm, project):
    api = people["manager"]["api"]
    data = jpeg_bytes()
    r = start(api, farm, data, checksum_sha256="b" * 64)
    up = r.json()
    etags = upload_parts(up["parts"], data, up["part_size"])
    r = api.post(
        f"/api/v1/attachments/{up['id']}/complete", {"upload_id": up["upload_id"], "parts": etags}
    )
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "checksum_sha256"
    with tenant_context(project.org_id):
        att = Attachment.objects.get(pk=up["id"])
        assert att.upload_status == "failed" and "checksum" in att.failure_reason
        assert storage.head(att.storage_key) is None
    # a failed upload can be restarted
    r = api.get(f"/api/v1/attachments/{up['id']}/upload")
    assert r.status_code == 200 and [p["part_number"] for p in r.json()["parts"]] == [1]
    assert api.get(f"/api/v1/attachments/{up['id']}").json()["download_url"] is None


def test_size_mismatch_and_wrong_etag(people, farm):
    api = people["manager"]["api"]
    data = jpeg_bytes()
    up = start(api, farm, data, size=len(data) + 5).json()
    etags = upload_parts(up["parts"], data, up["part_size"])
    r = api.post(
        f"/api/v1/attachments/{up['id']}/complete", {"upload_id": up["upload_id"], "parts": etags}
    )
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "size"
    up = start(api, farm, data).json()
    upload_parts(up["parts"], data, up["part_size"])
    r = api.post(
        f"/api/v1/attachments/{up['id']}/complete",
        {"upload_id": up["upload_id"], "parts": [{"part_number": 1, "etag": '"deadbeef"'}]},
    )
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "etag_mismatch"


def test_field_must_be_a_media_field_and_feature_must_be_visible(people, farm, pilot):
    api = people["manager"]["api"]
    data = jpeg_bytes()
    r = start(api, farm, data, field_key="crop")
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "not_media"
    r = start(api, {"id": str(uuid.uuid4())}, data)
    assert r.status_code == 404
    # collectors not on the project cannot start uploads
    assert start(people["collector"]["api"], farm, data).status_code == 403


def test_cross_org_access_is_denied(people, farm, client):
    api = people["manager"]["api"]
    data = jpeg_bytes()
    up = start(api, farm, data).json()
    from tests.factories import MembershipFactory, OrganisationFactory, UserFactory
    from tests.projects.conftest import Api, login

    other = OrganisationFactory()
    outsider = UserFactory(email="out@example.org")
    MembershipFactory(user=outsider, org=other, role="owner")
    out = Api(client, login(client, "out@example.org"), str(other.id))
    assert out.get(f"/api/v1/attachments/{up['id']}").status_code == 404
    assert out.get(f"/api/v1/attachments/{up['id']}/upload").status_code == 404
    assert (
        out.post(
            f"/api/v1/attachments/{up['id']}/complete", {"upload_id": "x", "parts": []}
        ).status_code
        == 404
    )
    assert out.get(f"/api/v1/features/{farm['id']}/attachments").status_code == 404


def test_missing_attachments_report(people, farm, pilot, project):
    api = people["manager"]["api"]
    r = api.get(f"/api/v1/projects/{project.id}/reports/missing-attachments")
    assert r.status_code == 200
    assert [(x["layer_key"], x["missing_fields"]) for x in r.json()] == [("lyr_farms", ["photos"])]
    data = jpeg_bytes()
    up = start(api, farm, data).json()
    etags = upload_parts(up["parts"], data, up["part_size"])
    api.post(
        f"/api/v1/attachments/{up['id']}/complete", {"upload_id": up["upload_id"], "parts": etags}
    )
    assert api.get(f"/api/v1/projects/{project.id}/reports/missing-attachments").json() == []
    assert (
        people["collector"]["api"]
        .get(f"/api/v1/projects/{project.id}/reports/missing-attachments")
        .status_code
        == 403
    )


def test_attachments_survive_feature_deletion(people, farm, project):
    api = people["manager"]["api"]
    data = jpeg_bytes()
    up = start(api, farm, data).json()
    etags = upload_parts(up["parts"], data, up["part_size"])
    api.post(
        f"/api/v1/attachments/{up['id']}/complete", {"upload_id": up["upload_id"], "parts": etags}
    )
    assert api.delete(f"/api/v1/features/{farm['id']}").status_code == 204
    with tenant_context(project.org_id):
        att = Attachment.objects.get(pk=up["id"])
        assert att.upload_status == "complete" and storage.head(att.storage_key) is not None
    assert api.get(f"/api/v1/attachments/{up['id']}").status_code == 200


_ = FARMER
