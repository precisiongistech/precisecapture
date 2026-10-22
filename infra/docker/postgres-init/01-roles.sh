#!/bin/bash
# Creates the four PreciseCapture database roles for local development.
# See docs/ENGINEERING_NOTES.md §1 (multi-tenancy with row-level security).
#   pc_owner    – owns tables, used only to run migrations
#   pc_app      – used by Django web + Celery; DML only; NO BYPASSRLS
#   pc_platform – platform-admin jobs only; BYPASSRLS
#   pc_tiles    – Martin tile server; SELECT only on tile functions; NO BYPASSRLS
set -euo pipefail

# PostGIS in template1 so every new database (incl. the pytest test DB) already has it.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname template1 <<-EOSQL
  CREATE EXTENSION IF NOT EXISTS postgis;
  CREATE EXTENSION IF NOT EXISTS pg_trgm;
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
  CREATE EXTENSION IF NOT EXISTS postgis;
  CREATE EXTENSION IF NOT EXISTS pg_trgm;

  DO \$\$
  BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'pc_owner') THEN
      CREATE ROLE pc_owner LOGIN PASSWORD '${PC_OWNER_PASSWORD}';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'pc_app') THEN
      CREATE ROLE pc_app LOGIN PASSWORD '${PC_APP_PASSWORD}' NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'pc_platform') THEN
      CREATE ROLE pc_platform LOGIN PASSWORD '${PC_PLATFORM_PASSWORD}' BYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'pc_tiles') THEN
      CREATE ROLE pc_tiles LOGIN PASSWORD '${PC_TILES_PASSWORD}' NOBYPASSRLS;
    END IF;
  END
  \$\$;

  GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO pc_owner, pc_app, pc_platform, pc_tiles;
  -- pc_owner can SET ROLE pc_app so tests prove RLS applies to the app role
  GRANT pc_app TO pc_owner;
  GRANT ALL ON SCHEMA public TO pc_owner;
  GRANT USAGE ON SCHEMA public TO pc_app, pc_platform, pc_tiles;
  -- pc_tiles gets EXECUTE on specific tile functions via migrations (M5), nothing by default.

  -- Tables created later by pc_owner (migrations) are automatically usable by the app roles.
  ALTER DEFAULT PRIVILEGES FOR ROLE pc_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO pc_app, pc_platform;
  ALTER DEFAULT PRIVILEGES FOR ROLE pc_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO pc_app, pc_platform;
  ALTER DEFAULT PRIVILEGES FOR ROLE pc_owner IN SCHEMA public
    GRANT EXECUTE ON FUNCTIONS TO pc_app, pc_platform;

  -- Test database for pytest (pytest-django creates test_<name>; allow pc_owner to create DBs)
  ALTER ROLE pc_owner CREATEDB;
EOSQL
