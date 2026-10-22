# Engineering notes: the hard parts

These are the parts of PreciseCapture that are easy to get subtly wrong. Follow these designs unless Ben approves a change (record it in `DECISIONS.md`).

---

## 1. Multi-tenancy with Postgres row-level security

**Goal:** a bug in a query must not be able to leak one organisation's data to another.

### Database roles and Django connections

| Role | Django alias | Used by | Rights |
| --- | --- | --- | --- |
| `pc_owner` | `migrations` | `migrate` only (and creating the test DB) | Owns all tables; `CREATEDB` locally |
| `pc_app` | `default` | Django web + Celery | SELECT/INSERT/UPDATE/DELETE only, **`NOBYPASSRLS`**, not a table owner |
| `pc_platform` | `platform` | Explicit platform-admin management commands only (billing, support) | `BYPASSRLS` |
| `pc_tiles` | (none; used by Martin) | Martin tile server | SELECT only on the tile functions/views, **`NOBYPASSRLS`** |

- A DB router allows migrations **only** on the `migrations` alias. `make api-migrate` runs `python manage.py migrate --database=migrations`.
- `pc_owner` is granted membership of `pc_app` (`GRANT pc_app TO pc_owner`), so tests can `SET ROLE pc_app` and prove RLS really applies.
- **Test database:**
  - pytest creates it as `pc_owner`, via test settings in which `default` points at `pc_owner`.
  - PostGIS, the schema grants and the `ALTER DEFAULT PRIVILEGES` for `pc_app`/`pc_platform` are applied to `template1` by the init script (default privileges are per database), so the new test DB already carries them and `SET ROLE pc_app` can read the tables migrations create.
  - Isolation tests then run their queries after `SET ROLE pc_app`. Provide a pytest fixture `as_app_role` that does this.

### Policies

Apply this to every tenant table, i.e. anything with `org_id` (see the table list below):

```sql
ALTER TABLE features_feature ENABLE ROW LEVEL SECURITY;
ALTER TABLE features_feature FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON features_feature
  USING      (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
```

**Why `NULLIF`:** after a connection has used `set_config(..., true)` once, later transactions on that pooled connection see `''`, not NULL. A bare `::uuid` cast would then raise an error instead of returning no rows. With `NULLIF`, the unset case is always NULL, so **no rows match**. That is the fail-closed behaviour we want. Write a test for it on a reused connection (`CONN_MAX_AGE > 0`).

Write a helper so each app's migration adds the policy in one line, e.g. `enable_rls("features_feature")`, returning a `RunSQL` with reverse SQL.

### Setting the tenant per request

- `ATOMIC_REQUESTS = True`. All tenant endpoints are **sync** views. Async views are not wrapped in the request transaction.
- **Do not set the tenant in Django middleware.** Middleware runs outside the `ATOMIC_REQUESTS` transaction, so a transaction-local setting there has no effect.
- **Set it in the Django Ninja auth class instead** (`common/auth.py`), which runs inside the view, and therefore inside the transaction:
  1. Verify the JWT.
  2. Read the `X-Org-Id` header and check `Membership`.
  3. Run `SELECT set_config('app.current_org_id', %s, true)`.
  4. Store the org on `request.org` and in a contextvar.
- `tenant_context(org_id)` in `common/tenancy.py`, a context manager that does `transaction.atomic()` + `set_config`, is used by Celery tasks, management commands and tests.
- **Belt and braces:** tenant models use a default manager that filters by the contextvar org. RLS is the guarantee; the manager makes the intent visible in code.
- **Endpoints that span orgs** (`GET /me`, `GET /me/projects`) loop over the user's memberships and run one `tenant_context(org)` per org. They never use the `platform` alias.

### Which tables are tenant-scoped

| Tenant-scoped (own `org_id` column + RLS) | Global (application permissions only) |
| --- | --- |
| Projects and setup: `project`, `project_member`, `layer`, `layer_schema_version`, `layer_template`, `basemap_pack`, `task` | `user` |
| Feature data: `feature`, `feature_history`, `feature_relation`, `raw_track`, `vertex_meta`, `attachment`, `review` | `organisation` |
| Sync: `project_sync_state`, `change_log`, `applied_change`, `sync_cursor`, `conflict` | `membership` |
| Integrations and jobs: `export_job`, `webhook`, `api_key`, `connector` | `device`, `refresh_token` (owned by the user, scoped by user id) |
| | `otp_code` |
| | `invitation` (looked up by token; carries `org_id` but is resolved before a tenant is known) |

