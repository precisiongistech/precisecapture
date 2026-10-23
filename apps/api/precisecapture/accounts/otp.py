"""OTP request and verify (ENGINEERING_NOTES.md §6)."""

import hashlib
import hmac
import re
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone

from precisecapture.accounts import messaging
from precisecapture.accounts.models import OtpCode, User, normalise_email, normalise_phone
from precisecapture.accounts.services import _device_for, client_ip
from precisecapture.accounts.tokens import TokenPair, issue_pair
from precisecapture.common import ratelimit
from precisecapture.common.errors import Unauthorized, UnprocessableEntity

E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


def _hash(code: str, destination: str) -> str:
    return hashlib.sha256(f"{destination}:{code}:{settings.SECRET_KEY}".encode()).hexdigest()


def normalise_destination(raw: str) -> str:
    if messaging.is_email(raw):
        value = normalise_email(raw)
    else:
        value = normalise_phone(raw)
        if value and not E164_RE.match(value):
            value = None
    if not value:
        raise UnprocessableEntity(
            "Enter an email address or a phone number",
            errors=[{"field": "destination", "code": "invalid", "message": "Email or E.164 phone"}],
        )
    return value


def request_code(request: HttpRequest, raw_destination: str) -> None:
    """
    Send a code when the destination belongs to an active account. The response is the same
    whether or not the account exists, so this endpoint cannot be used to enumerate users.
    """
    destination = normalise_destination(raw_destination)
    ratelimit.hit("otp:dest", destination, settings.RATE_LIMIT_OTP_PER_DESTINATION)
    ratelimit.hit("otp:ip", client_ip(request), settings.RATE_LIMIT_OTP_PER_IP)

    user = User.objects.by_identifier(destination)
    if user is None or not user.is_active:
        return

    code = f"{secrets.randbelow(10**6):06d}"
    now = timezone.now()
    with transaction.atomic():
        OtpCode.objects.filter(destination=destination, consumed_at__isnull=True).update(
            consumed_at=now
        )
        OtpCode.objects.create(
            destination=destination,
            code_hash=_hash(code, destination),
            expires_at=now + timedelta(seconds=settings.OTP_TTL_SECONDS),
            requested_ip=client_ip(request),
        )
    messaging.send_code(destination, code, ttl_minutes=max(1, settings.OTP_TTL_SECONDS // 60))


def verify_code(
    request: HttpRequest, raw_destination: str, code: str, device_id: uuid.UUID | None
) -> TokenPair:
    destination = normalise_destination(raw_destination)
    failure: str | None = None
    with transaction.atomic():
        otp = (
            OtpCode.objects.select_for_update()
            .filter(destination=destination, consumed_at__isnull=True)
            .order_by("-created_at")
            .first()
        )
        if otp is None or not otp.is_usable:
            failure = "Code expired or not requested. Request a new code."
        elif not hmac.compare_digest(otp.code_hash, _hash(code.strip(), destination)):
            otp.attempts += 1
            remaining = settings.OTP_MAX_ATTEMPTS - otp.attempts
            if remaining <= 0:
                otp.consumed_at = timezone.now()  # burnt: a new code must be requested
                failure = "Too many wrong codes. Request a new code."
            else:
                failure = f"Wrong code. {remaining} attempt(s) left."
            otp.save(update_fields=["attempts", "consumed_at", "updated_at"])
        else:
            otp.consumed_at = timezone.now()
            otp.save(update_fields=["consumed_at", "updated_at"])
    # Raised outside the savepoint so the attempt count / burn survives the error response.
    if failure is not None:
        raise Unauthorized(failure)

    user = User.objects.by_identifier(destination)
    if user is None or not user.is_active:
        raise Unauthorized("Account not found or disabled")
    device = _device_for(user, device_id)
    user.mark_login()
    return issue_pair(user, device)
