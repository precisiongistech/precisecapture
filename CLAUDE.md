# PreciseCapture: guide for Claude Code

You are working on **PreciseCapture**, a commercial GIS field data collection platform (web + mobile) built by Precision GIS and Technology Consultancy Ltd., Accra, Ghana. The goal is to become the household name for field data collection across Africa. The product follows the GIS Cloud model: admins set everything up in the browser, collectors capture on iOS/Android phones (online or offline), and data syncs back to a live web map, or to the client's own servers.

**Read these before any non-trivial work:**

- `docs/SPEC.md`: the full product and technical spec (source of truth for behaviour)
- `docs/BUILD_PLAN.md`: milestones, tasks and acceptance criteria, in order
- `docs/DECISIONS.md`: decisions already made; do not reopen them without asking
- `docs/ENGINEERING_NOTES.md`: the hard parts (tenancy/RLS, sync ordering, geometry) and how to do them
- `packages/schema/`: the shared contract (JSON Schemas for layer schemas, capture profiles and sync wire formats, plus examples). Code must conform to it.

**Precedence:** where `docs/SPEC.md` disagrees with `ENGINEERING_NOTES.md`, `packages/schema/` or `DECISIONS.md` on implementation detail, those three win. Point out the discrepancy so Ben can fix the spec.

---

## Who owns what

| Area | Owner | Notes |
| --- | --- | --- |
| `apps/api` (Django) and `apps/web` (React) | Ben | Your main working area in this repo |
| `apps/mobile` (React Native, iOS + Android) | Selorm | Do NOT edit unless Ben explicitly asks |
| `infra/` deploy, CI/CD, DigitalOcean | Desmond | You may add dev tooling (docker-compose for local dev); production infra changes need Ben's approval |
| `packages/schema`, OpenAPI contract | Shared | Changes affect the mobile app: flag every breaking change loudly |

## Stack (decided)

- **API:** Python 3.12, Django 5.2 LTS + GeoDjango, **Django Ninja** (typed endpoints, OpenAPI 3.1), psycopg 3, Celery + Redis, django-storages (S3-compatible), PyJWT, `uuid-utils` (UUIDv7).
- **Database:** PostgreSQL 16 + PostGIS 3.4+. Multi-tenant shared schema with `org_id` + Postgres row-level security.
- **Storage:** DigitalOcean Spaces in production, MinIO locally. Always via django-storages / boto3; never local paths.
- **Tiles:** Martin (MVT from PostGIS), internal only. Django authenticates and proxies tile requests. PMTiles for offline basemap packs.
- **Web:** React + TypeScript + Vite, MapLibre GL JS, TanStack Query + TanStack Router, Zod, Tailwind CSS. API types generated from OpenAPI (`openapi-typescript`).
- **Mobile (Selorm):** React Native + Expo dev client, MapLibre RN, op-sqlite. Consumes `packages/schema` and the OpenAPI contract.
- **Hosting:** DigitalOcean (Managed Postgres, Managed Redis/Valkey, Spaces, DOKS/App Platform). Everything also ships as Docker images for self-hosted clients.
- **Tooling:** `uv` (Python deps), `ruff` (lint + format), `mypy` + `django-stubs`, `pytest` + `pytest-django` + `factory_boy`; `pnpm` workspaces (Node 22), `eslint`, `prettier`, `vitest`, Playwright for web e2e.

## Repository layout

```
precisecapture/
├── CLAUDE.md                  ← this file
├── README.md
├── docs/                      ← spec, build plan, decisions, engineering notes
├── apps/
│   ├── api/                   ← Django project (Ben)
│   │   ├── config/            ← settings (base, dev, test, prod), urls, celery, asgi/wsgi
│   │   ├── precisecapture/    ← Django apps (see below)
│   │   ├── tests/
│   │   └── pyproject.toml
│   ├── web/                   ← React admin + data web app (Ben)
│   └── mobile/                ← React Native app (Selorm) – hands off
├── packages/
│   ├── schema/                ← JSON Schemas, TS types, expression evaluator, test vectors (shared)
│   └── api-client/            ← generated TS types/client from openapi.json
├── contract/
│   └── openapi.json           ← exported from Django Ninja, committed, reviewed in PRs
└── infra/
    ├── docker/                ← docker-compose.dev.yml (Postgres/PostGIS, Redis, MinIO, Martin, Mailpit)
    └── deploy/                ← Desmond's area
```

Django apps under `apps/api/precisecapture/`:

| App | Contents |
| --- | --- |
| `common` | Base models (UUIDv7 PK, timestamps), RFC 9457 error handling, pagination, permissions helpers, tenant context |
| `accounts` | Custom `User` (email or phone login), JWT auth, OTP login, `Device` |
| `orgs` | `Organisation`, `Membership`, roles, tenancy middleware, RLS migrations, plan limits |
| `projects` | `Project`, `ProjectMember`, `Layer`, `LayerSchemaVersion`, `LayerTemplate`, capture profiles, project bundle |
| `features` | `Feature`, `FeatureHistory`, `FeatureRelation`, `RawTrack`, `VertexMeta`, review workflow, spatial computations |
| `sync` | `ChangeLog`, `ProjectSyncState`, `AppliedChange`, `SyncCursor`, `Conflict`, push/pull services |
| `attachments` | `Attachment`, presigned multipart uploads, signed downloads |
| `exports` | Celery export jobs (CSV, XLSX, GeoJSON, EUDR GeoJSON, SHP, KML, GPKG) |
| `integrations` | API keys, webhooks, connectors (later milestones) |

