"""UUIDv7 generation (ENGINEERING_NOTES.md §1, Identifiers)."""

import uuid

import uuid_utils


def uuid7() -> uuid.UUID:
    """A time-ordered UUIDv7 as a standard-library UUID (what Django fields expect)."""
    return uuid.UUID(bytes=uuid_utils.uuid7().bytes)