- Copy `org_id` onto **every** tenant row, even when it could be derived from a parent. RLS policies must not join.
- Django admin for platform staff is **not** served by the public web process. It runs only when `PLATFORM_ADMIN_ENABLED=true`, on an internal-only deployment, using the `platform` alias. Record this exception in `DECISIONS.md` in M2.

### Required tests

- **For each tenant model:**
  - create rows in org A and org B
  - as `pc_app` inside `tenant_context(A)`, assert B's rows are invisible
  - assert an insert with B's `org_id` fails
- With no tenant context, and on a reused connection, tenant queries return nothing and do not error.
- `X-Org-Id` for an org the user is not a member of returns 403.

### Bring your own storage (later milestone; design for it now)

Per-org data destinations are configured on `Organisation.data_destination` (encrypted DSN + bucket). A database router picks the connection alias for that org's tenant models.

- Never assume all tenant data lives in `default`.
- Always go through the model manager and router, never raw connections.
- The one exception is the sync service, which takes the alias explicitly.

### Identifiers

- **Generating them:** all primary keys are UUIDv7. Python 3.12 and Postgres 16 have no native UUIDv7, so use the `uuid-utils` package (`uuid_utils.uuid7()`) on the server. The mobile app uses an equivalent RN/JS library.
- **References between layers:** each `Layer` has a `key`, a slug unique within the project (pattern `^[a-z][a-z0-9_]{0,62}$`, e.g. `lyr_farmers`). Layer schemas and capture profiles refer to other layers **by key** (`relation.layer`, `snapping.layers`, `topology.noOverlapWith`, plus the literal `self`). Keys survive copying a project or applying a template.
- **IDs in API paths and payloads:** these use the layer's **UUID** (`layer_id` in sync payloads). The project bundle returns both, so clients can map key ↔ id.

---

## 2. Sync: ordering, idempotency, conflicts

### The trap

A naive global `server_seq` from a Postgres `SEQUENCE` breaks pull cursors. If transaction T1 takes seq 101 and T2 takes seq 102, but T2 commits first, a device pulling at that moment sees 102, saves cursor = 102, and **never** sees 101.

### The design

- **`ProjectSyncState(project_id PK, last_seq bigint)`:** one row per project.
- **`ChangeLog(id, org_id, project_id, seq, entity, entity_id, op, feature_version, changed_at, device_id, user_id)`** with `UNIQUE(project_id, seq)`.
- **Push** (one HTTP request, one transaction, per project):
  1. `SELECT last_seq FROM sync_projectsyncstate WHERE project_id = %s FOR UPDATE`. This serialises writers per project.
  2. For each change in order:
     - Idempotency: if `change_id` is already recorded in `AppliedChange`, return the stored result.
     - Otherwise apply it, write `FeatureHistory`, increment the seq, and insert a `ChangeLog` row with that seq.
  3. Update `last_seq`; commit.

  Because writers to a project are serialised and seq is assigned inside the lock, commit order equals seq order. **Pull never misses rows.** Field data volume per project is low enough that per-project serialisation is fine. Measure it in M6 with a concurrent-push test.
- **Pull:** `ChangeLog WHERE project_id = %s AND seq > :cursor ORDER BY seq LIMIT :limit`. Join the current feature state (if a feature changed 5 times since the cursor, send the latest state once). Return `next_cursor` and `has_more`.
- Non-feature changes (layer schema publish, capture profile edits, membership changes) bump `Project.config_version`. The bundle endpoint returns it, and pull includes it so the phone knows to refresh config.

### Wire formats

The push request, the per-change result and the pull response are defined as JSON Schemas in `packages/schema/schemas/sync.schema.json`. That file is the contract, and the M4 stubs must match it exactly.

