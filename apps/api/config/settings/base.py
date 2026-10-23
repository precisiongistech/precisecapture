"""
Base settings shared by every environment.

Everything that differs between deployments comes from environment variables
(django-environ). The same image must run on our DigitalOcean cloud and on a
client's own server, so nothing here names a host, bucket or secret.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # apps/api
REPO_ROOT = BASE_DIR.parent.parent

env = environ.Env()
# A local .env at the repo root is read when present (never committed; see .gitignore).
environ.Env.read_env(REPO_ROOT / ".env")

# --- Core -------------------------------------------------------------------

SECRET_KEY = env.str("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])

PUBLIC_BASE_URL = env.str("PUBLIC_BASE_URL", default="http://localhost:8000")
INSTANCE_NAME = env.str("INSTANCE_NAME", default="PreciseCapture")
INSTANCE_LOGO_URL = env.str("INSTANCE_LOGO_URL", default="") or None

# The contract version advertised to clients (bumped with contract/openapi.json).
API_VERSION = "1"
# Oldest mobile app version this server accepts.
MIN_APP_VERSION = env.str("MIN_APP_VERSION", default="0.1.0")
# Auth methods the login screen may offer. Extended in M2 (otp, qr).
AUTH_METHODS: list[str] = ["password", "otp"]

PLATFORM_ADMIN_ENABLED = env.bool("PLATFORM_ADMIN_ENABLED", default=False)

# The shared contract (packages/schema): JSON Schemas, examples and test vectors.
# Read from the monorepo in development; the production image copies the folder.
SCHEMA_DIR = env.str("SCHEMA_DIR", default=str(REPO_ROOT / "packages" / "schema"))

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.gis",
    "ninja",  # management command export_openapi_schema (make contract)
    "precisecapture.common",
    "precisecapture.accounts",
    "precisecapture.orgs",
    "precisecapture.projects",
    "precisecapture.features",
    "precisecapture.sync",
    "precisecapture.attachments",
]

AUTH_USER_MODEL = "accounts.User"

if PLATFORM_ADMIN_ENABLED:
    # Internal-only deployment: Django admin for platform staff, reading/writing through the
    # `platform` alias (see common/admin.py). Never enabled on the public web process.
    INSTALLED_APPS += [
        "django.contrib.admin",
        "django.contrib.sessions",
        "django.contrib.messages",
        "django.contrib.staticfiles",
    ]
    STATIC_URL = "static/"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Clears the tenant contextvar after each request. The tenant itself is set by the Ninja
    # auth class inside the request transaction (ENGINEERING_NOTES.md §1), not here.
    "precisecapture.common.middleware.TenantContextResetMiddleware",
    "precisecapture.common.middleware.IdempotencyMiddleware",
]
if PLATFORM_ADMIN_ENABLED:
    MIDDLEWARE += [
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
    ]
    SESSION_ENGINE = "django.contrib.sessions.backends.cache"

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

# --- Databases (ENGINEERING_NOTES.md §1) ------------------------------------
#
#   default     pc_app      web + Celery, DML only, no BYPASSRLS, ATOMIC_REQUESTS
#   migrations  pc_owner    `manage.py migrate --database=migrations` only
#   platform    pc_platform explicit platform-admin management commands only
#
# A router (config.db_router) allows migrations only on MIGRATION_DATABASE_ALIAS.

DB_CONN_MAX_AGE = env.int("DB_CONN_MAX_AGE", default=60)

DATABASES = {
    "default": {
        **env.db_url("DATABASE_URL"),
        "ATOMIC_REQUESTS": True,
        "CONN_MAX_AGE": DB_CONN_MAX_AGE,
        "CONN_HEALTH_CHECKS": True,
    },
    "migrations": {
        **env.db_url("MIGRATION_DATABASE_URL"),
        "CONN_MAX_AGE": 0,
    },
    "platform": {
        **env.db_url("PLATFORM_DATABASE_URL"),
        "CONN_MAX_AGE": 0,
    },
}
MIGRATION_DATABASE_ALIAS = "migrations"
DATABASE_ROUTERS = ["config.db_router.MigrationsRouter"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# GeoDjango native libraries. Linux images find them by name; on macOS ctypes does not search
# the Homebrew prefix, so fall back to the usual locations unless an explicit path is given.
def _native_lib(env_name: str, filename: str) -> str | None:
    explicit: str = env.str(env_name, default="")
    if explicit:
        return explicit
    for prefix in ("/opt/homebrew/lib", "/usr/local/lib"):
        candidate = Path(prefix) / filename
        if candidate.exists():
            return str(candidate)
    return None


GDAL_LIBRARY_PATH = _native_lib("GDAL_LIBRARY_PATH", "libgdal.dylib")
GEOS_LIBRARY_PATH = _native_lib("GEOS_LIBRARY_PATH", "libgeos_c.dylib")

# --- Auth -------------------------------------------------------------------

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

JWT_SIGNING_KEY = env.str("JWT_SIGNING_KEY", default=SECRET_KEY)
JWT_ACCESS_TTL_SECONDS = env.int("JWT_ACCESS_TTL_SECONDS", default=900)
JWT_REFRESH_TTL_DAYS = env.int("JWT_REFRESH_TTL_DAYS", default=30)
OTP_TTL_SECONDS = env.int("OTP_TTL_SECONDS", default=600)
OTP_MAX_ATTEMPTS = env.int("OTP_MAX_ATTEMPTS", default=5)
SMS_BACKEND = env.str("SMS_BACKEND", default="console")

# Rate limits: "<count>/<seconds>". Enforced with the cache (Redis in dev/prod).
RATE_LIMIT_LOGIN_PER_IDENTIFIER = env.str("RATE_LIMIT_LOGIN_PER_IDENTIFIER", default="10/900")
RATE_LIMIT_LOGIN_PER_IP = env.str("RATE_LIMIT_LOGIN_PER_IP", default="50/900")
RATE_LIMIT_OTP_PER_DESTINATION = env.str("RATE_LIMIT_OTP_PER_DESTINATION", default="5/3600")
RATE_LIMIT_OTP_PER_IP = env.str("RATE_LIMIT_OTP_PER_IP", default="20/3600")

# --- Celery / Redis / cache --------------------------------------------------

REDIS_URL = env.str("REDIS_URL", default="redis://localhost:6379/0")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_PREFIX": "pc",
    }
}
CELERY_BROKER_URL = env.str("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env.str("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = "UTC"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 60 * 30
CELERY_WORKER_SEND_TASK_EVENTS = True
CELERY_TASK_ALWAYS_EAGER = False

# --- Object storage (django-storages / boto3; never local paths) ------------

S3_ENDPOINT_URL = env.str("S3_ENDPOINT_URL", default="")
S3_BUCKET = env.str("S3_BUCKET", default="")
S3_REGION = env.str("S3_REGION", default="us-east-1")
S3_PRESIGN_EXPIRY_SECONDS = env.int("S3_PRESIGN_EXPIRY_SECONDS", default=900)

STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": S3_BUCKET,
            "endpoint_url": S3_ENDPOINT_URL or None,
            "region_name": S3_REGION,
            "access_key": env.str("S3_ACCESS_KEY_ID", default=""),
            "secret_key": env.str("S3_SECRET_ACCESS_KEY", default=""),
            "file_overwrite": False,
            "default_acl": None,
            "querystring_expire": S3_PRESIGN_EXPIRY_SECONDS,
        },
    },
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# --- Email ------------------------------------------------------------------

EMAIL_CONFIG = env.email_url("EMAIL_URL", default="consolemail://")
vars().update(EMAIL_CONFIG)
DEFAULT_FROM_EMAIL = env.str("DEFAULT_FROM_EMAIL", default="noreply@precisecapture.local")

# --- Tiles ------------------------------------------------------------------

MARTIN_URL = env.str("MARTIN_URL", default="http://localhost:3000")

# --- I18N / time ------------------------------------------------------------

LANGUAGE_CODE = "en"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --- Logging ----------------------------------------------------------------

LOG_LEVEL = env.str("LOG_LEVEL", default="INFO")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "default"},
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django": {"level": LOG_LEVEL, "propagate": True},
        "precisecapture": {"level": LOG_LEVEL, "propagate": True},
    },
}

SENTRY_DSN = env.str("SENTRY_DSN", default="")
