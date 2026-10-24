# Build plan: backend and web (Ben's side)

Work through the milestones in order. Each one should be a branch and a pull request. Before coding a milestone, Claude Code proposes a plan and waits for Ben's OK. At the end, it reports on every acceptance criterion with evidence.

**Contract checkpoints for Selorm (mobile)** are marked 📱. When one lands, Ben sends Selorm the updated `contract/openapi.json` and `packages/schema` version.

| # | Milestone | Unblocks |
| --- | --- | --- |
| M0 | Monorepo and local dev environment | Everyone |
| M1 | Shared schema package (contract part 1) | 📱 Selorm can build forms and capture rules |
| M2 | Accounts, organisations, tenancy, auth | Everything else |
| M3 | Projects, layers, layer schemas, capture profiles, bundle | 📱 Selorm can download projects |
| M4 | Contract v0: OpenAPI export, mock server, TS client | 📱 Selorm builds against a mock |
| M5 | Features and spatial computations | Web data views |
| M6 | Sync (push/pull/conflicts) | 📱 Real offline sync |
| M7 | Attachments (resumable uploads) | 📱 Photos |
| M8 | Web app foundation and project setup UI | Admin can configure the pilot |
| M9 | Web data: map, table, detail, review, conflicts | Managers can review |
| M10 | Exports and QA (EUDR) | Pilot deliverables |
| M11 | Offline basemap packs | 📱 Offline maps |
| M12 | Start from existing data, reference layers, assignments | 📱 Verification of existing farm surveys; EUDR reserve checks |
| M13 | Pilot hardening and deploy to DigitalOcean (with Desmond) | Pilot go-live |
| Later | Connect integrations (webhooks, API keys, DB connector), BYO storage, self-hosted package, billing | v1/v2 |

---

## M0: Monorepo and local dev environment

**Goal:** one command brings up everything needed to develop; CI runs lint and tests.

**Tasks**

1. Create the layout in `CLAUDE.md` (`apps/api`, `apps/web`, `packages/schema`, `packages/api-client`, `contract/`, `infra/docker`). Keep `apps/mobile/` as an empty folder with a README pointing to Selorm.
2. Root `pnpm-workspace.yaml`, `package.json`, `.editorconfig`, `.gitignore`, `.env.example` (start from the one in this pack).
3. `infra/docker/docker-compose.dev.yml`:
   - PostGIS 16, Redis, MinIO with a bucket auto-created, Martin, and Mailpit
   - a Postgres init script creating the `pc_owner`, `pc_app` and `pc_platform` roles (start from the one in this pack)
4. Django project in `apps/api`:
   - `uv`-managed with `pyproject.toml`
   - settings split into `config/settings/{base,dev,test,prod}.py` using `django-environ`
   - GeoDjango enabled
   - Django Ninja mounted at `/api/v1/`
   - `/health` and `/.well-known/precisecapture` endpoints
5. Celery app wired to Redis, with one `ping` task.
6. `common` app:
   - `UUIDv7Model` base (UUIDv7 primary key, `created_at`, `updated_at`)
   - RFC 9457 exception handler
   - cursor pagination helper
7. Tooling: ruff, mypy + django-stubs, pytest-django, factory_boy, pre-commit.
8. `Makefile` with every command listed in `CLAUDE.md`.
9. GitHub Actions workflow: run API lint and tests against a PostGIS service container. Run web lint and tests once the web app exists.

**Acceptance criteria**

- [ ] On a fresh clone, `make dev-up && make api-install && make api-migrate && make api-run` works, and `GET /health` returns 200.
- [ ] `GET /api/v1/docs` shows the Ninja OpenAPI UI.
- [ ] `make api-test` and `make api-lint` pass locally and in CI.
- [ ] Celery `ping` round-trips in a test.
- [ ] No secrets are committed; `.env.example` documents every variable.

---

## M1: Shared schema package (contract part 1) 📱

**Goal:** a single source of truth for layer attribute schemas and capture profiles, usable from TS (web and mobile) and Python (server).

**Tasks**

