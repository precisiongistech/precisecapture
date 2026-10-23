"""OTP login: request + verify, expiry, attempt limit, rate limits, no account enumeration."""

import re
from datetime import timedelta
from typing import Any

import pytest
from django.core import mail
from django.test import Client
from django.utils import timezone

from precisecapture.accounts.models import OtpCode
from tests.factories import PhoneUserFactory, UserFactory

pytestmark = pytest.mark.django_db


def request_code(client: Client, destination: str, **extra: Any) -> Any:
    return client.post(
        "/api/v1/auth/otp/request",
        data={"destination": destination},
        content_type="application/json",
        **extra,
    )


def verify(client: Client, destination: str, code: str, **payload: Any) -> Any:
    return client.post(
        "/api/v1/auth/otp/verify",
        data={"destination": destination, "code": code, **payload},
        content_type="application/json",
    )


def code_from_email() -> str:
    body = str(mail.outbox[-1].body)
    match = re.search(r"\b(\d{6})\b", body)
    assert match, body
    return match.group(1)


def code_from_console(capsys) -> str:
    out = capsys.readouterr().out
    match = re.search(r"\[SMS\] to \+\d+: .*?(\d{6})", out)
    assert match, out
    return match.group(1)


def test_email_otp_round_trip(client):
    UserFactory(email="ama@example.org")
    r = request_code(client, "Ama@Example.org")
    assert r.status_code == 200 and r.json()["expires_in"] == 600
    assert len(mail.outbox) == 1 and mail.outbox[0].to == ["ama@example.org"]
    code = code_from_email()
    r = verify(client, "ama@example.org", code)
    assert r.status_code == 200, r.content
    assert set(r.json()) == {"access_token", "refresh_token", "token_type", "expires_in"}
    me = client.get("/api/v1/me", HTTP_AUTHORIZATION=f"Bearer {r.json()['access_token']}")
    assert me.status_code == 200


def test_phone_otp_goes_through_the_console_sms_backend(client, capsys):
    PhoneUserFactory(phone="+233241234567")
    assert request_code(client, "+233 24 123 4567").status_code == 200
    code = code_from_console(capsys)
    assert verify(client, "+233241234567", code).status_code == 200
    assert mail.outbox == []


def test_unknown_destination_gets_the_same_reply_and_no_message(client):
    r = request_code(client, "nobody@example.org")
    assert r.status_code == 200
    assert mail.outbox == [] and OtpCode.objects.count() == 0
    assert verify(client, "nobody@example.org", "123456").status_code == 401


def test_disabled_account_gets_no_code(client):
    UserFactory(email="off@example.org", status="disabled")
    request_code(client, "off@example.org")
    assert mail.outbox == []


@pytest.mark.parametrize("bad", ["not an address", "0241234567", "++233"])
def test_invalid_destination_is_422(client, bad):
    r = request_code(client, bad)
    assert r.status_code == 422
    assert r.json()["errors"][0]["field"] == "destination"


def test_code_is_single_use(client):
    UserFactory(email="ama@example.org")
    request_code(client, "ama@example.org")
    code = code_from_email()
    assert verify(client, "ama@example.org", code).status_code == 200
    assert verify(client, "ama@example.org", code).status_code == 401


def test_new_request_invalidates_the_previous_code(client):
    UserFactory(email="ama@example.org")
    request_code(client, "ama@example.org")
    first = code_from_email()
    request_code(client, "ama@example.org")
    second = code_from_email()
    assert verify(client, "ama@example.org", first).status_code == 401
    assert verify(client, "ama@example.org", second).status_code == 200


def test_expired_code_is_rejected(client):
    UserFactory(email="ama@example.org")
    request_code(client, "ama@example.org")
    code = code_from_email()
    OtpCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    r = verify(client, "ama@example.org", code)
    assert r.status_code == 401 and "expired" in r.json()["detail"]


def test_five_wrong_attempts_burn_the_code(client, settings):
    settings.OTP_MAX_ATTEMPTS = 5
    UserFactory(email="ama@example.org")
    request_code(client, "ama@example.org")
    code = code_from_email()
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        r = verify(client, "ama@example.org", wrong)
        assert r.status_code == 401
    assert OtpCode.objects.get().attempts == 5
    assert verify(client, "ama@example.org", code).status_code == 401  # correct code, but burnt


def test_rate_limit_per_destination(client, settings):
    settings.RATE_LIMIT_OTP_PER_DESTINATION = "2/3600"
    UserFactory(email="ama@example.org")
    assert request_code(client, "ama@example.org").status_code == 200
    assert request_code(client, "ama@example.org").status_code == 200
    r = request_code(client, "ama@example.org")
    assert r.status_code == 429 and r.json()["type"].endswith("/rate-limited")
    assert len(mail.outbox) == 2


def test_rate_limit_per_ip_covers_many_destinations(client, settings):
    settings.RATE_LIMIT_OTP_PER_IP = "2/3600"
    assert request_code(client, "a@example.org", REMOTE_ADDR="10.0.0.9").status_code == 200
    assert request_code(client, "b@example.org", REMOTE_ADDR="10.0.0.9").status_code == 200
    assert request_code(client, "c@example.org", REMOTE_ADDR="10.0.0.9").status_code == 429
    assert request_code(client, "c@example.org", REMOTE_ADDR="10.0.0.10").status_code == 200


def test_otp_can_bind_a_device(client):
    from tests.factories import DeviceFactory

    user = UserFactory(email="ama@example.org")
    device = DeviceFactory(user=user)
    request_code(client, "ama@example.org")
    r = verify(client, "ama@example.org", code_from_email(), device_id=str(device.id))
    assert r.status_code == 200
    me = client.get("/api/v1/me", HTTP_AUTHORIZATION=f"Bearer {r.json()['access_token']}").json()
    assert me["device_id"] == str(device.id)


def test_well_known_advertises_otp(client):
    assert client.get("/.well-known/precisecapture").json()["auth_methods"] == ["password", "otp"]
