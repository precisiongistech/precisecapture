# Decisions log

Append new decisions at the bottom: date, decision, reason. Don't reopen a decision without Ben's agreement.

| Date | Decision | Reason |
| --- | --- | --- |
| 2026-10-06 | Product model follows GIS Cloud (web-first setup + mobile collector), not Mergin Maps/QField (QGIS-first). | Non-GIS admins must be able to set up projects in a browser; QGIS-grade geometry is delivered inside our own app. |
| 2026-10-06 | Commercial, multi-tenant SaaS. | The business model: sold to organisations across Africa. |
| 2026-10-22 | Product name: **PreciseCapture**. | Ben. |
| 2026-10-22 | Pilot use case: **farm boundary and centroid mapping** (Farmers layer, no geometry + Farms polygon layer), with EUDR-ready exports. | Strong market driver (EU Deforestation Regulation) and a clear test of geometry capture. |
| 2026-10-22 | Backend: **Django 5.2 LTS + GeoDjango + Django Ninja** (not FastAPI). | Built-in auth/admin/ORM/migrations suit a commercial multi-tenant product; the DB router supports bring-your-own-database; Ninja gives typed endpoints and OpenAPI. |
| 2026-10-22 | Cloud: **DigitalOcean** (Managed PostgreSQL + PostGIS, Managed Redis/Valkey, Spaces, DOKS or App Platform). | Ben. Same Docker images ship to self-hosted clients. |
| 2026-10-22 | Mobile: **React Native + Expo dev client, iOS and Android both in the MVP**. Owner: Selorm. | Selorm's stack; both stores needed for reach. |
| 2026-10-22 | Background location: **open source** (expo-location + expo-task-manager) for now. | Avoid licence cost; revisit if the pilot shows tracking gaps, especially on iOS. |
| 2026-10-22 | DevOps owner: **Desmond**. | Ben. |
| 2026-10-22 | Institutions can keep data on their own infrastructure at three levels: Connect (push to their systems), Bring your own storage (their PostGIS + S3), Self-hosted (whole stack). Same app-store app connects to any server via URL or QR. | Data sovereignty requirements across African governments and NGOs. |
| 2026-10-22 | Layers own their attributes; there is no separate "form" object. A layer's attribute list is the form, stored as immutable `LayerSchemaVersion`s. | Simpler mental model for admins: Project → Layer → geometry + attributes + capture rules. |
| 2026-10-22 | Streaming capture interval can go down to **1 m** (options 1, 2, 3, 5, 10 m), with accuracy filter, standstill filter and simplify-on-close; raw track kept. Default 3 m on phone GPS, 1 m with an external GNSS receiver. | Ben's requirement; the filters stop GPS jitter from corrupting boundaries. |
| 2026-10-22 | Multi-tenancy: shared schema with `org_id` + Postgres RLS (FORCE), tenant set per transaction via `app.current_org_id`. | Isolation enforced by the database, fail-closed. |
| 2026-10-22 | Sync ordering: per-project `ProjectSyncState` row locked `FOR UPDATE` during push; `ChangeLog.seq` assigned inside the lock. | Guarantees commit order = seq order so pull cursors never miss rows. |
| 2026-10-22 | IDs: UUIDv7 everywhere; client-generated for features, attachments and sync changes. | Offline creation, idempotent sync, index-friendly ordering. |
| 2026-10-22 | Layers have a project-unique `key` slug; layer schemas and capture profiles reference other layers by key (or `self`); API paths and sync payloads use layer UUIDs. | Keys survive project copies and templates; UUIDs stay the stable API identity. |
| 2026-10-22 | Martin is internal only (role `pc_tiles`); Django authenticates and proxies `/projects/{id}/tiles/...`. | Vector tiles must respect tenancy and project membership. |
| 2026-10-22 | The tenant is set in the Django Ninja auth class inside the request transaction (not middleware); RLS policies use `NULLIF(current_setting(...), '')::uuid`. | Middleware runs outside `ATOMIC_REQUESTS`; pooled connections return `''` after first use. |
| 2026-10-22 | Where SPEC.md and ENGINEERING_NOTES.md / packages/schema / DECISIONS.md differ on implementation detail, the latter win. | One source of truth for implementers; the spec is the product view. |