1. Review the starter `packages/schema/schemas/*.schema.json` and `examples/` (already in the repo, and already validated), and tighten or fix any gaps against `docs/SPEC.md` §8 and §9. Turn the package into a proper pnpm package (`package.json`, build, tests).
2. Generate TS types from the schemas (`json-schema-to-typescript`) and export them along with Ajv validators.
3. Python side: `precisecapture/common/schema_validation.py` loads the same JSON files (copied or symlinked at build time) and validates with `jsonschema`.
4. Review the expression language spec in `packages/schema/expressions.md`, which is XLSForm-like (`${key}`, `.`, `div`, `selected()`, `if()`, plus `geom_area()` and `geom_length()`), and the starter vectors in `test-vectors/expressions.json`.
5. Implement the parser and evaluator in TS and in Python, with **no `eval`**. Both must pass `test-vectors/expressions.json`, which needs at least 40 cases.
6. Capture profile resolution function, `resolveCaptureProfile(org, project, layer, collectorOverrides)`, implemented in TS and Python with shared test vectors. Locked settings ignore collector overrides.
7. `make schema-test` runs all of the above.

**Acceptance criteria**

- [ ] The example farm capture profile and the Farmers/Farms layer schemas validate in both TS and Python.
- [ ] TS and Python expression evaluators produce identical results on every test vector.
- [ ] The resolution function honours `locked` in all test vectors.
- [ ] Versioned as `@precisecapture/schema@0.1.0`, with a CHANGELOG.

---

## M2: Accounts, organisations, tenancy, auth

**Goal:** users log in and act inside one organisation at a time, and the database itself enforces isolation.

**Tasks**

1. Custom `User`:
   - UUIDv7 primary key
   - email and/or phone (E.164), at least one required
   - name, status
   - argon2 password hashing
2. `Organisation` (name, slug, country, plan, settings JSON with org-level capture defaults, `data_destination` placeholder) and `Membership` (user, org, role: owner/admin/manager/collector/viewer).
3. DB roles, the migrations DB router, the RLS helper, and `tenant_context`. The **Django Ninja auth class** (not middleware) sets `app.current_org_id` from the `X-Org-Id` header after verifying membership, inside the request transaction (`ENGINEERING_NOTES.md §1`). Add the `as_app_role` pytest fixture.
4. Auth endpoints:
   - `POST /auth/login`
   - `POST /auth/refresh` (rotating refresh tokens)
   - `POST /auth/logout`
   - `POST /auth/otp/request`
   - `POST /auth/otp/verify` (console SMS/email backend in dev)
   - `GET /me` (user + memberships)
5. `Device` registration: `POST /devices` with platform, model, OS and app version. Refresh tokens are bound to a device and can be revoked per device.
6. Org admin endpoints: create org (the creator becomes owner), invite member (email/SMS invitation token), change role, remove member.
7. Permission helpers: `require_role(request, "admin")`, plus project-level checks (used in M3).
8. Django admin for platform staff: mounted only when `PLATFORM_ADMIN_ENABLED=true` (internal deployment), using the `platform` alias. Record this in `DECISIONS.md`.

**Acceptance criteria**

- [ ] Isolation tests pass for every tenant table created so far.
- [ ] A request with an `X-Org-Id` the user is not a member of returns 403.
- [ ] A refresh token can't be reused after rotation; reuse revokes that token family.
- [ ] OTP: expiry, attempt limits, and rate limiting per phone/email and per IP are all tested.
- [ ] OpenAPI shows every auth endpoint with schemas and examples.

---

## M3: Projects, layers, layer schemas, capture profiles, bundle 📱

**Goal:** an admin can configure the pilot project via the API, and a phone can download everything it needs.

**Tasks**

1. Models:
   - `Project`: name, description, extent polygon, status (draft/active/archived), settings, `config_version`
   - `ProjectMember`: role, optional `assigned_area`
   - `Layer`: name, `key` (unique slug within the project), `geometry_type` in point/line/polygon/none (immutable once features exist), style JSON, `capture_profile` JSON, `current_schema_version`, sort order
   - `LayerSchemaVersion`: immutable attributes JSON, version, published_at/by
   - `LayerTemplate`
