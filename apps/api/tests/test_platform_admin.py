"""The Django admin is off unless PLATFORM_ADMIN_ENABLED, and then uses the platform alias."""

import pytest
from django.contrib.admin.sites import AdminSite

from precisecapture.accounts.admin import UserAdmin
from precisecapture.accounts.models import User
from precisecapture.common.admin import PLATFORM_ALIAS
from precisecapture.orgs.admin import MembershipAdmin, OrganisationAdmin
from precisecapture.orgs.models import Membership, Organisation


@pytest.mark.django_db
def test_admin_is_not_mounted_by_default(client, settings):
    assert settings.PLATFORM_ADMIN_ENABLED is False
    assert "django.contrib.admin" not in settings.INSTALLED_APPS
    r = client.get("/platform-admin/")
    assert r.status_code == 404
    assert r["Content-Type"] == "application/problem+json"


@pytest.mark.parametrize(
    ("admin_cls", "model"),
    [(UserAdmin, User), (OrganisationAdmin, Organisation), (MembershipAdmin, Membership)],
)
@pytest.mark.django_db
def test_model_admins_query_the_platform_alias(rf, admin_cls, model):
    ma = admin_cls(model, AdminSite())
    qs = ma.get_queryset(rf.get("/platform-admin/"))
    assert qs.db == PLATFORM_ALIAS
    assert ma.using == PLATFORM_ALIAS
