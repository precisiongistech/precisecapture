import pytest
from django.db import connection
from django.test import Client


@pytest.fixture
def client() -> Client:
    return Client()


@pytest.fixture
def as_app_role(db: None):
    """
    Run the test's queries as `pc_app` (SET ROLE), the role Django uses in production.

    pc_owner is granted pc_app in the role setup, so tests can switch to it and prove
    that RLS applies to the application role. Reset at the end.
    """
    with connection.cursor() as cur:
        cur.execute("SET ROLE pc_app")
    yield
    with connection.cursor() as cur:
        cur.execute("RESET ROLE")
