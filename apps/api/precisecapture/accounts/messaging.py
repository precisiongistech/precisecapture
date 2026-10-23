"""
Outbound messages: SMS behind an interface (console in dev, a provider later) and email
through Django's configured backend (Mailpit in dev).
"""

import logging
from typing import Protocol

from django.conf import settings
from django.core.mail import send_mail
from django.utils.module_loading import import_string

log = logging.getLogger(__name__)


class SmsBackend(Protocol):
    def send(self, to: str, body: str) -> None: ...


class ConsoleSmsBackend:
    """Logs the message. Dev and test only."""

    def send(self, to: str, body: str) -> None:
        log.info("SMS to %s: %s", to, body)
        print(f"[SMS] to {to}: {body}")  # noqa: T201 - console backend by design


_BACKENDS: dict[str, str] = {
    "console": "precisecapture.accounts.messaging.ConsoleSmsBackend",
}


def sms_backend() -> SmsBackend:
    name = settings.SMS_BACKEND
    path = _BACKENDS.get(name, name)  # a dotted path is accepted for providers added later
    backend: SmsBackend = import_string(path)()
    return backend


def is_email(destination: str) -> bool:
    return "@" in destination


def send_code(destination: str, code: str, ttl_minutes: int) -> None:
    body = (
        f"Your {settings.INSTANCE_NAME} login code is {code}. It expires in {ttl_minutes} minutes."
    )
    if is_email(destination):
        send_mail(
            subject=f"{settings.INSTANCE_NAME} login code",
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[destination],
        )
    else:
        sms_backend().send(destination, body)
