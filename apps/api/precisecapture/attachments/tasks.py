"""Post-processing for completed uploads: thumbnail + EXIF (images only)."""

import contextlib
import io
import logging
import uuid
from datetime import datetime
from typing import Any

from celery import shared_task
from django.utils import timezone

from precisecapture.attachments import storage
from precisecapture.attachments.models import Attachment, UploadStatus
from precisecapture.common.tenancy import tenant_context

log = logging.getLogger(__name__)
THUMB_PX = 320
MAX_IMAGE_BYTES = 60 * 1024 * 1024


def _dms_to_deg(value: Any, ref: str | None) -> float | None:
    try:
        d, m, s = (float(v) for v in value)
    except (TypeError, ValueError):
        return None
    deg = d + m / 60 + s / 3600
    return -deg if ref in ("S", "W") else deg


def extract_exif(data: bytes) -> dict[str, Any]:
    """{lat, lon, time} from EXIF where present; never raises."""
    from PIL import ExifTags, Image

    out: dict[str, Any] = {}
    try:
        with Image.open(io.BytesIO(data)) as img:
            exif = img.getexif()
            if not exif:
                return out
            taken = exif.get(ExifTags.Base.DateTimeOriginal) or exif.get(ExifTags.Base.DateTime)
            if isinstance(taken, str):
                with contextlib.suppress(ValueError):
                    out["time"] = datetime.strptime(taken, "%Y:%m:%d %H:%M:%S").replace(
                        tzinfo=timezone.get_current_timezone()
                    )
            gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
            if gps:
                lat = _dms_to_deg(
                    gps.get(ExifTags.GPS.GPSLatitude), gps.get(ExifTags.GPS.GPSLatitudeRef)
                )
                lon = _dms_to_deg(
                    gps.get(ExifTags.GPS.GPSLongitude), gps.get(ExifTags.GPS.GPSLongitudeRef)
                )
                if lat is not None and lon is not None:
                    out["lat"], out["lon"] = lat, lon
    except Exception:  # corrupt images must not break the task
        log.exception("EXIF extraction failed")
    return out


def make_thumbnail(data: bytes, max_px: int = THUMB_PX) -> bytes:
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img) or img
        img.thumbnail((max_px, max_px))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=80)
        return buf.getvalue()


@shared_task(name="attachments.post_process")
def post_process(org_id: str, attachment_id: str) -> str:
    with tenant_context(uuid.UUID(org_id)):
        att = Attachment.objects.filter(
            pk=attachment_id, upload_status=UploadStatus.COMPLETE
        ).first()
        if att is None:
            return "skipped"
        if not att.is_image:
            return "not-image"
        try:
            data = storage.read_all(att.storage_key, MAX_IMAGE_BYTES)
        except ValueError:
            return "too-large"
        exif = extract_exif(data)
        att.exif_lat, att.exif_lon, att.exif_time = (
            exif.get("lat"),
            exif.get("lon"),
            exif.get("time"),
        )
        try:
            thumb = make_thumbnail(data)
            key = att.storage_key.rsplit(".", 1)[0] + ".thumb.jpg"
            storage.put_bytes(key, thumb, "image/jpeg")
            att.thumbnail_key = key
        except Exception:
            log.exception("Thumbnail failed for %s", att.id)
        att.metadata = {**att.metadata, "processed_at": timezone.now().isoformat()}
        att.save(
            update_fields=[
                "exif_lat",
                "exif_lon",
                "exif_time",
                "thumbnail_key",
                "metadata",
                "updated_at",
            ]
        )
        return "ok"
