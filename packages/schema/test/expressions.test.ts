import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { ExpressionParseError, evaluate, parse, referencedFields, validateExpression, type EvalContext } from "../src/index.js";

interface Vector {
  name: string;
  expr: string;
  context: Record<string, unknown> & { values: Record<string, unknown> };
  expect?: unknown;
  expectError?: "parse";
}
interface Vectors {
  defaults: { now: string; today: string };
  cases: Vector[];
}

const vectors = JSON.parse(readFileSync(join(__dirname, "..", "test-vectors", "expressions.json"), "utf8")) as Vectors;

function contextFromVector(c: Vector["context"]): EvalContext {
  const lookups = (c.lookups as Record<string, unknown> | undefined) ?? {};
  return {
    values: c.values,
    fields: (c.fields as string[] | undefined) ?? null,
    self: c.self,
    repeatItem: (c.repeatItem as Record<string, unknown> | undefined) ?? null,
    now: (c.now as string | undefined) ?? vectors.defaults.now,
    today: (c.today as string | undefined) ?? vectors.defaults.today,
    geomAreaM2: (c.geomAreaM2 as number | null | undefined) ?? null,
    geomLengthM: (c.geomLengthM as number | null | undefined) ?? null,
    lookup: (layer, field) => lookups[`${layer}.${field}`] ?? null,
    ghanapostGps: (c.ghanapostGps as string | null | undefined) ?? null,
  };
}

describe("shared expression vectors", () => {
  it("has at least 40 cases", () => {
    expect(vectors.cases.length).toBeGreaterThanOrEqual(40);
  });
  for (const v of vectors.cases) {
    it(v.name, () => {
      const ctx = contextFromVector(v.context);
      if (v.expectError === "parse") {
        expect(() => parse(v.expr, ctx.fields)).toThrow(ExpressionParseError);
        return;
      }
      expect(evaluate(v.expr, ctx)).toEqual(v.expect);
    });
  }
});

describe("helpers", () => {
  it("referencedFields lists root keys once, in order", () => {
    expect(referencedFields("${crop} = 'other' and ${other_crop} != '' or ${crop} = 'x'")).toEqual(["crop", "other_crop"]);
    expect(referencedFields("sum(${occupants.age}) + geom_area()")).toEqual(["occupants"]);
    expect(referencedFields(". = 'yes'")).toEqual([]);
  });
  it("validateExpression returns the error position for the form builder", () => {
    expect(validateExpression("${crop} = 'x'", ["crop"])).toBeNull();
    const err = validateExpression("${crop} = 'x", ["crop"]);
    expect(err).toMatchObject({ position: 10 });
    expect(validateExpression("${nope} = 1", ["crop"])?.message).toContain("Unknown field");
  });
});
