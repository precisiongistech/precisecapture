/**
 * Drag-and-drop attribute list (the form) with a per-field editor. Expressions are validated live
 * with the shared evaluator (validateExpression) against the keys of the other fields.
 */
import {
  closestCenter,
  DndContext,
  type DragEndEvent,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { validateExpression } from "@precisecapture/schema";
import { useMemo, useState } from "react";

import { Badge, Button, Field as FormField, Input, Select, cx } from "@/components/ui";

export type Option = { value: string; label: string | Record<string, string> };
export type FieldDef = {
  key: string;
  type: string;
  label?: string | Record<string, string>;
  hint?: string | Record<string, string>;
  required?: boolean | string;
  relevant?: string;
  constraint?: string;
  constraintMessage?: string | Record<string, string>;
  expression?: string;
  readonly?: boolean;
  sticky?: boolean;
  unique?: boolean;
  personalData?: boolean;
  options?: string | Option[];
  choiceFilterParent?: string;
  validation?: {
    min?: number;
    max?: number;
    minLength?: number;
    maxLength?: number;
    pattern?: string;
  };
  min?: number;
  max?: number;
  maxDimensionPx?: number;
  stamp?: boolean;
  relation?: { layer: string; displayField?: string; allowCreateInline?: boolean };
  fields?: FieldDef[];
  default?: unknown;
};
export type SchemaDoc = {
  fields: FieldDef[];
  lists?: Record<string, Option[]>;
  title?: string | Record<string, string>;
};

export const FIELD_TYPES = [
  "text",
  "number",
  "integer",
  "decimal",
  "date",
  "time",
  "datetime",
  "select_one",
  "select_many",
  "yes_no",
  "phone",
  "email",
  "photo",
  "audio",
  "video",
  "file",
  "signature",
  "barcode",
  "calculate",
  "note",
  "repeat",
  "group",
  "geopoint",
  "relation",
] as const;

export function labelText(l: string | Record<string, string> | undefined): string {
  if (!l) return "";
  if (typeof l === "string") return l;
  return l.en ?? Object.values(l)[0] ?? "";
}

function newKey(base: string, taken: Set<string>): string {
  let k =
    base
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .replace(/^[^a-z]/, "f$&") || "field";
  k = k.slice(0, 60);
  let candidate = k;
  let n = 2;
  while (taken.has(candidate)) candidate = `${k}_${n++}`;
  return candidate;
}

export function AttributeBuilder({
  value,
  onChange,
  layerKeys,
  readOnly = false,
}: {
  value: SchemaDoc;
  onChange: (next: SchemaDoc) => void;
  layerKeys: string[];
  readOnly?: boolean;
}) {
  const [selected, setSelected] = useState<string | null>(value.fields[0]?.key ?? null);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));
  const keys = useMemo(() => value.fields.map((f) => f.key), [value.fields]);
  const current = value.fields.find((f) => f.key === selected) ?? null;

  function update(fields: FieldDef[]) {
    onChange({ ...value, fields });
  }
  function onDragEnd(e: DragEndEvent) {
    if (!e.over || e.active.id === e.over.id) return;
    const from = keys.indexOf(String(e.active.id));
    const to = keys.indexOf(String(e.over.id));
    update(arrayMove(value.fields, from, to));
  }
  function add(type: string) {
    const key = newKey(type === "calculate" ? "calc" : type, new Set(keys));
    const field: FieldDef = { key, type, label: { en: key.replace(/_/g, " ") } };
    if (type === "select_one" || type === "select_many")
      field.options = [{ value: "option_1", label: { en: "Option 1" } }];
    if (type === "calculate") field.expression = "1";
    if (type === "relation") field.relation = { layer: layerKeys[0] ?? "" };
    if (type === "repeat" || type === "group")
      field.fields = [{ key: "item", type: "text", label: { en: "Item" } }];
    if (type === "photo")
      Object.assign(field, { min: 1, max: 4, maxDimensionPx: 1920, stamp: true });
    update([...value.fields, field]);
    setSelected(key);
  }
  function replace(key: string, next: FieldDef) {
    update(value.fields.map((f) => (f.key === key ? next : f)));
    if (next.key !== key) setSelected(next.key);
  }
  function remove(key: string) {
    update(value.fields.filter((f) => f.key !== key));
    if (selected === key) setSelected(null);
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
      <div>
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
          <SortableContext items={keys} strategy={verticalListSortingStrategy}>
            <ul className="space-y-1" aria-label="Attributes">
              {value.fields.map((f) => (
                <SortableRow
                  key={f.key}
                  field={f}
                  selected={f.key === selected}
                  onSelect={() => setSelected(f.key)}
                  disabled={readOnly}
                />
              ))}
            </ul>
          </SortableContext>
        </DndContext>
        {value.fields.length === 0 && (
          <p className="text-sm text-neutral-500">No attributes yet. Add one below.</p>
        )}
        {!readOnly && (
          <div className="mt-3 flex items-center gap-2">
            <Select
              aria-label="Add attribute of type"
              defaultValue=""
              onChange={(e) => {
                const t = e.target.value;
                if (t) {
                  add(t);
                  e.target.value = "";
                }
              }}
              className="w-56"
            >
              <option value="">+ Add attribute…</option>
              {FIELD_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </Select>
          </div>
        )}
      </div>
      <div>
        {current ? (
          <FieldEditor
            field={current}
            siblings={value.fields.filter((f) => f.key !== current.key)}
            lists={value.lists ?? {}}
            layerKeys={layerKeys}
            readOnly={readOnly}
            onChange={(next) => replace(current.key, next)}
            onRemove={() => remove(current.key)}
            onListsChange={(lists) => onChange({ ...value, lists })}
          />
        ) : (
          <p className="text-sm text-neutral-500">Select an attribute to edit it.</p>
        )}
      </div>
    </div>
  );
}

