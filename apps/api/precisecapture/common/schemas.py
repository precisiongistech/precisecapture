"""Pydantic schemas shared across apps."""

from ninja import Schema


class ProblemError(Schema):
    """One entry of a problem document's `errors[]` list."""

    field: str | None = None
    code: str
    message: str


class Problem(Schema):
    """RFC 9457 problem details (application/problem+json)."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    errors: list[ProblemError] = []


class Page[T](Schema):
    """A cursor-paginated page: `?cursor=&limit=` in, `next_cursor` out."""

    items: list[T]
    next_cursor: str | None = None
    has_more: bool = False


class HealthOut(Schema):
    status: str
    version: str
    checks: dict[str, str]


class WellKnownOut(Schema):
    name: str
    logo_url: str | None
    api_version: str
    min_app_version: str
    auth_methods: list[str]
    api_base_url: str