- **Push change:** `change_id`, `op` (`create` | `update` | `delete`), `entity` (`feature`), `id`, `layer_id` (UUID), `base_version` (null for create), `schema_version`, `geom`, `attributes`, `changed_fields`, `meta`.
- **Per-change result:**
  - `status` is one of `accepted`, `merged`, `conflict`, `rejected`, `duplicate`
  - plus `feature {id, version}`, `conflict_id` and `errors[]`
- **Pull item:**
  - the latest feature state, including `deleted`, `status`, `review_note`, `version` and `seq`
  - plus `next_cursor`, `has_more`, `config_version`
- Query parameters everywhere are `?project=&cursor=&limit=`.

### Conflict rules

| Situation | Result |
| --- | --- |
| `base_version == server.version` | Apply, version + 1, `accepted` |
| `base_version < server.version`, and the local `changed_fields` don't overlap the fields changed on the server since `base_version` (from `FeatureHistory`) | Field-level merge, version + 1, `merged` |
| Overlap on the same attribute, or both changed `geom` | Server keeps its state. Store a `Conflict` row with both payloads, flag the feature, return `conflict` |
| Delete vs edit (either direction) | Always `conflict` |
| `create` with an id that already exists | Same payload: `duplicate`. Different payload: `rejected` |
| Fails layer schema or capture-rule validation | `rejected`, with errors; nothing written |

### Required tests (M6)

- Idempotent replay of the same batch.
- Concurrent pushes from two devices to the same project; then assert a pull from cursor 0 returns every change exactly once, in seq order.
- Each conflict rule above.
- Pull paging across `limit` boundaries.
- A tenant isolation test on pull.

---

## 3. Geometry and the pilot computations

- Store `Feature.geom` as `GeometryField(srid=4326, null=True)` with a GIST index.
  - Copy the layer's `geometry_type` onto each feature row as `Feature.geometry_type`, because a CHECK constraint cannot read another table.
  - Add the CHECK: `(geometry_type = 'none' AND geom IS NULL) OR (geometry_type = 'point' AND GeometryType(geom) = 'POINT') OR (geometry_type = 'line' AND GeometryType(geom) = 'LINESTRING') OR (geometry_type = 'polygon' AND GeometryType(geom) IN ('POLYGON','MULTIPOLYGON'))`.
  - Changing a layer's geometry type after features exist is not allowed.
- **Server-computed fields, recomputed on every write:**

  | Field | How |
  | --- | --- |
  | `area_m2` | `ST_Area(geom::geography)` |
  | `perimeter_m` | `ST_Perimeter(geom::geography)` |
  | `length_m` | `ST_Length(geom::geography)` |
  | `centroid` | `ST_Centroid(geom)` if `ST_Contains(geom, ST_Centroid(geom))`, else `ST_PointOnSurface(geom)` with `centroid_method = 'point_on_surface'` and a QA flag |

  Expose hectares and acres in API outputs (`area_ha = area_m2 / 10000`, `area_acres = area_m2 / 4046.8564224`).
- **Validation on push:**
  - `ST_IsValid` (reject self-intersections when the capture profile says `preventSelfIntersection`)
  - minimum vertices
  - min/max area
  - **overlap check** against other non-deleted features in the same layer when `topology.noOverlapWith` includes `self`. Overlap means `ST_Intersects(a, b) AND NOT ST_Touches(a, b)`; ignore slivers below a configurable tolerance (default 1 m²). Overlaps are flagged rather than rejected by default; the capture profile decides.
- **Raw track:** store the unsimplified streamed points in `RawTrack` (compressed JSON or a LineStringZM with M = timestamp). Never return it in pull; only on the feature detail endpoint, for audit.
- **EUDR export:** `FeatureCollection`, EPSG:4326, coordinates rounded to 6 decimals. Polygon for plots over 4 ha; for plots of 4 ha or less, the polygon if available, else the point (make the rule configurable per export). Include farmer/producer reference, country, and area in ha as properties.

---

## 4. Shared schema and expression evaluator

