# PreciseCapture — Product & Technical Spec

Owner: Ben Emunah Aikins · Exported 2026-10-22 from the shared spec doc

## 1. Overview

> **Implementation precedence:** where this spec and `docs/ENGINEERING_NOTES.md`, `packages/schema/` or `docs/DECISIONS.md` differ on implementation detail, those files win. Raise the discrepancy with Ben and fix this spec.

**PreciseCapture** is a commercial web + mobile GIS field data collection platform, built to become the household name for field data collection across Africa. Everything is set up in the browser, field teams collect on iOS or Android phones (online or offline), and data lands on a live web map, or on the client's own servers if they choose. The first pilot is farm boundary and centroid mapping.

**What sets it apart**

- Every capture behaviour is configurable at four levels: org default, project, layer, collector toggle. Admins can lock a setting at any level.
- Geometry capture built for professionals: snapping, trace mode, streaming, GPS averaging, accuracy gating, offset points, and external GNSS/RTK receivers.
- Offline-first on low-end Android, including basemaps and location lookups.
- Data quality is checked on the device, before upload: topology, duplicates, fake GPS.
- Integrations that matter locally: DHIS2, GhanaPostGPS, QGIS, Power BI.

**Target users:** field survey teams in land administration, health, utilities, agriculture, NGOs and local government. Buyers are the org admins and project managers who set up projects and review data.

**Team split**

| Area | Owner | Scope |
| --- | --- | --- |
| Backend + web platform | Ben | Django API, database, sync server, web app, form builder, exports, integrations |
| Mobile app | Selorm | React Native app for iOS and Android: offline store, map and geometry capture, forms, sync client |
| DevOps | Desmond | DigitalOcean infrastructure, CI/CD, monitoring, backups, self-hosted deployment packages |
| Shared | All three | Layer attribute schema, capture profile schema, sync protocol, API contract |

## 2. How it works

An admin sets up a project on the web, collectors capture offline on their phones, and data syncs back for review and export, landing in our cloud or on the client's own servers.

> _Diagram (how PreciseCapture works · 5 steps, 3 data destinations) — see the live spec doc for the drawing._

A manager can send a record back with a note; it reappears on the collector's phone at the next sync.

**Project setup (one screen per layer, no separate form step)**

1. **Create a project:** name, area, description.
2. **Add a layer** and choose its geometry: point, line, polygon, or none (a plain table, such as a farmer register).
3. **Add attributes** to the layer: name, type, required, dropdown options, show/hide rules. This list is also the form the collector fills in, in the same order.
4. **Set capture rules** on the layer's rules tab: streaming interval (1 m and up), auto-close, GPS limit, snapping, overlap checks.
5. **Link layers** where needed: a relation attribute on Farms points to the Farmers layer, so one farmer can have many farms.
6. **Set the map:** basemap, layer styles, offline area.
7. **Assign members and publish.** Collectors see the project on their phones.

**The pilot project, set up this way**

```text
Project: Western North Farm Mapping
├── Layer: Farmers  (no geometry)
│     name, ID, phone, photo, community, cooperative
└── Layer: Farms    (polygon + automatic centroid)
      farmer → Farmers, crop, planting year, photos, consent
      area_ha, centroid_lat, centroid_lon calculated automatically
      capture rules: stream every 3 m (1 m allowed), auto-close locked, no overlaps
```

Behind the scenes, each layer's attribute list is saved as a versioned schema (section 9), so editing fields never breaks data already collected.

## 3. Pilot: farm boundary and centroid mapping

