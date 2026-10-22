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

```bash
cp .env.example .env
make dev-up          # Postgres/PostGIS, Redis, MinIO, Martin, Mailpit
make api-install
make api-migrate
make api-run         # http://localhost:8000/api/v1/docs
make web-dev         # http://localhost:5173
```

## Documentation

- `docs/SPEC.md`: product and technical spec
- `docs/BUILD_PLAN.md`: milestones and acceptance criteria
- `docs/ENGINEERING_NOTES.md`: tenancy, sync, geometry, attachments, auth
- `docs/DECISIONS.md`: decision log
- `CLAUDE.md`: working rules for Claude Code (useful for humans too)