2. Draft-then-publish flow:
   - `PUT /layers/{id}/schema` saves a draft
   - `POST /layers/{id}/schema/publish` validates it against the JSON Schema, checks keys are unique and that no existing key's type changes incompatibly, creates a new `LayerSchemaVersion`, and bumps `Project.config_version`
3. Capture profile endpoint: validate against the schema; editing bumps `config_version`.
4. Layer references: `relation.layer`, `snapping.layers`, `trace.layers` and `topology.*` must name layer **keys** in the same project, or `self`. Also run the cross-field checks in `validate_capture_profile_semantics()` (`ENGINEERING_NOTES.md §4`).
5. `GET /me/projects`: projects the user is a member of, with role and `config_version`.
6. `GET /projects/{id}/bundle`. The phone's offline package contains:
   - project
   - layers
   - current schema versions
   - resolved capture profiles (org → project → layer)
   - option lists
   - basemap pack references (empty until M11)
   - `config_version`
   - `server_seq` watermark

   The ETag is a hash of `config_version` plus the user's membership version (role, assigned area), so it never serves another user's view. The `server_seq` watermark is returned in a header, outside the cached body. `If-None-Match` is supported. A user who is not a member of the project gets 403.
7. Seed command `python manage.py seed_pilot` creates:
   - a demo org
   - users (admin, manager, 2 collectors)
   - the "Western North Farm Mapping" project with Farmers (none) and Farms (polygon) layers, using the example schemas in `packages/schema/examples`

**Acceptance criteria**

- [ ] Publishing an invalid schema returns 422 with per-field errors.
- [ ] Publishing a schema that changes an existing key's type is rejected, unless the change is a safe widening.
- [ ] `GET /me/projects` lists only projects the user is assigned to, across all their orgs.
- [ ] The bundle returns 403 to non-members, 304 when unchanged, and a new ETag when the user's role or assigned area changes.
- [ ] `seed_pilot` runs idempotently.
- [ ] Isolation tests are added for all new tenant tables.

---

## M4: Contract v0: OpenAPI export, mock server, TS client 📱

**Goal:** Selorm can build the mobile app against realistic responses before the real sync exists.

**Tasks**

1. `make contract` exports `contract/openapi.json` from Ninja, with stable operation IDs, tags, and examples on every request and response.
2. Add the sync and attachment endpoints **as typed stubs** returning 501, with Pydantic schemas matching `packages/schema/schemas/sync.schema.json` and `ENGINEERING_NOTES.md §5`. Add a test that validates the stub examples against the JSON Schema. The contract then covers these endpoints before they're implemented.
3. A Prism mock server (`make mock`, port 4010) serving the contract with examples.
4. `packages/api-client`: types generated with `openapi-typescript`, plus a thin fetch client with auth and the `X-Org-Id` header.
5. A CI check: fail if `contract/openapi.json` is out of date relative to the code.
6. `contract/CHANGELOG.md`.

**Acceptance criteria**

- [ ] `make mock` serves every endpoint the phone uses (auth, me, devices, bundle, sync push/pull, attachments).
- [ ] The generated TS client type-checks.
- [ ] Contract version v0.1.0 is tagged in git, and Ben has a summary to send to Selorm.

---

## M5: Features and spatial computations

**Goal:** features can be stored, queried and audited, with all server-side geometry rules.

**Tasks**

1. Models:
   - `Feature`: UUID primary key from the client, org, project, layer, nullable geom, attributes JSONB, `schema_version`, `version`, status (draft/submitted/approved/rejected/sent_back), soft delete, created/updated by and device, computed `area_m2` / `perimeter_m` / `length_m` / `centroid` / `centroid_method`, `qa_flags` array
   - `FeatureHistory`
   - `FeatureRelation`
   - `RawTrack`
   - `VertexMeta`
2. Service `features.services.write_feature(...)`, used by both sync and the web:
   - validate attributes against the layer schema version, evaluating the `relevant` / `required` / `constraint` expressions with the Python evaluator
   - validate geometry against the capture profile
   - compute derived fields
   - write history
3. Overlap QA (`ENGINEERING_NOTES.md §3`), with a configurable sliver tolerance.
4. Read endpoints:
   - `GET /layers/{id}/features`: bbox, status, `updated_since`, attribute filters, cursor pagination; GeoJSON FeatureCollection output
   - `GET /features/{id}`
   - `GET /features/{id}/history`
