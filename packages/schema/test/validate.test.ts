import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import {
  validateCaptureProfile,
  validateLayerSchema,
  validatePullResponse,
  validatePushRequest,
  validatePushResponse,
} from "../src/index.js";

const example = (name: string): unknown =>
  JSON.parse(readFileSync(join(__dirname, "..", "examples", name), "utf8"));

describe("pilot examples", () => {
  it("Farmers and Farms layer schemas validate strictly", () => {
    expect(validateLayerSchema(example("farmers.layer-schema.json")).ok).toBe(true);
    expect(validateLayerSchema(example("farms.layer-schema.json")).ok).toBe(true);
  });
  it("farm capture profile validates strictly", () => {
    expect(validateCaptureProfile(example("farms.capture-profile.json")).ok).toBe(true);
  });
});

describe("layer schema", () => {
  it("reports per-field errors with dotted paths", () => {
    const r = validateLayerSchema({
      schemaVersion: 1,
      fields: [{ key: "Bad Key", type: "select_one" }, { key: "ok", type: "nope" }],
    });
    expect(r.ok).toBe(false);
    if (r.ok) return;
    const fields = r.errors.map((e) => e.field);
    expect(fields).toContain("fields.0.key");
    expect(fields).toContain("fields.0.options"); // select_one requires options
    expect(fields).toContain("fields.1.type");
  });
  it("relation.layer must be a layer key", () => {
    const r = validateLayerSchema({
      schemaVersion: 1,
      fields: [{ key: "farmer", type: "relation", relation: { layer: "Not-A-Key" } }],
    });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors[0]?.field).toBe("fields.0.relation.layer");
  });
  it("strict mode rejects unknown keys, lenient mode strips them", () => {
    const doc = { schemaVersion: 1, fields: [{ key: "a", type: "text", futureKey: 1 }], futureTop: true };
    const strict = validateLayerSchema(doc);
    expect(strict.ok).toBe(false);
    if (!strict.ok) expect(strict.errors.map((e) => e.field)).toEqual(expect.arrayContaining(["futureTop", "fields.0.futureKey"]));
    const lenient = validateLayerSchema(doc, "lenient");
    expect(lenient.ok).toBe(true);
    if (lenient.ok) {
      expect(lenient.data).toEqual({ schemaVersion: 1, fields: [{ key: "a", type: "text" }] });
      expect((doc.fields[0] as Record<string, unknown>).futureKey).toBe(1); // input untouched
    }
  });
});

describe("capture profile", () => {
  it("layer refs must be keys or self", () => {
    const r = validateCaptureProfile({ snapping: { layers: ["self", "Roads!"] } });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors[0]?.field).toBe("snapping.layers.1");
  });
  it("partial profiles (org/project level) are valid", () => {
    expect(validateCaptureProfile({ gps: { averaging: { enabled: true, locked: true } } }).ok).toBe(true);
  });
  it("stream interval bounds", () => {
    const r = validateCaptureProfile({ stream: { intervalMeters: 0.5 } });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors[0]).toMatchObject({ field: "stream.intervalMeters", code: "minimum" });
  });
});

describe("sync wire formats", () => {
  const uuid = "0192f0c1-0000-7000-8000-000000000001";
  const change = {
    change_id: uuid,
    op: "create",
    entity: "feature",
    id: "0192f0c1-0000-7000-8000-000000000002",
    layer_id: "0192f0c1-0000-7000-8000-000000000003",
    base_version: null,
    schema_version: 1,
    geom: { type: "Point", coordinates: [-2.1, 6.2] },
    attributes: { crop: "cocoa" },
    meta: { device_id: "0192f0c1-0000-7000-8000-000000000004", captured_at: "2026-10-22T10:00:00Z" },
  };
  it("push request validates and ids must be uuids", () => {
    expect(validatePushRequest({ project_id: uuid, changes: [change] }).ok).toBe(true);
    const r = validatePushRequest({ project_id: uuid, changes: [{ ...change, layer_id: "lyr_farms" }] });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors[0]).toMatchObject({ field: "changes.0.layer_id", code: "format" });
  });
  it("update requires changed_fields; create requires base_version null", () => {
    const r1 = validatePushRequest({ project_id: uuid, changes: [{ ...change, op: "update", base_version: 3 }] });
    expect(r1.ok).toBe(false);
    if (!r1.ok) expect(r1.errors.map((e) => e.field)).toContain("changes.0.changed_fields");
    const r2 = validatePushRequest({ project_id: uuid, changes: [{ ...change, base_version: 1 }] });
    expect(r2.ok).toBe(false);
  });
  it("push and pull responses validate", () => {
    expect(
      validatePushResponse({ results: [{ change_id: uuid, status: "accepted", feature: { id: uuid, version: 1 } }], last_seq: 10 }).ok,
    ).toBe(true);
    expect(
      validatePullResponse({
        items: [{ seq: 1, entity: "feature", id: uuid, layer_id: uuid, version: 1, deleted: false }],
        next_cursor: 1,
        has_more: false,
        config_version: 3,
      }).ok,
    ).toBe(true);
  });
});
