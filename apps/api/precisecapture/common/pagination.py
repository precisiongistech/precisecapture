"""
Cursor (keyset) pagination: `?cursor=&limit=` in, `{items, next_cursor, has_more}` out.

The cursor is an opaque base64url string holding the ordering key of the last row
returned. It stays valid when rows are inserted or deleted, unlike an offset.
Default ordering is by `id`, which for UUIDv7 primary keys is creation order.
"""

import base64
import binascii
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from django.db.models import Model, QuerySet
from ninja import Schema

from precisecapture.common.errors import ProblemException

DEFAULT_LIMIT = 100
MAX_LIMIT = 500


class CursorParams(Schema):
    cursor: str | None = None
    limit: int = DEFAULT_LIMIT


class InvalidCursor(ProblemException):
    status = 400
    slug = "invalid-cursor"
    title = "Invalid cursor"


@dataclass(frozen=True)
class Paginated[M]:
    items: list[M]
    next_cursor: str | None
    has_more: bool


def encode_cursor(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> str:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode()).decode()
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise InvalidCursor("The cursor is not valid. Start again without a cursor.") from exc


def clamp_limit(limit: int | None) -> int:
    if limit is None or limit < 1:
        return DEFAULT_LIMIT
    return min(limit, MAX_LIMIT)


def paginate[M: Model](
    queryset: QuerySet[M],
    *,
    cursor: str | None,
    limit: int | None,
    key: str = "id",
    key_of: Callable[[M], Any] | None = None,
) -> Paginated[M]:
    """
    Page a queryset by keyset on a single unique, ascending field (`key`).

    The queryset's own ordering is replaced by `key`. `key_of` extracts the key from an
    instance (defaults to attribute access) and its `str()` goes into the cursor.
    """
    size = clamp_limit(limit)
    qs = queryset.order_by(key)
    if cursor:
        qs = qs.filter(**{f"{key}__gt": decode_cursor(cursor)})
    rows: Sequence[M] = list(qs[: size + 1])
    has_more = len(rows) > size
    items = list(rows[:size])
    next_cursor = None
    if has_more and items:
        last = items[-1]
        last_key = key_of(last) if key_of else getattr(last, key)
        next_cursor = encode_cursor(str(last_key))
    return Paginated(items=items, next_cursor=next_cursor, has_more=has_more)