5. Web edit endpoint: `PATCH /features/{id}`, which goes through the same service and versioning.
6. Review endpoint: `POST /features/{id}/review` with approve, reject, or send back with a note. A send-back appears in the collector's next pull.
7. Tiles:
   - Create a Postgres function `tiles_layer(z, x, y, query_params)` owned by `pc_owner`. It filters by `project_id` and `layer_id` and returns MVT. Grant EXECUTE to `pc_tiles`.
   - Add a Django endpoint `GET /projects/{id}/tiles/{layer}/{z}/{x}/{y}.mvt`. It authenticates the user, checks project membership, then proxies to the internal Martin with caching headers.
   - Martin is never exposed publicly.

**Acceptance criteria**

- [ ] Area/centroid tests:
  - a known square in Ghana gives the expected hectares (within 0.1%)
  - an L-shaped polygon falls back to point-on-surface
- [ ] A self-intersecting polygon is rejected when the profile says so.
- [ ] Two overlapping farms are flagged.
- [ ] History is written for every change, and `GET /features/{id}/history` shows it.
- [ ] A bbox query over 100k seeded features meets the performance target.

---

## M6: Sync (push/pull/conflicts) 📱

**Goal:** a phone can work offline for days and sync safely.

**Tasks**

1. Models: `ProjectSyncState`, `ChangeLog`, `AppliedChange` (change_id → result), `SyncCursor`, `Conflict`.
2. `POST /sync/push`:
   - up to 200 changes; gzip accepted
   - one transaction per project, with a `FOR UPDATE` lock on `ProjectSyncState`
   - per-change results as in `ENGINEERING_NOTES.md §2`
3. `GET /sync/pull?project=&cursor=&limit=`: latest state per changed entity, `next_cursor`, `has_more`, `config_version`. Pull includes review status changes and send-back notes.
4. Conflict handling, field-level merge using `FeatureHistory`, and the conflict endpoints: `GET /conflicts` and `POST /conflicts/{id}/resolve` (keep server, keep device, or merged payload).
5. Update the device's `last_sync_at`, and record sync metrics (changes, durations, errors) for support.
6. Replace the M4 stubs and regenerate the contract.

**Acceptance criteria**

- [ ] Every required test in `ENGINEERING_NOTES.md §2` passes, including the concurrent-push ordering test.
- [ ] Replaying a batch gives `duplicate` results and no new versions.
- [ ] Push and pull performance targets are met with seeded data.
- [ ] Contract updated, and the diff is summarised for Selorm.

---

## M7: Attachments 📱

**Tasks**

1. `Attachment` model, plus the S3 multipart presigned flow against MinIO (dev) and Spaces (prod), per `ENGINEERING_NOTES.md §5`.
2. Image post-processing in a Celery task: generate a thumbnail, extract EXIF GPS and time into metadata, and verify the checksum.
3. Signed download URLs, and an endpoint listing a feature's attachments.
4. Missing-attachment report: features whose required photo fields have no completed upload.

**Acceptance criteria**

- [ ] An interrupted multipart upload can resume.
- [ ] A checksum mismatch is rejected.
- [ ] Storage keys follow the org/project/feature pattern.
- [ ] Cross-org access to an attachment is denied.

---

## M8: Web app foundation and project setup UI

**Goal:** a non-GIS admin can set up the pilot project in the browser.

**Tasks**

1. `apps/web`: Vite + React + TS, TanStack Router and Query, Tailwind, and the auth flow (login, OTP, org switcher). The API client comes from `packages/api-client`.
2. App shell: sidebar (Projects, Data, Members, Settings), responsive layout, toasts, error boundaries.
3. Organisation settings: org-level capture defaults; members and invitations.
4. Project screens:
   - list, create, and draw or upload the project area on a MapLibre map
   - members and assigned areas
