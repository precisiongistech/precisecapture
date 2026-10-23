import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from precisecapture.accounts.models import User, normalise_phone
from tests.factories import PhoneUserFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_user_has_uuid7_pk_and_argon2_password():
    u = User.objects.create_user(email="Ama@Example.org", password="s3cret-pass")
    assert u.id.version == 7
    assert u.email == "ama@example.org"  # normalised
    assert u.password.startswith("argon2$") or u.password.startswith(
        "md5$"
    )  # md5 under test settings
    assert u.check_password("s3cret-pass")
    assert u.is_active


def test_phone_only_user_is_allowed_and_normalised():
    u = User.objects.create_user(phone="0024 424 123 4567")
    assert u.email is None
    assert u.phone == "+244241234567"
    assert not u.has_usable_password()


def test_user_needs_email_or_phone():
    with pytest.raises(ValidationError):
        User.objects.create_user()
    # The database enforces it too, not only full_clean().
    with pytest.raises(IntegrityError):
        User(email=None, phone=None).save()


@pytest.mark.parametrize("bad", ["0241234567", "+0241234567", "+233 24", "12345"])
def test_phone_must_be_e164(bad):
    with pytest.raises(ValidationError):
        User.objects.create_user(phone=bad)


def test_email_and_phone_are_unique_but_null_is_not():
    UserFactory(email="dup@example.org")
    with pytest.raises(ValidationError):
        User.objects.create_user(email="DUP@example.org")
    PhoneUserFactory()
    PhoneUserFactory()  # two phone-only users with email NULL coexist


def test_by_identifier_finds_email_or_phone():
    u1 = UserFactory(email="kofi@example.org")
    u2 = PhoneUserFactory(phone="+233241234567")
    assert User.objects.by_identifier(" Kofi@Example.org ") == u1
    assert User.objects.by_identifier("+233 24 123 4567") == u2
    assert User.objects.by_identifier("nobody@example.org") is None


def test_disabled_user_is_not_active():
    u = UserFactory(status=User.Status.DISABLED)
    assert not u.is_active


def test_normalise_phone_blank_is_none():
    assert normalise_phone("") is None
    assert normalise_phone(None) is None