## Commands (create these in M0 and keep them working)

```bash
make dev-up          # start Postgres/PostGIS, Redis, MinIO, Martin, Mailpit (docker compose)
make dev-down
make api-install     # uv sync
make api-migrate     # python manage.py migrate --database=migrations  (runs as pc_owner)
make api-run         # runserver on :8000
make api-worker      # celery worker
make api-test        # pytest (must pass before every commit)
make api-lint        # ruff check + ruff format --check + mypy
make contract        # export OpenAPI to contract/openapi.json and regenerate packages/api-client
make mock            # Prism mock server of the contract on :4010 (for the mobile app)
make web-dev         # pnpm --filter web dev
make web-test        # vitest
make schema-test     # validate examples against JSON Schemas; run expression test vectors (TS + Python)
```

## Non-negotiable rules

1. **Tenant isolation.** Every tenant-owned table has `org_id` and an RLS policy. Every request and every Celery task runs inside `tenant_context(org_id)`. Never query tenant data outside it. Every new tenant table needs an isolation test proving org A cannot read org B. See `docs/ENGINEERING_NOTES.md §1`.
2. **Contract first.** `packages/schema` and `contract/openapi.json` are the contract with the mobile app. Any change to them must be backward compatible (new fields optional with defaults), or be listed under a **BREAKING CHANGE** heading in the commit message and PR description so Ben can warn Selorm.
3. **Client-generated IDs.** Features, attachments and sync changes use UUIDs created on the device (UUIDv7). The server never reassigns them. All sync writes are idempotent on `change_id`.
4. **No hard-coded hosts, buckets or secrets.** Everything comes from environment variables (`django-environ`). The same image must run on our DigitalOcean cloud and on a client's own server.
5. **Geometry on the wire is GeoJSON in EPSG:4326.** Areas and lengths are computed on the geography type (metres, hectares), never in degrees.
6. **Soft deletes only** for features (`deleted=true`), so deletes sync.
7. **Every write is audited**: who, when, which device, plus `FeatureHistory` for features.
8. **Tests are part of the task.** No feature is done without tests: unit tests for services, API tests for endpoints, isolation tests for tenant tables, and sync scenario tests.
9. **Do not touch `apps/mobile`** or production infra without Ben's explicit go-ahead.
10. **Ask before deviating** from `docs/DECISIONS.md` or adding a heavyweight dependency. Propose; don't silently swap.

## Code conventions

- **Python:**
  - type hints everywhere
  - business logic in `services.py` (not in views or models)
  - Ninja routers in `api.py` per app
  - Pydantic schemas in `schemas.py`
  - Celery tasks in `tasks.py`
- **Errors:** RFC 9457 problem JSON (`type`, `title`, `status`, `detail`, `errors[]`), via one exception handler in `common`.
- **API paths:** `/api/v1/...`, plural nouns, cursor pagination (`?cursor=&limit=`), ISO 8601 UTC timestamps, `Idempotency-Key` header on non-sync writes.
- **Migrations:** one logical change per migration; RLS policies created in migrations with `RunSQL` (with reverse SQL).
- **Web:**
  - feature folders (`src/features/projects/...`), server state in TanStack Query, forms with React Hook Form + Zod
  - map code isolated in `src/map/`
  - no `any`
- **Commits:** Conventional Commits (`feat(sync): ...`, `fix(api): ...`). Small commits, one task each. Work on a branch per milestone (`m3-projects-layers`), open a PR for Ben to review.
- **Docs:** when you make a design decision, append it to `docs/DECISIONS.md` (date, decision, reason).

## How to work in this repo

1. At the start of a milestone, read the milestone in `docs/BUILD_PLAN.md`, then **propose a short plan** (files, models, endpoints, tests) and wait for Ben's OK.
2. Implement task by task. After each task: run `make api-lint api-test` (and `web-test` / `schema-test` where relevant), then commit.
3. When the contract changes, run `make contract` and summarise the diff of `contract/openapi.json` for Ben.
4. At the end of a milestone, walk the acceptance criteria one by one and report pass/fail with evidence (test names, commands run).
5. If something in the spec is ambiguous, ask a concrete question with a recommended answer rather than guessing.

## Glossary

- **Organisation (org):** a paying tenant (e.g. a cocoa exporter, an NGO, a district assembly).
- **Project:** a collection of layers, members and an offline area (e.g. "Western North Farm Mapping").
- **Layer:** one feature type with a geometry type (`point`, `line`, `polygon`, `none`) and attributes. It has a UUID (used in API paths and sync) and a project-unique `key` slug (used for references inside layer schemas and capture profiles).
- **Layer schema:** the layer's attribute list. It is also the form the collector fills in. Versioned (`LayerSchemaVersion`).
- **Capture profile:** per-layer JSON rules for how geometry is captured (streaming interval, auto-close, GPS limits, snapping, topology). Resolves org default → project → layer → collector toggle (unless `locked`).
- **Project bundle:** everything a phone downloads to work offline for a project.
- **Outbox:** the phone's queue of local changes awaiting sync.
- **server_seq:** the per-project, gap-free, commit-ordered sequence used for pull cursors.
- **Pilot:** farm boundary + centroid mapping (Farmers layer with no geometry + Farms polygon layer), EUDR-ready exports.
