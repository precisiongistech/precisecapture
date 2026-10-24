/** Cross-field rules a JSON Schema cannot express (capture-profile-resolution.md). */
import type { ValidationIssue } from "../validate.js";

export interface SemanticsContext {
  geometryType?: "point" | "line" | "polygon" | "none" | null;
  layerKeys?: readonly string[] | null;
  /** Keys of the project's layers with role 'reference'; enables the `not_reference` rule. */
  referenceLayerKeys?: readonly string[] | null;
}

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => v !== null && typeof v === "object" && !Array.isArray(v);

const LINE_OR_POLYGON_ONLY = ["stream", "snapping", "trace", "autoClose"] as const;
const LAYER_REF_PATHS = [
  "snapping.layers",
  "trace.layers",
  "validation.topology.noOverlapWith",
  "validation.topology.noGapsWith",
] as const;

function getPath(obj: Obj, path: string): unknown {
  let cur: unknown = obj;
  for (const part of path.split(".")) {
    if (!isObj(cur)) return undefined;
    cur = cur[part];
  }
  return cur;
}

export function validateCaptureProfileSemantics(
  profile: Record<string, unknown>,
  context: SemanticsContext = {},
): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  const push = (field: string, code: string, message: string): void => {
    issues.push({ field, code, message });
  };

  const modes = profile.modes;
  if (isObj(modes) && Array.isArray(modes.allowed) && typeof modes.default === "string") {
    if (!modes.allowed.includes(modes.default)) {
      push("modes.default", "not_allowed", `Default mode '${modes.default}' is not in modes.allowed`);
    }
  }

  const stream = profile.stream;
  if (isObj(stream)) {
    const meters = stream.intervalMeters;
    const seconds = stream.intervalSeconds;
    if (meters !== null && meters !== undefined && seconds !== null && seconds !== undefined) {
      push("stream.intervalSeconds", "exclusive", "Set either intervalMeters or intervalSeconds, not both");
    }
    const allowed = stream.allowedIntervalsMeters;
    if (typeof meters === "number" && Array.isArray(allowed) && !allowed.includes(meters)) {
      push("stream.intervalMeters", "not_allowed", `${meters} m is not one of allowedIntervalsMeters`);
    }
  }

  const geometry = context.geometryType ?? (typeof profile.geometryType === "string" ? profile.geometryType : null);
  if (geometry === "point" || geometry === "none") {
    for (const key of LINE_OR_POLYGON_ONLY) {
      if (profile[key] !== undefined) {
        push(key, "geometry", `${key} applies only to line and polygon layers`);
      }
    }
  }

  if (context.layerKeys) {
    const known = new Set(context.layerKeys);
    for (const path of LAYER_REF_PATHS) {
      const refs = getPath(profile, path);
      if (!Array.isArray(refs)) continue;
      refs.forEach((ref, i) => {
        if (ref !== "self" && !known.has(String(ref))) {
          push(`${path}.${i}`, "unknown_layer", `Layer '${String(ref)}' does not exist in this project`);
        }
      });
    }
  }

  const validation = profile.validation;
  if (isObj(validation)) {
    const rules = validation.spatialRules;
    if (Array.isArray(rules) && (context.layerKeys || context.referenceLayerKeys)) {
      const known = new Set([...(context.layerKeys ?? []), ...(context.referenceLayerKeys ?? [])]);
      const reference = context.referenceLayerKeys ? new Set(context.referenceLayerKeys) : null;
      rules.forEach((rule, i) => {
        if (!isObj(rule) || typeof rule.referenceLayer !== "string") return;
        const field = `validation.spatialRules.${i}.referenceLayer`;
        if (!known.has(rule.referenceLayer)) {
          push(field, "unknown_layer", `Layer '${rule.referenceLayer}' does not exist in this project`);
        } else if (reference && !reference.has(rule.referenceLayer)) {
          push(field, "not_reference", `Layer '${rule.referenceLayer}' is not a reference layer`);
        }
      });
    }
    const min = validation.minAreaSqm;
    const max = validation.maxAreaSqm;
    if (typeof min === "number" && typeof max === "number" && max < min) {
      push("validation.maxAreaSqm", "range", "maxAreaSqm must not be below minAreaSqm");
    }
  }

  return issues;
}