The pilot maps farms as a boundary polygon plus a centroid point, linked to a registered farmer. The timing is strong: under the EU Deforestation Regulation (EUDR), exporters of cocoa, coffee, oil palm, rubber, soya, wood and cattle must supply the geolocation of every plot, with polygons required for plots over 4 hectares. Application dates are 30 December 2026 for large and medium operators and 30 June 2027 for micro and small ones ([source](https://www.coolset.com/academy/eu-deforestation-regulation); confirm against the EU Official Journal before quoting to clients).

**Field workflow**

1. Register or find the farmer: name, ID number, phone, photo, community, cooperative.
2. Start a new farm for that farmer (one farmer can have many farms).
3. Walk the boundary in streaming mode; corners can be captured with GPS averaging.
4. The app auto-closes the polygon and shows area (hectares and acres), perimeter and centroid.
5. On-device checks: self-intersection, overlap with other mapped farms, GPS accuracy, area outside expected range.
6. Add crop type, planting year, photos and consent, then submit. Sync happens when a network is available.

**Centroid rules**

- Default is the geometric centroid of the polygon.
- If the centroid falls outside the polygon (L-shaped or irregular farms), the app uses a point-on-surface instead and flags the record.
- For small plots, an admin can allow point-only capture (a centroid taken by standing in the farm) where the buyer's rules permit it.
- Both polygon and centroid are stored, so exports can serve either requirement.

**Farm capture profile (starting point)**

```json
{
  "geometryType": "polygon",
  "modes": { "allowed": ["stream", "gps_vertex", "tap"], "default": "stream" },
  "autoClose": { "enabled": true, "locked": true },
  "stream": { "intervalMeters": 3, "allowedIntervalsMeters": [1, 2, 3, 5], "pauseWhenStationary": true, "simplifyOnClose": { "enabled": true }, "keepRawTrack": true },
  "gps": { "maxAccuracyMeters": 5, "onPoorAccuracy": "warn", "averaging": { "enabled": true, "samples": 10 }, "rejectMockLocation": true },
  "validation": { "preventSelfIntersection": true, "topology": { "noOverlapWith": ["self"] }, "duplicateWarningMeters": 10 },
  "display": { "showArea": true, "units": "hectares" },
  "centroid": { "method": "centroid", "fallback": "point_on_surface" }
}
```

Values are proposals to tune during the pilot.

**Outputs**

- EUDR-ready GeoJSON (WGS84, 6 decimal places), one feature per plot, with polygon or point by the size rule.
- CSV and XLSX: farmer, farm ID, centroid latitude and longitude, area in hectares, crop, capture date, collector.
- QA dashboard: overlapping farms, poor-accuracy farms, unusually small or large areas, farmers with no farm.

**Pilot measures (targets to agree with the partner)**

- Average time to map one farm.
- Share of farms passing QA on first submission.
- Area difference against a reference survey on a sample of farms.
- Longest offline period with no data loss.
- Collector satisfaction after one week.

## 4. Design principles

1. **Configurable at three levels.** Every capture and form behaviour is a setting. It resolves as org default, then project, then layer, then collector toggle. An admin can lock any setting so collectors cannot change it.
2. **Offline-first.** The app works fully with no network: forms, existing features, basemaps, lookups. Sync is a background task, never a blocker.
3. **Quality at the point of capture.** Validation, topology checks, duplicate warnings and GPS accuracy rules run on the phone. The web is for review, not cleanup.
4. **Schema-driven.** The web defines forms and capture behaviour as JSON. The app renders whatever the schema says. New field types ship on both sides from one contract.
5. **Fast on cheap phones.** Target a 2–3 GB RAM Android device. Geometry editing must stay smooth with large datasets.
6. **Trust by default.** Every change is attributed (who, when, which device, which GPS fix) and versioned.
7. **Open at the edges.** Standard formats in and out (GeoJSON, GPKG, SHP, KML, CSV, XLSForm), a public API, and webhooks.

## 5. Feature roadmap

The MVP proves the hard part: smooth, offline geometry capture with configurable rules, synced to a live web map. v1 makes it sellable to teams; v2 adds the differentiators that justify premium pricing.

| Area | MVP | v1 | v2 |
| --- | --- | --- | --- |
| Geometry capture (mobile) | Point, line, polygon by map tap or GPS vertex; undo/redo; move/insert/delete vertex; auto-close toggle; live area and length; self-intersection check | Snapping (vertex/edge, tolerance, target layers); streaming mode (every X m or s); GPS averaging; accuracy gating; offset points; holes; split/merge | Trace mode for shared boundaries; topology rules (no overlap, no gaps); external GNSS/RTK over Bluetooth with NTRIP; imagery-assisted digitising |
| Forms | Text, number, date, select one/many, photo, GPS-derived fields; required and range validation; skip logic | Calculations, cascading selects, repeat groups, sticky values, barcode/QR, signature, voice note; XLSForm import; form versioning | Voice-to-form; photo-based attribute suggestions |
| Offline | Download project (forms + features); offline basemap packs; outbox with retry | Area-based partial download; offline admin boundary lookup; resumable photo upload | Offline imagery packs; peer sync between devices |
| Data quality | Required fields, validation, GPS accuracy stored per vertex | Duplicate-nearby warning; fake-GPS detection; photo GPS/time stamp | Rule engine for custom checks; anomaly flags |
| Web: setup | Orgs, users, roles; projects and layers; form builder; capture profile editor | Data upload (SHP, GeoJSON, KML, CSV, GPKG); layer styling; basemap pack builder | Templates marketplace; QGIS connector plugin |
| Web: data | Live map + table; record detail with photos; filters; exports (CSV, XLSX, GeoJSON, SHP, KML, GPKG) | Review workflow (approve / reject / send back); per-feature history; conflict resolution UI | Dashboards and PDF reports; public share and embed |
| Field ops | Project assignment to users | Task assignment by area or feature; progress map | Live tracking and breadcrumbs; team messaging |
| Platform | Auth, multi-tenant orgs, audit log | API keys, webhooks, plan limits and usage metering, billing | DHIS2, Power BI and ArcGIS connectors; SSO; data residency option |

## 6. System architecture and tech stack

> _Diagram (system architecture · 2 clients, 1 API, 3 backing services) — see the live spec doc for the drawing._

Both apps talk only to the API, and both import the same schema package, so a form or capture rule behaves the same on web preview and in the field.

| Layer | Choice | Why |
| --- | --- | --- |
| Backend API | Python, Django 5 + GeoDjango, Django Ninja (typed endpoints, OpenAPI out of the box) | Built-in auth, admin, ORM and migrations; GeoDjango for spatial; Ninja keeps the API fast and typed |
| Multi-tenancy | Shared schema with org\_id + Postgres row-level security; a database router for orgs that bring their own database | One codebase serves cloud, BYO-storage and self-hosted clients (section 13) |
| Database | DigitalOcean Managed PostgreSQL with PostGIS | Spatial queries, topology checks; managed backups and failover |
| Background jobs | Celery + Redis (DigitalOcean Managed Redis/Valkey) | Exports, imports, basemap pack builds, webhooks, connector sync |
| Vector tiles | Martin (serves MVT straight from PostGIS) | Fast web map for large layers |
| Basemap packs | PMTiles built from OpenStreetMap or imagery per project extent | Single-file offline maps the app can download |
| Object storage | DigitalOcean Spaces (S3-compatible) via django-storages | Photos and files; the same code works with a client's own S3 or MinIO |
| Hosting | DigitalOcean Kubernetes (DOKS) or App Platform, with a CDN in front of Spaces | Simple to run; same containers ship to self-hosted clients |
| Web app | React, TypeScript, Vite, MapLibre GL JS, TanStack Query, a drag-and-drop form builder | Modern, fast; same map engine as mobile |
| Mobile app | React Native (new architecture) with Expo dev client, iOS and Android from one codebase | Selorm's stack; native modules where needed |
| Mobile map | @maplibre/maplibre-react-native | Offline packs, vector styles, same styles as web |
| Mobile database | op-sqlite (with SQLite R\*Tree spatial index) | Fast synchronous SQLite over JSI for large offline datasets |
| Mobile geometry | Turf.js for general ops; hot paths (snapping, intersection) in worklets or a native module | Keeps editing smooth on low-end phones |
| Mobile device | react-native-vision-camera, react-native-ble-plx (GNSS), expo-location + expo-task-manager for background location | All open source; revisit a commercial background library only if pilot tracking is unreliable |
| Shared code | npm workspace package: TypeScript types, JSON Schemas, expression evaluator | One contract for web and mobile |
| Ops (Desmond) | Docker, GitHub Actions CI/CD, Sentry, OpenTelemetry, automated backups, staging + production environments | Same images for cloud and on-prem |

Library choices are proposals to validate in the Phase 0 spike. Background location on iOS is the area to test hardest, because iOS limits background GPS more strictly than Android.

## 7. Data model

Every row belongs to an organisation, and every feature carries a client-generated UUID and a version number. That is what makes multi-tenancy and offline sync work.

| Entity | Key fields | Notes |
| --- | --- | --- |
| organisation | id, name, plan, settings (org-level capture defaults), region, data\_destination | Tenant boundary; Postgres row-level security keyed on org\_id |
| user | id, email, name, phone, status | A user can belong to several orgs |
| membership | user\_id, org\_id, role | Roles: owner, admin, manager, collector, viewer |
| project | id, org\_id, name, extent, status, settings | Groups layers, members and basemap packs |
| project\_member | project\_id, user\_id, role, assigned\_area (geometry, optional) | Controls what a collector downloads |
| layer | id, project\_id, name, key (project-unique slug), geometry\_type (point, line, polygon, none), style, capture\_profile (JSON), current\_schema\_version | One layer = one feature type; its attributes are its form. Geometry is always stored in EPSG:4326 |
| layer\_schema\_version | id, layer\_id, version, attributes (JSON, section 9), published\_at, published\_by | Immutable once published; features record the version they used |
| layer\_template | id, org\_id, name, geometry\_type, attributes, capture\_profile | Save a layer (e.g. Farms) and reuse it in new projects |
| feature | id (UUID), layer\_id, geom, attributes (JSONB), schema\_version, version, created\_by, updated\_by, device\_id, created\_at, updated\_at, deleted, status | Geometry in PostGIS (null for no-geometry layers); status = draft, submitted, approved, rejected, sent\_back |
| feature\_relation | from\_feature\_id, to\_feature\_id, attribute\_key | Links across layers, e.g. farm → farmer |
| feature\_history | feature\_id, version, geom, attributes, changed\_by, changed\_at, device\_id, change\_type | Full version history and audit |
| raw\_track | feature\_id, points with accuracy and time | The unsimplified streamed track, kept for audit |
| vertex\_meta | feature\_id, vertex\_index, accuracy\_m, fix\_type, satellites, timestamp, source | Optional per-vertex GPS quality |
| attachment | id (UUID), feature\_id, field\_key, type, storage\_key, size, checksum, captured\_at, lat, lon, upload\_status | Files in object storage; metadata in Postgres |
| task | id, project\_id, assignee\_id, area/feature ref, due, status | v1 |
| basemap\_pack | id, project\_id, extent, zoom\_range, format, storage\_key, size | PMTiles packs for offline use |
| device | id, user\_id, platform, app\_version, last\_sync\_at | For sync bookkeeping and support |
| sync\_cursor | device\_id, project\_id, last\_server\_seq | Where each device is up to |
| conflict | id, feature\_id, local\_version, server\_version, payloads, status, resolved\_by | Feeds the conflict resolution UI |

## 8. Capture profile schema

The capture profile is one JSON object per layer that tells the app how geometry may be captured. The web edits it; the app obeys it. This object is how auto-close, snapping and every other behaviour become switchable.

**Resolution rule:** effective value = collector toggle (if allowed) → layer profile → project settings → org default. Any setting can carry `"locked": true`, which hides the collector toggle.

```json
{
  "schemaVersion": 1,
  "geometryType": "polygon",
  "modes": {
    "allowed": ["tap", "gps_vertex", "stream", "hybrid"],
    "default": "tap",
    "locked": false
  },
  "autoClose": { "enabled": true, "locked": false },
  "minVertices": 3,
  "snapping": {
    "enabled": true,
    "toleranceMeters": 2.0,
    "targets": ["vertex", "edge"],
    "layers": ["self", "lyr_roads"],
    "locked": false
  },
  "trace": { "enabled": false, "layers": ["self"] },
  "stream": {
    "intervalMeters": 3,
    "allowedIntervalsMeters": [1, 2, 3, 5, 10],
    "intervalSeconds": null,
    "pauseWhenStationary": true,
    "skipVertexIfAccuracyWorseThanMeters": 5,
    "simplifyOnClose": { "enabled": true, "toleranceMeters": "auto" },
    "keepRawTrack": true,
    "locked": false
  },
  "gps": {
    "maxAccuracyMeters": 5,
    "onPoorAccuracy": "warn",
    "averaging": { "enabled": true, "samples": 10, "locked": false },
    "allowExternalReceiver": true,
    "rejectMockLocation": true
  },
  "offsetPoints": { "enabled": true },
  "validation": {
    "preventSelfIntersection": true,
    "topology": { "noOverlapWith": ["self"], "noGapsWith": [] },
    "minAreaSqm": 1,
    "maxAreaSqm": null,
    "duplicateWarningMeters": 5
  },
  "display": { "showArea": true, "showLength": true, "units": "metric" }
}
```

**Field notes**

- `onPoorAccuracy`: `warn` lets the collector proceed with a flag; `block` rejects the vertex; `ignore` records the accuracy only.
- `stream` applies only to lines and polygons. Either distance or time drives it, not both.
- `topology` rules run on the device against features already downloaded. The server re-checks on upload.
- New keys must be optional with safe defaults, so older app versions can ignore what they do not understand.

**Streaming down to 1 m**

Collectors can stream a vertex as often as every 1 m. Phone GPS is usually accurate to only 3–5 m in the open and worse under tree canopy, so at 1 m the app applies three filters to stop GPS wobble from producing zigzag boundaries, inflated perimeters or self-crossing polygons:

- **Accuracy filter:** a vertex is skipped when the GPS reading is worse than the layer's limit.
- **Standstill filter:** no vertices are added while the collector is not moving.
- **Simplify on close:** when the polygon closes, wobble is removed with Douglas–Peucker simplification (tolerance `auto` = the median GPS accuracy of the walk). The raw track is kept for audit.

Recommended: 3 m as the default for phone GPS; 1 m as the default when an external sub-metre GNSS receiver is connected.

## 9. Layer attribute schema (the form)

Each layer's attributes are stored as a versioned JSON document. The admin builds it on the layer's attributes screen; the app renders it as the form, in the same order. Attribute keys are stable forever; labels can change between versions without breaking data.

```json
{
  "schemaVersion": 1,
  "layerId": "lyr_parcels",
  "version": 3,
  "title": { "en": "Land parcel survey" },
  "fields": [
    { "key": "parcel_id", "type": "text", "label": { "en": "Parcel ID" },
      "required": true, "validation": { "pattern": "^[A-Z]{2}-\\d{5}$" } },
    { "key": "land_use", "type": "select_one", "label": { "en": "Land use" },
      "options": "list:land_use", "sticky": true },
    { "key": "building_type", "type": "select_one", "label": { "en": "Building type" },
      "options": "list:building_type",
      "relevant": "${land_use} = 'residential'" },
    { "key": "area_sqm", "type": "calculate", "expression": "geom_area()", "readonly": true },
    { "key": "district", "type": "calculate", "expression": "lookup('districts', 'name')" },
    { "key": "gpgps", "type": "calculate", "expression": "ghanapost_gps()" },
    { "key": "photos", "type": "photo", "label": { "en": "Photos" },
      "min": 1, "max": 4, "maxDimensionPx": 1920, "stamp": true },
    { "key": "occupants", "type": "repeat", "label": { "en": "Occupants" },
      "fields": [
        { "key": "name", "type": "text", "required": true },
        { "key": "phone", "type": "phone" }
      ] },
    { "key": "owner_sign", "type": "signature" }
  ],
  "lists": {
    "land_use": [
      { "value": "residential", "label": { "en": "Residential" } },
      { "value": "commercial", "label": { "en": "Commercial" } }
    ],
    "building_type": []
  }
}
```

**Field types:** text, number, integer, decimal, date, time, datetime, select\_one, select\_many (cascading via `choiceFilterParent` + option `filter`), yes\_no, phone, email, photo, audio, video, file, signature, barcode, calculate, note, repeat, group, geopoint (secondary location), relation. The authoritative list is the enum in `packages/schema/schemas/layer-schema.schema.json`.

**Expression language:** a small, safe subset close to XLSForm (`${field}`, comparisons, `and`/`or`, arithmetic, `if()`, string functions) plus spatial functions: `geom_area()`, `geom_length()`, `lookup(layer, field)` (point-in-polygon on offline reference layers), `ghanapost_gps()`, `nearest(layer, field)` (later version). The same evaluator must exist in TypeScript for both web preview and the app, so share it as an npm package.

**Versioning:** publishing a layer's attribute changes creates a new `layer_schema_version`. Collected features keep the version they were captured with. Removed attributes stay in old data; new required attributes apply only to new captures. A **relation** attribute type (`"type": "relation", "relation": { "layer": "lyr_farmers" }`) links a feature to a feature in another layer, such as a farm to its farmer.

## 10. Sync protocol

Sync is push-then-pull over a server sequence number: the device pushes its outbox, then pulls every change since its last cursor. Records use client UUIDs and optimistic versioning, so the phone never waits for the server to assign IDs.

**Rules**

- Every feature and attachment gets a UUID v7 on the device at creation.
- Every server write bumps the feature's `version` and stamps a per-project, gap-free, commit-ordered `seq` (see ENGINEERING_NOTES.md §2).
- Deletes are soft (`deleted: true`) so they sync like any other change.
- The device keeps an **outbox** table: one row per local change, applied in order, retried with exponential backoff.
- Push sends `base_version` (the version the edit started from). If it matches the server, the write is accepted. If not, it is a conflict.

**Sequence**

1. **Push changes:** `POST /sync/push` with a batch of up to 200 changes from the outbox.
2. **Server applies each change:** accepted, conflict, or rejected (validation error). It returns a per-change result.
3. **Device clears accepted items** from the outbox and records conflicts locally.
4. **Upload attachments:** for each pending file, `POST /attachments` returns an S3 multipart upload with presigned part URLs; the device uploads parts directly to storage and calls `/complete` (ENGINEERING_NOTES.md §5).
5. **Pull changes:** `GET /sync/pull?project=&cursor=<cursor>&limit=500`, paged until `has_more` is false. The device applies them and saves the new cursor.
6. **Pull config:** if the project's `config_version` changed (layer schemas, capture profiles, layers), the device refreshes those before the next capture.

**Push payload (one change)**

```json
{
  "change_id": "0192f0c1-...",
  "op": "update",
  "entity": "feature",
  "id": "0192efa3-...",
  "layer_id": "0192ef00-5a1e-7c3b-9d2f-8a4b6c1e2d3f",
  "base_version": 4,
  "schema_version": 3,
  "geom": { "type": "Polygon", "coordinates": [[[-0.187, 5.603], [-0.186, 5.603], [-0.186, 5.604], [-0.187, 5.603]]] },
  "attributes": { "land_use": "residential" },
  "changed_fields": ["geom", "land_use"],
  "meta": { "device_id": "0192ee9a-1b2c-7d4e-8f90-123456789abc", "captured_at": "2026-10-06T10:15:02Z", "gps_accuracy_m": 2.4, "mock_location": false }
}
```

**Conflict policy**

- If the local and server edits touched **different fields**, the server merges them automatically (field-level merge using `changed_fields`).
- If they touched the **same field or the geometry**, the server keeps its version, stores the device's version in `conflict`, and flags the feature. A manager resolves it in the web conflict UI, choosing one side or merging.
- A deleted-versus-edited conflict always goes to manual review.

**Low-bandwidth handling:** gzip all payloads, resize photos on the device before upload (configurable, default 1920 px), allow "sync on Wi-Fi only" for attachments, and let changes sync before photos so the map updates first.

## 11. API outline

REST over HTTPS, JSON, versioned under `/api/v1`, documented as an OpenAPI 3.1 spec generated by Django Ninja. Ben publishes the spec and a mock server first, so Selorm can build against it from day one. Mobile uses the endpoints marked ✓.

| Group | Endpoint | Purpose | Mobile |
| --- | --- | --- | --- |
| Auth | `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout` | JWT access (15 min) + refresh token (30 days) | ✓ |
| Auth | `POST /auth/otp/request`, `POST /auth/otp/verify` | Phone/email one-time code login for field staff | ✓ |
| Me | `GET /me`, `GET /me/projects` | Profile, orgs, assigned projects | ✓ |
| Devices | `POST /devices` | Register device, app version | ✓ |
| Orgs | `GET/POST/PATCH /orgs`, `/orgs/{id}/members` | Tenant and membership admin |  |
| Projects | `GET/POST/PATCH /projects`, `/projects/{id}/members` | Project setup and assignment |  |
| Project bundle | `GET /projects/{id}/bundle` | Everything the app needs offline: layers, layer schemas, capture profiles, lists, config\_version | ✓ |
| Layers | `GET/POST/PATCH /projects/{id}/layers`, `/layers/{id}/capture-profile` | Layers, styles, capture rules |  |
| Layer schemas | `GET/PUT /layers/{id}/schema`, `POST /layers/{id}/schema/publish`, `GET /layers/{id}/schema/versions/{v}` | Layer attributes (the form) and their versions | ✓ (read) |
| Features | `GET /layers/{id}/features` (bbox, filters, paging), `GET/PATCH /features/{id}`, `GET /features/{id}/history` | Web table/map and detail |  |
| Vector tiles | `GET /projects/{id}/tiles/{layer}/{z}/{x}/{y}.mvt` (proxied to Martin after auth) | Fast web map rendering of large layers |  |
| Sync | `POST /sync/push`, `GET /sync/pull` | Section 10 | ✓ |
| Attachments | `POST /attachments` (returns presigned multipart part URLs), `POST /attachments/{id}/complete`, `GET /attachments/{id}` | Resumable media upload and signed download | ✓ |
| Basemaps | `POST /projects/{id}/basemap-packs`, `GET /basemap-packs/{id}/download` | Build and download offline packs | ✓ (download) |
| Review | `POST /features/{id}/review` | Approve, reject, send back with a note |  |
| Conflicts | `GET /conflicts`, `POST /conflicts/{id}/resolve` | Conflict resolution UI |  |
| Tasks | `GET/POST/PATCH /tasks` | v1 field task assignment | ✓ |
| Exports | `POST /exports`, `GET /exports/{id}` | Async export jobs (CSV, XLSX, GeoJSON, SHP, KML, GPKG) |  |
| Imports | `POST /imports` | Data upload and XLSForm import |  |
| Integrations | `/webhooks`, `/api-keys` | v1 integrations |  |

**Conventions:** UUIDs for all IDs; cursor paging; ISO 8601 UTC times; GeoJSON in EPSG:4326 on the wire; errors as RFC 9457 problem JSON; idempotency via `change_id` on sync and an `Idempotency-Key` header on other writes.

## 12. Security, multi-tenancy and compliance

Tenant isolation is enforced in the database, not only in application code, because one leaked query across clients would end the business.

- **Isolation:** every tenant table has `org_id`; Postgres row-level security policies use the org set on each request's connection. Object storage keys are prefixed by org.
- **Permissions:** role per org, role per project, and optional layer-level and field-level rules (e.g. collectors cannot see the `owner_phone` field; viewers see approved records only).
- **Auth:** short-lived JWTs, rotating refresh tokens, revocation on device loss, optional 2FA for admins; SSO (SAML/OIDC) in v2.
- **On the device:** encrypted local database (SQLCipher-compatible), tokens in the OS keystore, remote wipe of project data when a user is removed.
- **In transit and at rest:** TLS 1.2+ everywhere; encrypted database volumes and storage buckets; signed, expiring URLs for media.
- **Audit:** every write logged with user, device, time and IP; audit log exportable for clients.
- **Data protection:** design for Ghana's Data Protection Act, 2012 (Act 843): consent fields in forms where personal data is collected, data retention settings per project, export and delete on request. Confirm Data Protection Commission registration obligations with a lawyer before launch.
- **Data residency:** default cloud region plus an option to deploy in-country or on a client's own server for government contracts. Keep the stack container-based so this is a deployment choice, not a rewrite.
- **Commercial controls:** plan limits (users, projects, storage, features/month) enforced server-side; usage metering feeds billing.

## 13. Bring your own infrastructure

Any institution can keep its data on its own servers, at one of three levels, using the same mobile app from the app stores. This is a core selling point across Africa, where governments, ministries and large NGOs often require data to stay in-country under laws such as Ghana's Act 843, Nigeria's NDPA, Kenya's Data Protection Act and South Africa's POPIA.

| Level | Where data lives | How it works | Best for | Phase |
| --- | --- | --- | --- | --- |
| 1. Connect | PreciseCapture cloud, copied to the client in near real time | Webhooks, REST API, scheduled exports to the client's S3 or SFTP, and a "sync to your database" connector that writes features into the client's PostGIS | NGOs, companies, exporters with their own data warehouse | v1 |
| 2. Bring your own storage | Client's own PostgreSQL/PostGIS and S3-compatible bucket | PreciseCapture runs the apps; the org's settings hold encrypted connection details, and a database router sends that org's features and media to the client's servers. Our cloud keeps only users, project settings and the sync queue | Agencies that want managed software but owned data | v1–v2 |
| 3. Self-hosted | Entirely on the client's servers or national data centre | The whole stack ships as Docker images with Docker Compose and a Helm chart; licence key; versioned updates Desmond publishes | Governments, ministries, regulators | v2 (earlier for a paying client) |

**How the mobile app connects to a client's server**

- The login screen has a "Use my organisation's server" option: type a server URL or scan a QR code from the web admin.
- The app can hold several accounts on different servers and switches between them.
- Each server exposes `/.well-known/precisecapture` (name, logo, API version, auth method), so the app checks compatibility before login and can show the institution's branding.

**Rules for the codebase so this stays possible**

- No hard-coded domains or bucket names; every endpoint and credential comes from configuration.
- All storage goes through django-storages and the database router, never direct paths.
- Migrations must run cleanly on a client database that we do not control; document the minimum PostgreSQL and PostGIS versions.
- Connectors report health (last success, backlog, errors) on the web admin and alert the client when their server is unreachable; data waits in a queue and is never dropped.
- The API is versioned and backward-compatible, so a self-hosted server a version behind still works with the latest app.

## 14. Delivery plan and open decisions

> _Diagram (delivery roadmap · 4 phases, 3 gates) — see the live spec doc for the drawing._

Phase 0 is the most important: once the contract is agreed, Ben builds the API and web app while Selorm builds against the mock server, and neither blocks the other. Selorm's first job is a geometry-editing spike on a low-end Android phone, because smooth editing in React Native is the biggest technical risk.

**Working agreements**

- One monorepo (web, mobile, shared package, API) or at least a shared package published to a private registry.
- Any change to a schema or endpoint goes through a pull request both of you review.
- Weekly 30-minute sync between Ben and Selorm; a shared test project with real Ghana data from week 4.
- Test devices: at least one 2–3 GB RAM Android phone, one mid-range Android phone, and one older iPhone still on a supported iOS version.

**Open decisions**

- [x] Product name: PreciseCapture
- [ ] Domain name and app store listings
- [x] First pilot: farm boundary and centroid mapping
- [ ] Pilot partner (cooperative, licensed buying company or exporter) and region
- [x] Cloud: DigitalOcean; clients can bring their own infrastructure (section 13)
- [x] Background location: open source for now
- [x] Platforms: iOS and Android both in the MVP
- [x] Backend framework: Django + GeoDjango
- [x] DevOps: Desmond
- [ ] Pricing model: per user, per project, or per farm/feature volume
- [ ] Who covers QA

## Sources

- [EU Deforestation Regulation: operator obligations before December 2026](https://www.coolset.com/academy/eu-deforestation-regulation) (Coolset)
