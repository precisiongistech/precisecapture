"""
Database router enforcing which connection may run migrations.

`pc_app` (the `default` alias) owns no tables and must never run DDL. Migrations
run only on `settings.MIGRATION_DATABASE_ALIAS` (`migrations` = pc_owner in dev
and prod; `default` under pytest, where `default` already is pc_owner).

Reads and writes stay on `default` (tenant models get a bring-your-own-storage
router in a later milestone, ENGINEERING_NOTES.md §1). The platform admin picks the
`platform` alias explicitly per query (common/admin.py) rather than through this router.
"""

from typing import Any

from django.conf import settings


class MigrationsRouter:
    def db_for_read(self, model: type, **hints: Any) -> str | None:
        return None

    def db_for_write(self, model: type, **hints: Any) -> str | None:
        return None

    def allow_relation(self, obj1: Any, obj2: Any, **hints: Any) -> bool | None:
        return None

    def allow_migrate(
        self, db: str, app_label: str, model_name: str | None = None, **hints: Any
    ) -> bool:
        return db == settings.MIGRATION_DATABASE_ALIAS
