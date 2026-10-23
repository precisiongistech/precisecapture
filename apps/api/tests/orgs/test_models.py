import pytest
from django.db import IntegrityError

from precisecapture.orgs.models import Membership, Organisation, Role, role_at_least
from tests.factories import MembershipFactory, OrganisationFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_unique_slug_increments():
    OrganisationFactory(name="Cocoa Board")
    assert Organisation.unique_slug("Cocoa Board") == "cocoa-board-2"
    assert Organisation.unique_slug("!!!") == "org"


def test_capture_defaults_reads_settings():
    org = OrganisationFactory(settings={"capture_defaults": {"gps": {"maxAccuracyMeters": 5}}})
    assert org.capture_defaults == {"gps": {"maxAccuracyMeters": 5}}
    assert OrganisationFactory(settings={}).capture_defaults == {}


def test_membership_is_unique_per_user_and_org():
    m = MembershipFactory()
    with pytest.raises(IntegrityError):
        Membership.objects.create(user=m.user, org=m.org, role=Role.VIEWER)


def test_user_can_belong_to_several_orgs():
    user = UserFactory()
    MembershipFactory(user=user, role=Role.ADMIN)
    MembershipFactory(user=user, role=Role.COLLECTOR)
    assert user.memberships.count() == 2


def test_bump_version():
    m = MembershipFactory()
    m.bump_version()
    m.refresh_from_db()
    assert m.version == 2


@pytest.mark.parametrize(
    ("role", "minimum", "ok"),
    [
        (Role.OWNER, Role.ADMIN, True),
        (Role.ADMIN, Role.ADMIN, True),
        (Role.MANAGER, Role.ADMIN, False),
        (Role.COLLECTOR, Role.VIEWER, True),
        (Role.VIEWER, Role.COLLECTOR, False),
        ("bogus", Role.VIEWER, False),
    ],
)
def test_role_at_least(role, minimum, ok):
    assert role_at_least(role, minimum) is ok