function SortableRow({
  field,
  selected,
  onSelect,
  disabled,
}: {
  field: FieldDef;
  selected: boolean;
  onSelect: () => void;
  disabled: boolean;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: field.key,
    disabled,
  });
  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cx(
        "flex cursor-pointer items-center gap-2 rounded-md border px-2 py-1.5 text-sm",
        selected
          ? "border-brand-500 bg-brand-50"
          : "border-neutral-200 bg-white hover:bg-neutral-50",
        isDragging && "opacity-60",
      )}
      onClick={onSelect}
    >
      <button
        type="button"
        className="cursor-grab text-neutral-400"
        aria-label={`Drag ${field.key}`}
        {...attributes}
        {...listeners}
      >
        ⋮⋮
      </button>
      <span className="flex-1 truncate">{labelText(field.label) || field.key}</span>
      <span className="font-mono text-xs text-neutral-500">{field.key}</span>
      <Badge>{field.type}</Badge>
      {field.required === true && <Badge tone="amber">required</Badge>}
    </li>
  );
}

function ExprInput({
  label,
  value,
  siblings,
  onChange,
  readOnly,
  hint,
}: {
  label: string;
  value: string | undefined;
  siblings: FieldDef[];
  onChange: (v: string | undefined) => void;
  readOnly: boolean;
  hint?: string;
}) {
  const keys = siblings.map((s) => s.key);
  const err = value ? validateExpression(value, [...keys, "self"]) : null;
  return (
    <FormField
      label={label}
      error={err?.message}
      hint={hint ?? `Fields: ${keys.map((k) => `\${${k}}`).join(" ") || "—"}`}
    >
      <Input
        value={value ?? ""}
        disabled={readOnly}
        invalid={!!err}
        placeholder="e.g. ${crop} = 'other'"
        onChange={(e) => onChange(e.target.value || undefined)}
        className="font-mono text-xs"
      />
    </FormField>
  );
}

