/**
 * Phone-sized preview of a layer's form, driven by the schema document and the shared evaluator:
 * relevant hides fields, calculate recomputes, constraint and required show errors as the phone would.
 */
import { evaluate, type Value } from "@precisecapture/schema";
import { useMemo, useState } from "react";

import { Input, Select } from "@/components/ui";
import {
  labelText,
  type FieldDef,
  type Option,
  type SchemaDoc,
} from "@/features/layers/AttributeBuilder";

type Values = Record<string, unknown>;

function ctx(values: Values, self?: unknown) {
  const now = new Date();
  return {
    values,
    self,
    now: now.toISOString(),
    today: now.toISOString().slice(0, 10),
    geomAreaM2: 12_345.6,
    geomLengthM: 445.2,
  };
}

function safeEval(expr: string | undefined, values: Values, self?: unknown): Value | undefined {
  if (!expr) return undefined;
  try {
    return evaluate(expr, ctx(values, self));
  } catch {
    return undefined;
  }
}

export function isRelevant(f: FieldDef, values: Values): boolean {
  const r = safeEval(f.relevant, values);
  return r === undefined || r === null || !!r;
}

export function fieldError(f: FieldDef, values: Values): string | null {
  const v = values[f.key];
  const empty = v === undefined || v === null || v === "" || (Array.isArray(v) && v.length === 0);
  const required =
    f.required === true || (typeof f.required === "string" && !!safeEval(f.required, values));
  if (required && empty) return "Required";
  if (!empty && f.constraint) {
    const ok = safeEval(f.constraint, values, v);
    if (ok === false) return labelText(f.constraintMessage) || "Constraint not met";
  }
  return null;
}

export function FormPreview({ schema, geometryType }: { schema: SchemaDoc; geometryType: string }) {
  const [values, setValues] = useState<Values>({});
  const computed = useMemo(() => {
    const out: Values = { ...values };
    for (const f of schema.fields) {
      if (f.type === "calculate" && f.expression) {
        const v = safeEval(f.expression, out);
        out[f.key] = v === undefined ? null : v;
      }
    }
    return out;
  }, [schema.fields, values]);
  const set = (k: string, v: unknown) => setValues((prev) => ({ ...prev, [k]: v }));

  return (
    <div className="mx-auto w-[320px] rounded-[2rem] border-8 border-neutral-800 bg-white shadow-xl">
      <div className="h-6 rounded-t-[1.5rem] bg-neutral-800" />
      <div className="max-h-[560px] space-y-3 overflow-y-auto p-3 text-sm">
        <div className="text-xs text-neutral-500">
          {labelText(schema.title) || "New record"} ·{" "}
          {geometryType === "none" ? "no geometry" : `${geometryType} captured`}
        </div>
        {schema.fields.map((f) => (
          <PreviewField
            key={f.key}
            field={f}
            values={computed}
            lists={schema.lists ?? {}}
            onChange={set}
          />
        ))}
        <button
          type="button"
          className="w-full rounded-md bg-brand-600 py-2 font-medium text-white"
        >
          Save
        </button>
      </div>
    </div>
  );
}

function options(f: FieldDef, lists: Record<string, Option[]>, values: Values): Option[] {
  let opts: Option[] = Array.isArray(f.options)
    ? f.options
    : typeof f.options === "string"
      ? (lists[f.options.replace(/^list:/, "")] ?? [])
      : [];
  if (f.choiceFilterParent) {
    const parent = values[f.choiceFilterParent];
    if (parent !== undefined && parent !== null && parent !== "") {
      opts = opts.filter((o) => {
        const filter = (o as Option & { filter?: Record<string, unknown> }).filter;
        return !filter || String(filter[f.choiceFilterParent!]) === String(parent);
      });
    }
  }
  return opts;
}

