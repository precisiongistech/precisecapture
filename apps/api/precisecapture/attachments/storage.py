"""
Object storage access for attachments through boto3, configured only from settings
(DigitalOcean Spaces in production, MinIO or any S3-compatible store locally).
Never local paths (CLAUDE.md rule 4).
"""

import contextlib
import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cache
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from django.conf import settings

PART_SIZE = 8 * 1024 * 1024  # 8 MB parts (ENGINEERING_NOTES.md §5)
PART_URL_TTL_SECONDS = 3600


@dataclass(frozen=True)
class PartInfo:
    part_number: int
    etag: str
    size: int


@cache
def client() -> Any:
    return boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL or None,
        region_name=settings.S3_REGION,
        aws_access_key_id=settings.S3_ACCESS_KEY_ID or None,
        aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY or None,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def bucket() -> str:
    name: str = settings.S3_BUCKET
    return name


def ensure_bucket() -> None:
    """Dev and tests only: create the bucket if it does not exist."""
    try:
        client().head_bucket(Bucket=bucket())
    except ClientError:
        client().create_bucket(Bucket=bucket())


def part_count(size: int, part_size: int = PART_SIZE) -> int:
    return max(1, -(-size // part_size))


def start_multipart(key: str, content_type: str) -> str:
    resp = client().create_multipart_upload(Bucket=bucket(), Key=key, ContentType=content_type)
    upload_id: str = resp["UploadId"]
    return upload_id


def presign_part(
    key: str, upload_id: str, part_number: int, ttl: int = PART_URL_TTL_SECONDS
) -> str:
    url: str = client().generate_presigned_url(
        "upload_part",
        Params={"Bucket": bucket(), "Key": key, "UploadId": upload_id, "PartNumber": part_number},
        ExpiresIn=ttl,
    )
    return url


def list_parts(key: str, upload_id: str) -> list[PartInfo]:
    out: list[PartInfo] = []
    marker = 0
    while True:
        resp = client().list_parts(
            Bucket=bucket(), Key=key, UploadId=upload_id, PartNumberMarker=marker
        )
        out.extend(
            PartInfo(int(p["PartNumber"]), str(p["ETag"]), int(p["Size"]))
            for p in resp.get("Parts", [])
        )
        if not resp.get("IsTruncated"):
            return out
        marker = int(resp["NextPartNumberMarker"])


def complete_multipart(key: str, upload_id: str, parts: list[tuple[int, str]]) -> None:
    client().complete_multipart_upload(
        Bucket=bucket(),
        Key=key,
        UploadId=upload_id,
        MultipartUpload={"Parts": [{"PartNumber": n, "ETag": e} for n, e in sorted(parts)]},
    )


def abort_multipart(key: str, upload_id: str) -> None:
    with contextlib.suppress(ClientError):
        client().abort_multipart_upload(Bucket=bucket(), Key=key, UploadId=upload_id)


def head(key: str) -> dict[str, Any] | None:
    try:
        resp: dict[str, Any] = client().head_object(Bucket=bucket(), Key=key)
        return resp
    except ClientError:
        return None


def stream(key: str, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    body = client().get_object(Bucket=bucket(), Key=key)["Body"]
    while True:
        chunk = body.read(chunk_size)
        if not chunk:
            return
        yield chunk


def sha256_of(key: str) -> str:
    digest = hashlib.sha256()
    for chunk in stream(key):
        digest.update(chunk)
    return digest.hexdigest()


def read_all(key: str, max_bytes: int) -> bytes:
    data = bytearray()
    for chunk in stream(key):
        data.extend(chunk)
        if len(data) > max_bytes:
            raise ValueError("object too large to buffer")
    return bytes(data)


def put_bytes(key: str, data: bytes, content_type: str) -> None:
    client().put_object(Bucket=bucket(), Key=key, Body=data, ContentType=content_type)


def delete(key: str) -> None:
    with contextlib.suppress(ClientError):
        client().delete_object(Bucket=bucket(), Key=key)


def presign_get(key: str, ttl: int | None = None, filename: str | None = None) -> str:
    params: dict[str, Any] = {"Bucket": bucket(), "Key": key}
    if filename:
        params["ResponseContentDisposition"] = f'inline; filename="{filename}"'
    url: str = client().generate_presigned_url(
        "get_object", Params=params, ExpiresIn=ttl or settings.S3_PRESIGN_EXPIRY_SECONDS
    )
    return url
