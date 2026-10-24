import hashlib
import io
from typing import Any

import pytest
import requests
from botocore.exceptions import EndpointConnectionError

from precisecapture.attachments import storage
from tests.features.conftest import pilot
from tests.projects.conftest import Api, example, login, org, people, project

__all__ = ["Api", "example", "login", "org", "people", "pilot", "project"]


@pytest.fixture(scope="session", autouse=True)
def _bucket() -> None:
    """Attachment tests need a reachable S3-compatible store (MinIO locally, versitygw in CI)."""
    import django

    django.setup()
    try:
        storage.ensure_bucket()
    except EndpointConnectionError as exc:  # pragma: no cover
        pytest.exit(f"S3 store not reachable at S3_ENDPOINT_URL: {exc}", returncode=3)


def jpeg_bytes(with_gps: bool = True, size_px: int = 64) -> bytes:
    """A small JPEG, optionally with EXIF GPS (6.33N, 2.83W) and DateTimeOriginal."""
    from PIL import ExifTags, Image
    from PIL.TiffImagePlugin import IFDRational

    img = Image.new("RGB", (size_px, size_px), (200, 120, 40))
    exif = Image.Exif()
    exif[ExifTags.Base.DateTimeOriginal] = "2026:10:22 10:15:02"
    if with_gps:
        gps = {
            ExifTags.GPS.GPSLatitudeRef: "N",
            ExifTags.GPS.GPSLatitude: (IFDRational(6), IFDRational(19), IFDRational(48)),
            ExifTags.GPS.GPSLongitudeRef: "W",
            ExifTags.GPS.GPSLongitude: (IFDRational(2), IFDRational(49), IFDRational(48)),
        }
        exif[ExifTags.IFD.GPSInfo] = gps
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def upload_parts(
    parts: list[dict[str, Any]], data: bytes, part_size: int, skip: set[int] | None = None
) -> list[dict[str, Any]]:
    """PUT each presigned part like the phone would; returns {part_number, etag} per part sent."""
    sent = []
    for p in parts:
        n = int(p["part_number"])
        if skip and n in skip:
            continue
        chunk = data[(n - 1) * part_size : n * part_size]
        r = requests.put(p["url"], data=chunk, timeout=30)
        assert r.status_code == 200, (r.status_code, r.text[:200])
        sent.append({"part_number": n, "etag": r.headers["ETag"]})
    return sent