function PreviewField({
  field: f,
  values,
  lists,
  onChange,
}: {
  field: FieldDef;
  values: Values;
  lists: Record<string, Option[]>;
  onChange: (k: string, v: unknown) => void;
}) {
  if (!isRelevant(f, values)) return null;
  const error = fieldError(f, values);
  const label = (
    <span className="block text-xs font-medium text-neutral-700">
      {labelText(f.label) || f.key}
      {f.required === true && <span className="text-red-600"> *</span>}
    </span>
  );
  const v = values[f.key];
  const hint = f.hint ? (
    <span className="block text-[11px] text-neutral-500">{labelText(f.hint)}</span>
  ) : null;
  const err = error ? <span className="block text-[11px] text-red-600">{error}</span> : null;
  switch (f.type) {
    case "note":
      return <p className="text-xs text-neutral-600">{labelText(f.label)}</p>;
    case "group":
      return (
        <fieldset className="rounded-md border border-neutral-200 p-2">
          <legend className="px-1 text-xs font-medium">{labelText(f.label)}</legend>
          {(f.fields ?? []).map((c) => (
            <PreviewField key={c.key} field={c} values={values} lists={lists} onChange={onChange} />
          ))}
        </fieldset>
      );
    case "repeat":
      return (
        <div className="rounded-md border border-dashed border-neutral-300 p-2 text-xs text-neutral-600">
          {labelText(f.label)}: repeating group ({(f.fields ?? []).length} fields)
        </div>
      );
    case "calculate":
      return (
        <div>
          {label}
          <div className="rounded-md bg-neutral-100 px-2 py-1 font-mono text-xs">
            {v === null || v === undefined ? "—" : String(v)}
          </div>
        </div>
      );
    case "select_one":
    case "yes_no": {
      const opts =
        f.type === "yes_no"
          ? [
              { value: "yes", label: "Yes" },
              { value: "no", label: "No" },
            ]
          : options(f, lists, values);
      return (
        <div>
          {label}
          <Select
            aria-label={labelText(f.label) || f.key}
            value={String(v ?? "")}
            onChange={(e) => onChange(f.key, e.target.value || null)}
          >
            <option value="">—</option>
            {opts.map((o) => (
              <option key={o.value} value={o.value}>
                {labelText(o.label)}
              </option>
            ))}
          </Select>
          {hint}
          {err}
        </div>
      );
    }
    case "select_many": {
      const opts = options(f, lists, values);
      const arr = Array.isArray(v) ? (v as string[]) : [];
      return (
        <div>
          {label}
          <div className="flex flex-wrap gap-2">
            {opts.map((o) => (
              <label key={o.value} className="flex items-center gap-1 text-xs">
                <input
                  type="checkbox"
                  checked={arr.includes(o.value)}
                  onChange={(e) =>
                    onChange(
                      f.key,
                      e.target.checked ? [...arr, o.value] : arr.filter((x) => x !== o.value),
                    )
                  }
                />
                {labelText(o.label)}
              </label>
            ))}
          </div>
          {err}
        </div>
      );
    }
    case "photo":
    case "audio":
    case "video":
    case "file":
    case "signature":
      return (
        <div>
          {label}
          <div className="rounded-md border border-dashed border-neutral-300 p-3 text-center text-xs text-neutral-500">
            {f.type} ({f.min ?? 0}–{f.max ?? "∞"})
          </div>
          {err}
        </div>
      );
    case "geopoint":
      return (
        <div>
          {label}
          <div className="rounded-md border border-dashed border-neutral-300 p-3 text-center text-xs text-neutral-500">
            GPS point
          </div>
        </div>
      );
    case "relation":
      return (
        <div>
          {label}
          <Input
            placeholder={`Choose from ${f.relation?.layer ?? "…"}`}
            value={String(v ?? "")}
            onChange={(e) => onChange(f.key, e.target.value || null)}
          />
          {err}
        </div>
      );
    case "number":
    case "integer":
    case "decimal":
      return (
        <div>
          {label}
          <Input
            aria-label={labelText(f.label) || f.key}
            type="number"
            value={String(v ?? "")}
            onChange={(e) => onChange(f.key, e.target.value === "" ? null : Number(e.target.value))}
          />
          {hint}
          {err}
        </div>
      );
    case "date":
    case "time":
    case "datetime":
      return (
        <div>
          {label}
          <Input
            type={f.type === "datetime" ? "datetime-local" : f.type}
            value={String(v ?? "")}
            onChange={(e) => onChange(f.key, e.target.value || null)}
          />
          {err}
        </div>
      );
    default:
      return (
        <div>
          {label}
          <Input
            aria-label={labelText(f.label) || f.key}
            value={String(v ?? "")}
            onChange={(e) => onChange(f.key, e.target.value || null)}
          />
          {hint}
          {err}
        </div>
      );
  }
}
