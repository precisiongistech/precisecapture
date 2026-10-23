/**
 * JSON Schema validation for the shared contract.
 *
 * Two modes (ENGINEERING_NOTES.md §4):
 * - "strict": the server's view; unknown keys are errors so typos are caught on save.
 * - "lenient": the apps' view; unknown keys are removed so an older app never rejects a
 *   newer server's document. Validates a deep copy and returns the cleaned data.
 */
import Ajv2020, { type ErrorObject, type ValidateFunction } from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

import captureProfileSchema from "../schemas/capture-profile.schema.json";
import layerSchemaSchema from "../schemas/layer-schema.schema.json";
import syncSchema from "../schemas/sync.schema.json";
import type {
  CaptureProfile,
  LayerSchema,
  PullResponse,
  PushRequest,
  PushResponse,
} from "./types.js";

export type ValidationMode = "strict" | "lenient";

export interface ValidationIssue {
  /** JSON-pointer-ish dotted path to the offending value, e.g. "fields.2.options". */
  field: string | null;
  code: string;
  message: string;
}

export type ValidationResult<T> =
  | { ok: true; data: T; errors: [] }
  | { ok: false; data: null; errors: ValidationIssue[] };

type SyncDoc = typeof syncSchema & { oneOf: Array<Record<string, unknown> & { title: string }> };

/** The sync file is a oneOf of three titled documents; each becomes its own schema. */
function syncBranch(title: string): Record<string, unknown> {
  const doc = syncSchema as SyncDoc;
  const branch = doc.oneOf.find((b) => b.title === title);
  if (!branch) throw new Error(`sync.schema.json has no document titled ${title}`);
  return {
    $schema: doc.$schema,
    $id: `${doc.$id.replace(/\.json$/, "")}/${title.toLowerCase()}.json`,
    $defs: doc.$defs,
    ...branch,
  };
}

const schemas = {
  layerSchema: layerSchemaSchema as Record<string, unknown>,
  captureProfile: captureProfileSchema as Record<string, unknown>,
  pushRequest: syncBranch("PushRequest"),
  pushResponse: syncBranch("PushResponse"),
  pullResponse: syncBranch("PullResponse"),
} as const;

type SchemaName = keyof typeof schemas;

function makeAjv(mode: ValidationMode): Ajv2020 {
  const ajv = new Ajv2020({
    allErrors: true,
    strict: false,
    useDefaults: false,
    // `true` strips extra keys only where the schema says additionalProperties: false
    // ("all" would also strip keys inside if/then subschemas that list a single property).
    removeAdditional: mode === "lenient",
  });
  addFormats(ajv);
  return ajv;
}

const compiled: Record<ValidationMode, Partial<Record<SchemaName, ValidateFunction>>> = {
  strict: {},
  lenient: {},
};
const ajvs: Partial<Record<ValidationMode, Ajv2020>> = {};

function validator(name: SchemaName, mode: ValidationMode): ValidateFunction {
  const cache = compiled[mode];
  let fn = cache[name];
  if (!fn) {
    ajvs[mode] ??= makeAjv(mode);
    fn = ajvs[mode]!.compile(schemas[name]);
    cache[name] = fn;
  }
  return fn;
}

export function formatAjvErrors(errors: ErrorObject[] | null | undefined): ValidationIssue[] {
  const out: ValidationIssue[] = [];
  for (const e of errors ?? []) {
    let path = e.instancePath.replace(/^\//, "").replace(/\//g, ".");
    if (e.keyword === "additionalProperties") {
      const extra = (e.params as { additionalProperty?: string }).additionalProperty;
      path = path ? `${path}.${extra}` : String(extra);
    }
    if (e.keyword === "required") {
      const missing = (e.params as { missingProperty?: string }).missingProperty;
      path = path ? `${path}.${missing}` : String(missing);
    }
    out.push({ field: path || null, code: e.keyword, message: e.message ?? "invalid" });
  }
  // Ajv reports the same failure several times for if/then and oneOf; keep the first per field+code.
  const seen = new Set<string>();
  return out.filter((i) => {
    const k = `${i.field}|${i.code}|${i.message}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

function run<T>(name: SchemaName, data: unknown, mode: ValidationMode): ValidationResult<T> {
  const subject = mode === "lenient" ? (JSON.parse(JSON.stringify(data)) as unknown) : data;
  const fn = validator(name, mode);
  if (fn(subject)) return { ok: true, data: subject as T, errors: [] };
  return { ok: false, data: null, errors: formatAjvErrors(fn.errors) };
}

export function validateLayerSchema(data: unknown, mode: ValidationMode = "strict"): ValidationResult<LayerSchema> {
  return run("layerSchema", data, mode);
}

export function validateCaptureProfile(data: unknown, mode: ValidationMode = "strict"): ValidationResult<CaptureProfile> {
  return run("captureProfile", data, mode);
}

export function validatePushRequest(data: unknown, mode: ValidationMode = "strict"): ValidationResult<PushRequest> {
  return run("pushRequest", data, mode);
}

export function validatePushResponse(data: unknown, mode: ValidationMode = "strict"): ValidationResult<PushResponse> {
  return run("pushResponse", data, mode);
}

export function validatePullResponse(data: unknown, mode: ValidationMode = "strict"): ValidationResult<PullResponse> {
  return run("pullResponse", data, mode);
}

/** The raw JSON Schemas, for tooling that wants them (form builders, OpenAPI examples). */
export const jsonSchemas = {
  layerSchema: layerSchemaSchema,
  captureProfile: captureProfileSchema,
  sync: syncSchema,
} as const;
