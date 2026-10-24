"""Local development settings."""

from .base import *
from .base import env

DEBUG = env.bool("DJANGO_DEBUG", default=True)
# 0.0.0.0 is what the runserver banner prints; the API answers on it in dev only.
ALLOWED_HOSTS = [
    *env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"]),
    "0.0.0.0",
    "[::1]",
]
