"""
Tenant isolation plumbing (ENGINEERING_NOTES.md §1), proven on a test-only tenant table.
Every real tenant table (from M3 on) gets the same tests through the shared helper below.
"""

import uuid

import pytest
from django.db import DatabaseError, connection, transaction

from precisecapture.common.rls import rls_reverse_sql, rls_sql
from precisecapture.common.tenancy import NoTenantContext, current_org_id, tenant_context
from tests.factories import OrganisationFactory
from tests.testapp.models import Secret

pytestmark = pytest.mark.django_db(transaction=True)


def _as_app_role() -> None:
    with connection.cursor() as cur:
        cur.execute("SET ROLE pc_app")


def _reset_role() -> None:
    with connection.cursor() as cur:
        cur.execute("RESET ROLE")


@pytest.fixture
def two_orgs():
    a, b = OrganisationFactory(), OrganisationFactory()
    with tenant_context(a.id):
        Secret.objects.create(note="a1")
        Secret.objects.create(note="a2")
    with tenant_context(b.id):
        Secret.objects.create(note="b1")
    return a, b


def test_rls_sql_uses_nullif_and_force():
    sql = rls_sql("features_feature")
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "NULLIF(current_setting('app.current_org_id', true), '')::uuid" in sql
    assert "WITH CHECK" in sql
    assert "DROP POLICY IF EXISTS tenant_isolation" in rls_reverse_sql("features_feature")


def test_policy_is_installed_on_the_test_tenant_table():
    with connection.cursor() as cur:
        cur.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relname = 'testapp_secret'"
        )
        assert cur.fetchone() == (True, True)
        cur.execute("SELECT polname FROM pg_policy WHERE polrelid = 'testapp_secret'::regclass")
        assert [r[0] for r in cur.fetchall()] == ["tenant_isolation"]


def test_org_a_cannot_read_org_b_as_app_role(two_orgs):
    a, b = two_orgs
    _as_app_role()
    try:
        with tenant_context(a.id):
            assert sorted(Secret.objects.values_list("note", flat=True)) == ["a1", "a2"]
            # Even bypassing the manager, the database hides B's rows.
            assert Secret.all_tenants.filter(org=b).count() == 0
            assert Secret.all_tenants.count() == 2
        with tenant_context(b.id):
            assert list(Secret.objects.values_list("note", flat=True)) == ["b1"]
    finally:
        _reset_role()


def test_insert_with_another_orgs_id_is_rejected_by_the_database(two_orgs):
    a, b = two_orgs
    _as_app_role()
    try:
        with pytest.raises(DatabaseError), tenant_context(a.id):
            Secret.all_tenants.create(org=b, note="smuggled")
    finally:
        _reset_role()


def test_update_cannot_move_a_row_to_another_org(two_orgs):
    a, b = two_orgs
    _as_app_role()
    try:
        with pytest.raises(DatabaseError), tenant_context(a.id):
            Secret.all_tenants.filter(note="a1").update(org=b)
    finally:
        _reset_role()


def test_no_tenant_context_returns_nothing_and_does_not_error(two_orgs):
    _as_app_role()
    try:
        # Never set on this connection: current_setting(..., true) is NULL.
        assert Secret.all_tenants.count() == 0
        assert list(Secret.objects.all()) == []  # manager fails closed too
        # Set once then cleared by commit: a reused pooled connection sees '' not NULL.
        with tenant_context(two_orgs[0].id):
            assert Secret.all_tenants.count() == 2
        with connection.cursor() as cur:
            cur.execute("SELECT current_setting('app.current_org_id', true)")
            assert cur.fetchone()[0] == ""
        assert Secret.all_tenants.count() == 0
    finally:
        _reset_role()


def test_owner_role_is_also_subject_to_force_rls(two_orgs):
    # pc_owner owns the table; FORCE makes the policy apply to it as well.
    assert Secret.all_tenants.count() == 0
    with tenant_context(two_orgs[1].id):
        assert Secret.all_tenants.count() == 1


def test_tenant_model_defaults_org_from_context():
    org = OrganisationFactory()
    with tenant_context(org.id):
        s = Secret.objects.create(note="auto")
        assert s.org_id == org.id
    with pytest.raises(NoTenantContext):
        Secret(note="no ctx").save()


def test_tenant_context_is_transactional_and_restores_contextvar():
    org = OrganisationFactory()
    assert current_org_id() is None
    with pytest.raises(RuntimeError, match="boom"), tenant_context(org.id):
        assert current_org_id() == org.id
        Secret.objects.create(note="rolled back")
        raise RuntimeError("boom")
    assert current_org_id() is None
    with tenant_context(org.id):
        assert Secret.objects.count() == 0


def test_cannot_switch_tenant_inside_a_context():
    a, b = OrganisationFactory(), OrganisationFactory()
    with pytest.raises(NoTenantContext), tenant_context(a.id), tenant_context(b.id):
        pass
    with tenant_context(a.id), tenant_context(a.id):  # same org nests fine
        assert current_org_id() == a.id


def test_setting_is_transaction_local():
    org = OrganisationFactory()
    with tenant_context(org.id):
        pass
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SELECT NULLIF(current_setting('app.current_org_id', true), '')")
        assert cur.fetchone()[0] is None
    assert uuid.UUID(str(org.id)) == org.id
