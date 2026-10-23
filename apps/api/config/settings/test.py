"""
Settings for pytest.

`default` points at pc_owner here, so pytest-django can create the test database
(pc_owner has CREATEDB and the test DB is cloned from template1, which already has
PostGIS and the role grants). Migrations therefore run on `default` in tests.
Isolation tests `SET ROLE pc_app` through the `as_app_role` fixture to prove RLS
really applies to the application role.
"""

import copy

from .base import *
from .base import env

# Copy, never mutate base.DATABASES in place (other modules import it too).
DATABASES = copy.deepcopy(DATABASES)

DEBUG = False
ALLOWED_HOSTS = ["*"]
SECRET_KEY = "test-only-not-secret-but-long-enough-for-hmac-sha256-keys"
JWT_SIGNING_KEY = SECRET_KEY

DATABASES["default"] = {
    **env.db_url("MIGRATION_DATABASE_URL"),
    "ATOMIC_REQUESTS": True,
    "CONN_MAX_AGE": 60,  # a reused connection is part of the tenant fail-closed test
    "CONN_HEALTH_CHECKS": True,
}
# The other aliases reuse the test database created for `default`.
DATABASES["migrations"]["TEST"] = {"MIRROR": "default"}
DATABASES["platform"]["TEST"] = {"MIRROR": "default"}
MIGRATION_DATABASE_ALIAS = "default"

INSTALLED_APPS = [*INSTALLED_APPS, "tests.testapp"]

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Celery tasks run inline unless a test overrides this (see tests/test_celery.py).
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
STORAGES["default"] = {"BACKEND": "django.core.files.storage.InMemoryStorage"}
