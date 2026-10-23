"""
Row-level security helpers for migrations (ENGINEERING_NOTES.md §1).

    operations = [
        migrations.CreateModel(...),
        enable_rls("features_feature"),
    ]

The policy uses NULLIF so an unset or cleared setting ('' on a reused pooled connection)
yields NULL and therefore matches no rows: fail closed, never an error.
"""

from django.db import migrations

POLICY_NAME = "tenant_isolation"
_PREDICATE = "org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid"


def rls_sql(table: str) -> str:
    return (
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;\n"
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;\n"
        f"CREATE POLICY {POLICY_NAME} ON {table}\n"
        f"  USING ({_PREDICATE})\n"
        f"  WITH CHECK ({_PREDICATE});"
    )


def rls_reverse_sql(table: str) -> str:
    return (
        f"DROP POLICY IF EXISTS {POLICY_NAME} ON {table};\n"
        f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;\n"
        f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;"
    )


def enable_rls(table: str) -> migrations.RunSQL:
    """A reversible migration operation enabling the tenant policy on `table`."""
    return migrations.RunSQL(sql=rls_sql(table), reverse_sql=rls_reverse_sql(table))