5. **Layer screen, one page with tabs:**
   - **General:** name, geometry type (point/line/polygon/none), style
   - **Attributes:** the drag-and-drop attribute builder, with types, required, options and lists, `relevant` / `constraint` / `calculate` expressions validated live by the shared evaluator, a relation picker, and a **live phone-sized form preview**
   - **Capture rules:** the capture profile editor with toggles, sliders and lock icons per setting; the streaming interval offers 1, 2, 3, 5 and 10 m
   - **Publish:** shows a diff from the last version and warns about breaking changes
6. Layer templates: save as template; create a layer from a template.

**Acceptance criteria**

- [ ] Ben can create the Western North project with the Farmers and Farms layers entirely in the UI.
- [ ] The resulting bundle matches what `seed_pilot` produces.
- [ ] Form preview and validation behave identically to the server (driven by shared test vectors).
- [ ] Playwright e2e covers login → create project → add layer → add attributes → publish.

---

## M9: Web data: map, table, detail, review, conflicts

**Tasks**

1. Data view: split map + table.
   - The map uses Martin vector tiles, styled by layer style; clicking a feature selects it.
   - The table is virtualised, with column filters and status filters.
2. Feature detail drawer:
   - attributes, photos (signed URLs), centroid, area in ha and acres
   - GPS accuracy summary, raw-track overlay toggle, history timeline
3. Review actions (approve / reject / send back with a note), including bulk approve.
4. QA panel: overlaps, poor accuracy, centroid fallback, area outliers, farmers with no farm. Clicking a flag zooms the map to it.
5. Conflicts screen: side-by-side compare, and resolve.
6. Live-ish updates: poll the feature list every 15 s, or use SSE.

**Acceptance criteria**

- [ ] The map stays smooth with 100k features.
- [ ] Review status changes reach a collector's next pull.
- [ ] A conflict created by the M6 tests can be resolved in the UI.

---

## M10: Exports and QA (EUDR)

**Tasks**

1. Export jobs as Celery tasks, with progress and a signed download link:
   - **Formats:** CSV, XLSX, GeoJSON, KML, SHP (zipped), GPKG
   - **Scope:** layer, filters, and only-approved
2. **EUDR GeoJSON preset** (`ENGINEERING_NOTES.md §3`), plus a farmer–farm CSV with centroid lat/lon and area in ha.
3. An export history page in the web app.

**Acceptance criteria**

- [ ] The EUDR file validates as GeoJSON, uses EPSG:4326 with 6-decimal coordinates, and applies the polygon/point rule per configuration.
- [ ] SHP and GPKG open in QGIS with correct attributes and CRS.
- [ ] Exports of 50k features finish without timing out (they run in a worker).

---

## M11: Offline basemap packs 📱

**Tasks**

1. Basemap source: a hosted PMTiles file covering Africa (OpenStreetMap-based vector tiles, e.g. a Protomaps build), stored in Spaces. Record the source, licence and attribution in `DECISIONS.md`.
2. `POST /projects/{id}/basemap-packs` runs a Celery job (`pmtiles extract`) for the project area and zoom range, then stores the result in Spaces. The bundle lists the packs, with their size and checksum.
3. Optional satellite imagery pack: design only; source licensing to be decided by Ben.

**Acceptance criteria**

- [ ] A pack for a district-sized area builds, downloads, and opens in MapLibre (web test page).
- [ ] The size estimate is shown before building.

---

## M12: Start from existing data, reference layers, assignments 📱

Spec: `docs/SPEC.md` section 10. Contract: `hiddenOnDevice` and `sourceName` on layer schema fields, `validation.spatialRules` in the capture profile (both optional, backward compatible).

**Tasks**

