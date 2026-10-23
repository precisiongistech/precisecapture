import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { resolveCaptureProfile, validateCaptureProfileSemantics, type SemanticsContext } from "../src/index.js";

const load = <T>(name: string): T => JSON.parse(readFileSync(join(__dirname, "..", "test-vectors", name), "utf8")) as T;

interface ResolutionCase {
  name: string;
  org: Record<string, unknown> | null;
  project: Record<string, unknown> | null;
  layer: Record<string, unknown> | null;
  collector: Record<string, unknown> | null;
  expect: Record<string, unknown>;
}
interface SemanticsCase {
  name: string;
  profile: Record<string, unknown>;
  geometryType?: SemanticsContext["geometryType"];
  layerKeys?: string[];
  expectErrors: Array<{ field: string; code: string }>;
}

describe("resolveCaptureProfile vectors", () => {
  for (const c of load<{ cases: ResolutionCase[] }>("capture-profile-resolution.json").cases) {
    it(c.name, () => {
      expect(resolveCaptureProfile(c.org, c.project, c.layer, c.collector)).toEqual(c.expect);
    });
  }
  it("does not mutate its inputs", () => {
    const org = { gps: { averaging: { enabled: true, locked: true } } };
    const layer = { gps: { averaging: { enabled: false } } };
    const collector = { gps: { maxAccuracyMeters: 1 } };
    resolveCaptureProfile(org, null, layer, collector);
    expect(org).toEqual({ gps: { averaging: { enabled: true, locked: true } } });
    expect(layer).toEqual({ gps: { averaging: { enabled: false } } });
    expect(collector).toEqual({ gps: { maxAccuracyMeters: 1 } });
  });
});

describe("validateCaptureProfileSemantics vectors", () => {
  for (const c of load<{ cases: SemanticsCase[] }>("capture-profile-semantics.json").cases) {
    it(c.name, () => {
      const issues = validateCaptureProfileSemantics(c.profile, { geometryType: c.geometryType, layerKeys: c.layerKeys });
      const got = issues.map((i) => `${i.field}|${i.code}`).sort();
      const want = c.expectErrors.map((e) => `${e.field}|${e.code}`).sort();
      expect(got).toEqual(want);
      for (const i of issues) expect(i.message).toBeTruthy();
    });
  }
});
