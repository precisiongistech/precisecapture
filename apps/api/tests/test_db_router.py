"""Migrations run only on the owner connection (ENGINEERING_NOTES.md §1)."""

from config.db_router import MigrationsRouter


def test_migrations_only_on_configured_alias(settings):
    settings.MIGRATION_DATABASE_ALIAS = "migrations"
    router = MigrationsRouter()
    assert router.allow_migrate("migrations", "common") is True
    assert router.allow_migrate("default", "common") is False
    assert router.allow_migrate("platform", "common") is False


def test_test_settings_migrate_on_default_which_is_the_owner(settings):
    # Under pytest `default` is pc_owner, so the test database can be migrated.
    assert settings.MIGRATION_DATABASE_ALIAS == "default"
    assert settings.DATABASES["default"]["USER"] == "pc_owner"


def test_prod_shaped_aliases_use_the_right_roles():
    from config.settings import base

    assert base.DATABASES["default"]["USER"] == "pc_app"
    assert base.DATABASES["default"]["ATOMIC_REQUESTS"] is True
    assert base.DATABASES["migrations"]["USER"] == "pc_owner"
    assert base.DATABASES["platform"]["USER"] == "pc_platform"
    assert base.MIGRATION_DATABASE_ALIAS == "migrations"