1. `imports` Django app: `SourceDataset` (original file in object storage, never modified) and `ImportJob` (kind: `new_layer`, `reference`, `add_records`, `update`). Chunked upload reusing the attachments multipart flow.
2. Inspect task (Celery + GDAL via `pyogrio`): layers, geometry types, counts, fields, coded-value domains, SRID. Report stored on the job.
3. Confirm step (`POST /imports/{id}/confirm`): chosen layers, source SRID (required when missing), geometry fixes (repair/skip, keep/split multipart, drop Z), field mapping (type, label, edit/read-only/hidden, `sourceName`), key field. Reject a mapping whose key field is not unique unless "flag duplicates" was chosen.
4. Load: reproject with PROJ to EPSG:4326, `ST_MakeValid` where chosen, COPY into a staging table, insert features with `status=imported`, `field_status=pending`, `source_fid`, `baseline_geom`, `baseline_attributes`. Publish schema version 1. Audit entry.
5. `Layer.role` (`data` or `reference`) and `Layer.origin`. Reference layers: no form, excluded from push, included in the bundle as read-only GeoJSON or PMTiles depending on size.
6. Spatial rules: evaluate `validation.spatialRules` on push and as a backfill task when a reference layer is added or changed; write QA flags (`in_reference`) with overlap area.
7. `Assignment` model and endpoints (`/assignments`, `/assignments/bulk`). The pull for a collector includes only assigned features (or features in `assigned_area`) for imported layers.
8. Field status transitions on push: `verified` when submitted unchanged, `updated` when geometry or an editable attribute changed, `not_found` with reason and photo, `new` for features created in the field. Never allow deletes of imported features from devices.
9. Exports: "back to source format" (original layer name, `sourceName` columns, source SRID, key values) with optional changes-only and `pc_*` change columns. Update-from-file: preview (new / changed / unchanged / missing / changed in both) then apply with a snapshot and rollback.
10. Web UI: start-from-existing-data wizard (source, layers, coordinates, geometry checks, fields, review), reference layers list, assignments map (select, assign, progress), field-status filters and baseline-vs-current view in the record drawer. Follow the prototype.

**Acceptance criteria**

- [ ] A shapefile without a .prj, a GeoPackage in Ghana Metre Grid (EPSG:25000) and a GeoJSON all import; sample coordinates match `pyproj` to within 1 cm.
- [ ] A bow-tie polygon is repaired or skipped as chosen; nothing in the stored original changes.
- [ ] Coded-value domains become choice lists; hidden fields never appear in a collector's bundle or pull.
- [ ] A collector pulls only assigned imported features; reassignment moves them on the next pull.
- [ ] A device cannot delete an imported feature (rejected per change, not per batch).
- [ ] Adding a reference layer flags existing intersecting features; a new push inside it is flagged, warned or blocked per the rule.
- [ ] Export back to GeoPackage reopens in QGIS with the original column names, SRID and key values; changes-only includes exactly updated, not-found and new features.
- [ ] Update-from-file preview counts are correct on a fixture, apply is idempotent, and rollback restores the snapshot.
- [ ] Isolation tests for every new tenant table.

## M13: Pilot hardening and deploy (with Desmond)

**Tasks**

1. Production Dockerfiles: API, worker, beat, Martin, and the web app as static files behind a CDN. Health checks on each.
2. Settings for DigitalOcean: Managed Postgres (PostGIS enabled, `pc_app` role), Managed Redis, Spaces, Sentry, and structured logs.
3. Security:
   - rate limits
   - CORS
   - security headers
   - an admin 2FA option
   - a dependency audit in CI
4. Backups and a restore runbook (Desmond); staging and production environments.
5. Load test of the pilot scenario: 50 collectors, each syncing 30 farms with photos at the end of the day.
6. A support toolkit: per-device sync log view, and resending a project bundle.

**Acceptance criteria**

- [ ] The staging deploy is reproducible from CI.
- [ ] The restore drill is done and documented.
- [ ] The load test meets targets.
- [ ] Every acceptance criterion from M0 to M12 still passes.

---

## Later milestones (v1/v2, plan when we get there)

- **Connect:** API keys, webhooks (signed and retried), scheduled exports to a client's S3/SFTP, and a "sync to your PostGIS" connector with health monitoring.
- **Bring your own storage:** per-org database router and storage backend; encrypted DSNs; migration tooling for client databases.
- **Self-hosted package:** Docker Compose and Helm chart, licence key, RS256 JWT, an update channel.
- **Field ops:** assignment by drawn area, live tracking and breadcrumbs.
- **Live sources:** File Geodatabase write-back hardening, scheduled two-way sync with PostGIS, WFS / OGC API Features and ArcGIS Feature Services.
- **Billing:** plans, usage metering, mobile money payments.
- **XLSForm import, DHIS2 connector, GhanaPostGPS lookups.**
