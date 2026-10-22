# PreciseCapture

PreciseCapture is a GIS field data collection platform for Africa. Admins set up projects in a browser, field teams capture data offline on iOS and Android, and the data syncs back to a live web map or to the client's own servers.

| Part | Path | Owner |
| --- | --- | --- |
| API (Django + GeoDjango + Django Ninja) | `apps/api` | Ben |
| Web app (React + MapLibre) | `apps/web` | Ben |
| Mobile app (React Native, iOS + Android) | `apps/mobile` | Selorm |
| Shared schemas and expression language | `packages/schema` | Shared |
| API contract (OpenAPI) | `contract/openapi.json` | Shared |
| Deployment (DigitalOcean) | `infra/deploy` | Desmond |

## Quick start (local)

Prerequisites: Docker Desktop, [uv](https://docs.astral.sh/uv/), Node 22 + pnpm, and GDAL/GEOS/PROJ
(`brew install gdal geos proj` on macOS; `apt install gdal-bin libgdal-dev libgeos-dev libproj-dev` on Debian/Ubuntu).

```bash
cp .env.example .env
make dev-up          # Postgres/PostGIS, Redis, MinIO, Martin, Mailpit
make api-install
make api-migrate
make api-run         # http://localhost:8000/api/v1/docs
make web-dev         # http://localhost:5173
make help            # every target
```

If a default port is already taken on your machine (for example a native PostgreSQL on 5432), change
`DB_PORT` (and the matching `*_DATABASE_URL`s) or the other `*_PORT` variables in `.env`; the
compose file reads them. `.env` files take comment lines only, not inline comments.

Tests run against the dockerised database (`make api-test`). Tests marked `integration` also need
Redis from `make dev-up`.

## Documentation

- `docs/SPEC.md`: product and technical spec
- `docs/BUILD_PLAN.md`: milestones and acceptance criteria
- `docs/ENGINEERING_NOTES.md`: tenancy, sync, geometry, attachments, auth
- `docs/DECISIONS.md`: decision log
- `CLAUDE.md`: working rules for Claude Code (useful for humans too)
