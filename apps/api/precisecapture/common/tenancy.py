"""
Tenant context: which organisation the current transaction may see.

RLS policies compare `org_id` with `current_setting('app.current_org_id', true)`. The value
is set per transaction (`set_config(..., true)`), so it must be set inside the transaction
that runs the queries: the Ninja auth class does that for requests (common/auth.py), and
`tenant_context()` does it for Celery tasks, management commands and tests.

A contextvar mirrors the setting so Python code (the tenant default manager, services) can
read the current org without a query. ENGINEERING_NOTES.md §1.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from django.db import connections, transaction

_current_org: ContextVar[uuid.UUID | None] = ContextVar("precisecapture_current_org", default=None)

SETTING_NAME = "app.current_org_id"


def current_org_id() -> uuid.UUID | None:
    return _current_org.get()


def require_org_id() -> uuid.UUID:
    org_id = _current_org.get()
    if org_id is None:
        raise NoTenantContext("No tenant context: wrap the call in tenant_context(org_id).")
    return org_id


class NoTenantContext(RuntimeError):
    pass


def clear_tenant() -> None:
    """Drop the contextvar (the DB setting is transaction-local and clears itself)."""
    _current_org.set(None)


def enter_tenant(org_id: uuid.UUID, using: str = "default") -> None:
    """
    Set the tenant for the rest of the current transaction and thread (used by the request
    auth class, which runs inside ATOMIC_REQUESTS and cannot wrap the view in a `with`).
    The middleware clears the contextvar when the request ends.
    """
    _current_org.set(org_id)
    set_db_tenant(org_id, using)


def set_db_tenant(org_id: uuid.UUID | None, using: str = "default") -> None:
    """Set the transaction-local Postgres setting the RLS policies read."""
    with connections[using].cursor() as cur:
        cur.execute(
            "SELECT set_config(%s, %s, true)", [SETTING_NAME, str(org_id) if org_id else ""]
        )


@contextmanager
def tenant_context(org_id: uuid.UUID, using: str = "default") -> Iterator[uuid.UUID]:
    """
    Run the block inside a transaction scoped to one organisation.

    Nested use with the same org is fine; a different org inside an open context is a bug.
    """
    outer = _current_org.get()
    if outer is not None and outer != org_id:
        raise NoTenantContext(f"Already inside tenant_context({outer}); cannot switch to {org_id}.")
    token = _current_org.set(org_id)
    try:
        with transaction.atomic(using=using):
            set_db_tenant(org_id, using)
            yield org_id
    finally:
        _current_org.reset(token)