- `packages/schema` holds the JSON Schemas (draft 2020-12) for the **capture profile** and the **layer schema**, plus examples. The server validates both on save with `jsonschema` (Python). The web and mobile apps validate with Ajv or Zod schemas generated from the same files.
- **Expressions** (`relevant`, `constraint`, `calculate`) must give identical results on phone, web and server:
  - Write the grammar once in `packages/schema/expressions.md`.
  - Implement it in TypeScript (`packages/schema/src/expr`) and Python (`precisecapture/common/expr.py`).
  - Make both pass the same JSON test vectors in `packages/schema/test-vectors/expressions.json`.
  - **Never use `eval`.** Use a small Pratt or recursive-descent parser.
- **Which calculated values the server trusts:**

  | Expression uses | Server behaviour |
  | --- | --- |
  | `geom_area()`, `geom_length()` (spheroid via PostGIS) | **Recomputes and overrides** the device value. The server value is authoritative; small differences from the phone's spherical calculation are expected. |
  | Only attribute values and literals | **Recomputes and overrides** with the Python evaluator. |
  | `lookup()`, `ghanapost_gps()` | **Keeps the device value**, because the server may not have the reference layer or the GhanaPostGPS service. Optionally re-derives `lookup()` when the reference layer exists on the server, and flags a mismatch. |
  | `today()`, `now()` | **Keeps the device value**, so the capture time is preserved. |

- **Client-side validation must be lenient.** The JSON Schemas are strict (`additionalProperties: false`) so the server catches typos. Web and mobile must validate in a lenient mode (Ajv `removeAdditional: "all"`, or a generated relaxed copy), so an older app never rejects a newer server's profile.
- **Cross-field rules** the schema cannot express are checked by the server on save. They live in one function, `validate_capture_profile_semantics()`, mirrored in TS:
  - `modes.default` must be in `modes.allowed`
  - only one of `stream.intervalMeters` and `stream.intervalSeconds` may be set
  - `intervalMeters` must be in `allowedIntervalsMeters`
  - `stream`, `snapping`, `trace` and `autoClose` apply only to line and polygon layers
  - every layer key referenced must exist in the project
- **Capture profile precedence and locks:**
  - Effective value = org default → project → layer → collector override.
  - A `locked: true` at **any** level freezes that object's settings for every lower level, including the collector. For example, an org-level lock on `gps.averaging` cannot be undone by a layer.
  - Collectors can only change settings inside objects that carry a `locked` flag. Scalars such as `minVertices`, `validation` and `centroid` are admin-only.
  - Implement this in `resolveCaptureProfile` (TS + Python) with shared test vectors.

---

## 5. Attachments

- `POST /attachments` with `{id, feature_id, field_key, content_type, size, checksum_sha256}` returns an S3 multipart upload: an `upload_id` plus presigned part URLs (8 MB parts). The client uploads the parts directly to Spaces or MinIO.
- `POST /attachments/{id}/complete` with the part ETags completes the multipart upload and verifies the size and checksum.
- Storage keys follow `org/{org_id}/project/{project_id}/feature/{feature_id}/{attachment_id}.{ext}`.
- Downloads use short-lived presigned GET URLs (15 min).
- Attachments of deleted features are retained according to the project's retention setting, never deleted immediately.

---

## 6. Auth

- **Access tokens:** JWT, 15 minutes, HS256 with `JWT_SIGNING_KEY` (move to RS256 in the self-hosted milestone so licence servers can verify).
- **Refresh tokens:** opaque, 30 days, stored hashed, rotated on use, revocable per device.
- **OTP login (phone or email):** 6 digits, 10-minute expiry, 5 attempts. The SMS provider sits behind an interface: `ConsoleSmsBackend` in dev, real provider later.
- **Field login options:** username + password, OTP, or a QR code from the web admin, which encodes the server URL and a one-time enrolment token.
- **`/.well-known/precisecapture`** returns `{name, logo_url, api_version, min_app_version, auth_methods}`, so the app can connect to self-hosted servers.

---

## 7. Performance targets (for the pilot)

| Area | Target |
| --- | --- |
| Push batch (200 changes) | p95 < 1.5 s on a DigitalOcean 2 vCPU droplet |
| Pull page (500 changes) | p95 < 1 s |
| Feature list with bbox | p95 < 500 ms for 100k features in a layer |
| Web map | Served by Martin vector tiles, not GeoJSON, above 5k features |

Add a `pytest -m perf` suite with seeded data for these, run manually.
