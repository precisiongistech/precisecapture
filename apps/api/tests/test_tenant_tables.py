"""
Every concrete TenantModel must have RLS installed, and org A must not see org B's rows.
New tenant tables are picked up automatically (and need a factory in TENANT_FACTORIES).
"""

from collections.abc import Callable
from typing import Any

import pytest
from django.apps import apps
from django.db import DatabaseError, connection

from precisecapture.common.models import TenantModel
from precisecapture.common.tenancy import tenant_context
from tests import factories
from tests.factories import OrganisationFactory

pytestmark = pytest.mark.django_db(transaction=True)


def _project(org: Any) -> Any:
    return factories.ProjectFactory(org=org)


def _layer(org: Any) -> Any:
    return factories.LayerFactory(org=org, project=_project(org))


def _feature(org: Any) -> Any:
    return factories.FeatureFactory(org=org, layer=_layer(org))


# label -> callable(org) creating one row of that model inside the given org
TENANT_FACTORIES: dict[str, Callable[[Any], Any]] = {
    "projects.Project": _project,
    "projects.ProjectMember": lambda org: factories.ProjectMemberFactory(
        org=org, project=_project(org)
    ),
    "projects.Layer": _layer,
    "projects.LayerSchemaVersion": lambda org: factories.LayerSchemaVersionFactory(
        org=org, layer=_layer(org)
    ),
    "projects.LayerTemplate": lambda org: factories.LayerTemplateFactory(org=org),
    "features.Feature": _feature,
    "features.FeatureHistory": lambda org: factories.FeatureHistoryFactory(
        org=org, feature=_feature(org)
    ),
    "features.FeatureRelation": lambda org: factories.FeatureRelationFactory(
        org=org, from_feature=_feature(org), to_feature=_feature(org)
    ),
    "features.RawTrack": lambda org: factories.RawTrackFactory(org=org, feature=_feature(org)),
    "features.VertexMeta": lambda org: factories.VertexMetaFactory(org=org, feature=_feature(org)),
    "sync.ProjectSyncState": lambda org: factories.ProjectSyncStateFactory(
        org=org, project=_project(org)
    ),
    "sync.ChangeLog": lambda org: factories.ChangeLogFactory(org=org, project=_project(org)),
    "sync.AppliedChange": lambda org: factories.AppliedChangeFactory(
        org=org, project=_project(org)
    ),
    "sync.SyncCursor": lambda org: factories.SyncCursorFactory(org=org, project=_project(org)),
    "sync.Conflict": lambda org: factories.ConflictFactory(org=org, feature=_feature(org)),
}

TENANT_MODELS = sorted(
    (
        m
        for m in apps.get_models()
        if issubclass(m, TenantModel) and not m._meta.abstract and m._meta.app_label != "testapp"
    ),
    key=lambda m: m._meta.label,
)


def test_every_tenant_model_has_a_factory_registered():
    missing = [m._meta.label for m in TENANT_MODELS if m._meta.label not in TENANT_FACTORIES]
    assert missing == [], f"add isolation factories for: {missing}"


@pytest.mark.parametrize("model", TENANT_MODELS, ids=lambda m: m._meta.label)
def test_rls_is_installed(model):
    table = model._meta.db_table
    with connection.cursor() as cur:
        cur.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s", [table]
        )
        assert cur.fetchone() == (True, True), f"{table} lacks FORCE ROW LEVEL SECURITY"
        cur.execute("SELECT count(*) FROM pg_policy WHERE polrelid = %s::regclass", [table])
        assert cur.fetchone()[0] == 1, f"{table} lacks the tenant_isolation policy"
    assert any(f.name == "org" for f in model._meta.fields)


@pytest.mark.parametrize("label", sorted(TENANT_FACTORIES), ids=str)
def test_org_a_cannot_read_or_write_org_b(label):
    model = apps.get_model(label)
    make = TENANT_FACTORIES[label]
    a, b = OrganisationFactory(), OrganisationFactory()
    with tenant_context(a.id):
        make(a)
    with tenant_context(b.id):
        row_b = make(b)
    with connection.cursor() as cur:
        cur.execute("SET ROLE pc_app")
    try:
        with tenant_context(a.id):
            assert model.all_tenants.count() == 1, "org B's row leaked into org A"
            assert not model.all_tenants.filter(pk=row_b.pk).exists()
            with pytest.raises(DatabaseError):
                model.all_tenants.filter(pk=model.all_tenants.first().pk).update(org=b)
        assert model.all_tenants.count() == 0  # no tenant context: fail closed
    finally:
        with connection.cursor() as cur:
            cur.execute("RESET ROLE")
