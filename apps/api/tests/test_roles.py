"""The database role setup from infra/docker/postgres-init is what the app relies on."""

import pytest
from django.db import connection


def _scalar(sql: str) -> object:
    with connection.cursor() as cur:
        cur.execute(sql)
        row = cur.fetchone()
        return row[0] if row else None


@pytest.mark.django_db
def test_roles_exist_with_expected_rls_bypass():
    rows = {}
    with connection.cursor() as cur:
        cur.execute(
            "SELECT rolname, rolbypassrls FROM pg_roles WHERE rolname LIKE 'pc\\_%' ORDER BY 1"
        )
        rows = dict(cur.fetchall())
    assert rows == {"pc_app": False, "pc_owner": False, "pc_platform": True, "pc_tiles": False}


@pytest.mark.django_db
def test_test_database_has_postgis_from_template1():
    assert _scalar("SELECT extversion FROM pg_extension WHERE extname = 'postgis'")


@pytest.mark.django_db
def test_app_role_can_use_tables_created_by_owner_in_test_database(as_app_role):
    # Default privileges came from template1, so pc_app can read tables pc_owner just created.
    assert _scalar("SELECT current_user") == "pc_app"
    assert _scalar("SELECT count(*) FROM testapp_widget") == 0


@pytest.mark.django_db
def test_app_role_cannot_create_tables(as_app_role):
    from django.db import ProgrammingError, transaction

    with pytest.raises(ProgrammingError), transaction.atomic(), connection.cursor() as cur:
        cur.execute("CREATE TABLE should_fail (id int)")