function FieldEditor({
  field,
  siblings,
  lists,
  layerKeys,
  readOnly,
  onChange,
  onRemove,
  onListsChange,
}: {
  field: FieldDef;
  siblings: FieldDef[];
  lists: Record<string, Option[]>;
  layerKeys: string[];
  readOnly: boolean;
  onChange: (f: FieldDef) => void;
  onRemove: () => void;
  onListsChange: (lists: Record<string, Option[]>) => void;
}) {
  const set = <K extends keyof FieldDef>(k: K, v: FieldDef[K]) => {
    const next = { ...field, [k]: v };
    if (v === undefined || v === "" || v === false) delete (next as Record<string, unknown>)[k];
    onChange(next);
  };
  const keyTaken = siblings.some((s) => s.key === field.key);
  const isSelect = field.type === "select_one" || field.type === "select_many";
  const isMedia = ["photo", "audio", "video", "file", "signature"].includes(field.type);
  const isNumeric = ["number", "integer", "decimal"].includes(field.type);
  const isText = ["text", "phone", "email", "barcode"].includes(field.type);
  const inlineOptions = Array.isArray(field.options) ? field.options : null;
  const listName = typeof field.options === "string" ? field.options.replace(/^list:/, "") : null;

  return (
    <div className="space-y-3 rounded-md border border-neutral-200 bg-white p-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <FormField
          label="Key"
          error={keyTaken ? "Key already used" : undefined}
          hint="Stable forever; lowercase letters, digits, _"
        >
          <Input
            value={field.key}
            disabled={readOnly}
            pattern="^[a-z][a-z0-9_]{0,62}$"
            invalid={keyTaken}
            onChange={(e) => set("key", e.target.value)}
          />
        </FormField>
        <FormField label="Type">
          <Select
            value={field.type}
            disabled={readOnly}
            onChange={(e) => set("type", e.target.value)}
          >
            {FIELD_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label="Label">
          <Input
            value={labelText(field.label)}
            disabled={readOnly}
            onChange={(e) => set("label", { en: e.target.value })}
          />
        </FormField>
        <FormField label="Hint">
          <Input
            value={labelText(field.hint)}
            disabled={readOnly}
            onChange={(e) => set("hint", e.target.value ? { en: e.target.value } : undefined)}
          />
        </FormField>
      </div>
      {field.type !== "calculate" && field.type !== "note" && field.type !== "group" && (
        <div className="flex flex-wrap gap-4 text-sm">
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={field.required === true}
              disabled={readOnly || typeof field.required === "string"}
              onChange={(e) => set("required", e.target.checked ? true : undefined)}
            />
            Required
          </label>
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={!!field.sticky}
              disabled={readOnly}
              onChange={(e) => set("sticky", e.target.checked || undefined)}
            />
            Sticky (carry value to next record)
          </label>
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={!!field.unique}
              disabled={readOnly}
              onChange={(e) => set("unique", e.target.checked || undefined)}
            />
            Unique
          </label>
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={!!field.personalData}
              disabled={readOnly}
              onChange={(e) => set("personalData", e.target.checked || undefined)}
            />
            Personal data
          </label>
        </div>
      )}
      {isSelect && (
        <div className="space-y-2 rounded-md bg-neutral-50 p-3">
          <div className="flex items-center gap-2 text-sm">
            <span className="font-medium">Options</span>
            <Select
              value={listName ? `list:${listName}` : "inline"}
              disabled={readOnly}
              className="w-56"
              onChange={(e) => {
                const v = e.target.value;
                if (v === "inline")
                  set(
                    "options",
                    inlineOptions ?? [{ value: "option_1", label: { en: "Option 1" } }],
                  );
                else if (v === "new") {
                  const name = newKey("list", new Set(Object.keys(lists)));
                  onListsChange({
                    ...lists,
                    [name]: [{ value: "option_1", label: { en: "Option 1" } }],
                  });
                  set("options", `list:${name}`);
                } else set("options", v);
              }}
            >
              <option value="inline">inline options</option>
              {Object.keys(lists).map((l) => (
                <option key={l} value={`list:${l}`}>
                  list: {l}
                </option>
              ))}
              <option value="new">+ new named list…</option>
            </Select>
            <label className="ml-auto flex items-center gap-1">
              Filter by parent
              <Select
                value={field.choiceFilterParent ?? ""}
                disabled={readOnly}
                className="w-40"
                onChange={(e) => set("choiceFilterParent", e.target.value || undefined)}
              >
                <option value="">(none)</option>
                {siblings
                  .filter((s) => s.type === "select_one")
                  .map((s) => (
                    <option key={s.key} value={s.key}>
                      {s.key}
                    </option>
                  ))}
              </Select>
            </label>
          </div>
          <OptionsEditor
            options={inlineOptions ?? (listName ? (lists[listName] ?? []) : [])}
            readOnly={readOnly}
            withFilter={!!field.choiceFilterParent}
            parentKey={field.choiceFilterParent}
            onChange={(opts) =>
              inlineOptions
                ? set("options", opts)
                : listName && onListsChange({ ...lists, [listName]: opts })
            }
          />
        </div>
      )}
      {field.type === "relation" && (
        <FormField label="Related layer" hint="Layer key in this project">
          <Select
            value={field.relation?.layer ?? ""}
            disabled={readOnly}
            onChange={(e) =>
              set("relation", { ...(field.relation ?? { layer: "" }), layer: e.target.value })
            }
          >
            <option value="">— choose —</option>
            {layerKeys.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </Select>
        </FormField>
      )}
      {field.type === "calculate" && (
        <>
          <ExprInput
            label="Expression"
            value={field.expression}
            siblings={siblings}
            readOnly={readOnly}
            onChange={(v) => set("expression", v)}
            hint="e.g. geom_area() div 10000 or if(${crop} = 'other', ${other_crop}, ${crop})"
          />
          <label className="flex items-center gap-1 text-sm">
            <input
              type="checkbox"
              checked={!!field.readonly}
              disabled={readOnly}
              onChange={(e) => set("readonly", e.target.checked || undefined)}
            />
            Read-only on the phone
          </label>
        </>
      )}
      {isNumeric && (
        <div className="grid gap-3 sm:grid-cols-2">
          <FormField label="Minimum">
            <Input
              type="number"
              value={field.validation?.min ?? ""}
              disabled={readOnly}
              onChange={(e) =>
                set("validation", {
                  ...field.validation,
                  min: e.target.value === "" ? undefined : Number(e.target.value),
                })
              }
            />
          </FormField>
          <FormField label="Maximum">
            <Input
              type="number"
              value={field.validation?.max ?? ""}
              disabled={readOnly}
              onChange={(e) =>
                set("validation", {
                  ...field.validation,
                  max: e.target.value === "" ? undefined : Number(e.target.value),
                })
              }
            />
          </FormField>
        </div>
      )}
      {isText && (
        <div className="grid gap-3 sm:grid-cols-3">
          <FormField label="Min length">
            <Input
              type="number"
              value={field.validation?.minLength ?? ""}
              disabled={readOnly}
              onChange={(e) =>
                set("validation", {
                  ...field.validation,
                  minLength: e.target.value === "" ? undefined : Number(e.target.value),
                })
              }
            />
          </FormField>
          <FormField label="Max length">
            <Input
              type="number"
              value={field.validation?.maxLength ?? ""}
              disabled={readOnly}
              onChange={(e) =>
                set("validation", {
                  ...field.validation,
                  maxLength: e.target.value === "" ? undefined : Number(e.target.value),
                })
              }
            />
          </FormField>
          <FormField label="Pattern (regex)">
            <Input
              value={field.validation?.pattern ?? ""}
              disabled={readOnly}
              className="font-mono text-xs"
              onChange={(e) =>
                set("validation", { ...field.validation, pattern: e.target.value || undefined })
              }
            />
          </FormField>
        </div>
      )}
      {isMedia && (
        <div className="grid gap-3 sm:grid-cols-3">
          <FormField label="Min count">
            <Input
              type="number"
              value={field.min ?? ""}
              disabled={readOnly}
              onChange={(e) =>
                set("min", e.target.value === "" ? undefined : Number(e.target.value))
              }
            />
          </FormField>
          <FormField label="Max count">
            <Input
              type="number"
              value={field.max ?? ""}
              disabled={readOnly}
              onChange={(e) =>
                set("max", e.target.value === "" ? undefined : Number(e.target.value))
              }
            />
          </FormField>
          {field.type === "photo" && (
            <FormField label="Max dimension (px)">
              <Input
                type="number"
                value={field.maxDimensionPx ?? ""}
                disabled={readOnly}
                onChange={(e) =>
                  set("maxDimensionPx", e.target.value === "" ? undefined : Number(e.target.value))
                }
              />
            </FormField>
          )}
        </div>
      )}
      {field.type !== "note" && field.type !== "group" && (
        <>
          <ExprInput
            label="Show when (relevant)"
            value={field.relevant}
            siblings={siblings}
            readOnly={readOnly}
            onChange={(v) => set("relevant", v)}
          />
          {field.type !== "calculate" && (
            <>
              <ExprInput
                label="Constraint (use . for this field's value)"
                value={field.constraint}
                siblings={siblings}
                readOnly={readOnly}
                onChange={(v) => set("constraint", v)}
                hint="e.g. . >= 1950 and . <= 2027"
              />
              {field.constraint && (
                <FormField label="Constraint message">
                  <Input
                    value={labelText(field.constraintMessage)}
                    disabled={readOnly}
                    onChange={(e) =>
                      set("constraintMessage", e.target.value ? { en: e.target.value } : undefined)
                    }
                  />
                </FormField>
              )}
              <ExprInput
                label="Required when (expression, optional)"
                value={typeof field.required === "string" ? field.required : undefined}
                siblings={siblings}
                readOnly={readOnly}
                onChange={(v) => set("required", v ?? (field.required === true ? true : undefined))}
              />
            </>
          )}
        </>
      )}
      {!readOnly && (
        <div className="flex justify-end">
          <Button
            type="button"
            variant="danger"
            size="sm"
            onClick={() => confirm(`Remove attribute "${field.key}"?`) && onRemove()}
          >
            Remove attribute
          </Button>
        </div>
      )}
    </div>
  );
}

function OptionsEditor({
  options,
  onChange,
  readOnly,
  withFilter,
  parentKey,
}: {
  options: Option[];
  onChange: (o: Option[]) => void;
  readOnly: boolean;
  withFilter: boolean;
  parentKey?: string;
}) {
  type Row = Option & { filter?: Record<string, string> };
  const rows = options as Row[];
  return (
    <div className="space-y-1">
      {rows.map((o, i) => (
        <div key={i} className="flex items-center gap-2">
          <Input
            className="w-40 font-mono text-xs"
            value={o.value}
            disabled={readOnly}
            aria-label="Option value"
            onChange={(e) =>
              onChange(rows.map((r, j) => (j === i ? { ...r, value: e.target.value } : r)))
            }
          />
          <Input
            value={labelText(o.label)}
            disabled={readOnly}
            aria-label="Option label"
            onChange={(e) =>
              onChange(rows.map((r, j) => (j === i ? { ...r, label: { en: e.target.value } } : r)))
            }
          />
          {withFilter && parentKey && (
            <Input
              className="w-36 font-mono text-xs"
              placeholder={`${parentKey} value`}
              value={o.filter?.[parentKey] ?? ""}
              disabled={readOnly}
              aria-label="Parent value"
              onChange={(e) =>
                onChange(
                  rows.map((r, j) =>
                    j === i
                      ? {
                          ...r,
                          filter: e.target.value ? { [parentKey]: e.target.value } : undefined,
                        }
                      : r,
                  ),
                )
              }
            />
          )}
          {!readOnly && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-label="Remove option"
              onClick={() => onChange(rows.filter((_, j) => j !== i))}
            >
              ✕
            </Button>
          )}
        </div>
      ))}
      {!readOnly && (
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={() =>
            onChange([
              ...rows,
              { value: newKey("option", new Set(rows.map((r) => r.value))), label: { en: "" } },
            ])
          }
        >
          + option
        </Button>
      )}
    </div>
  );
}
