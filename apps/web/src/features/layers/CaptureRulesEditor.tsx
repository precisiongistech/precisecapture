/**
 * Capture profile editor: toggles, sliders and a lock icon per lockable object. Partial profiles
 * are fine (org and project levels). Cross-field problems come from the shared semantic checker.
 */
import { validateCaptureProfileSemantics, type CaptureProfile } from "@precisecapture/schema";
import { useMemo } from "react";

import { Alert, Input, Select } from "@/components/ui";

export type PartialProfile = Record<string, unknown> & Partial<CaptureProfile>;

const INTERVALS = [1, 2, 3, 5, 10];
const MODES = ["tap", "gps_vertex", "stream", "hybrid"] as const;

type Obj = Record<string, unknown>;
const obj = (v: unknown): Obj =>
  v && typeof v === "object" && !Array.isArray(v) ? (v as Obj) : {};

export function CaptureRulesEditor({
  value,
  onChange,
  readOnly = false,
  geometryType,
  layerKeys,
  resolved,
}: {
  value: PartialProfile;
  onChange: (next: PartialProfile) => void;
  readOnly?: boolean;
  geometryType: string | null;
  layerKeys: string[];
  /** The effective org -> project -> layer profile, shown as placeholders where this level is silent. */
  resolved?: PartialProfile;
}) {
  const issues = useMemo(
    () =>
      validateCaptureProfileSemantics(value, {
        geometryType: (geometryType as "point" | "line" | "polygon" | "none" | null) ?? undefined,
        layerKeys,
      }),
    [value, geometryType, layerKeys],
  );
  const linear = geometryType === null || geometryType === "line" || geometryType === "polygon";

  function set(path: string, v: unknown) {
    const next = structuredClone(value) as Obj;
    const parts = path.split(".");
    let cur: Obj = next;
    for (const p of parts.slice(0, -1)) {
      cur[p] = obj(cur[p]);
      cur = cur[p] as Obj;
    }
    const last = parts[parts.length - 1]!;
    if (v === undefined || v === "" || v === null) delete cur[last];
    else cur[last] = v;
    // drop empty objects
    for (const p of parts.slice(0, -1)) {
      const o = get(next, parts.slice(0, parts.indexOf(p) + 1).join("."));
      if (o && typeof o === "object" && Object.keys(o as Obj).length === 0)
        set(parts.slice(0, parts.indexOf(p) + 1).join("."), undefined);
    }
    onChange(next as PartialProfile);
  }
  function get(o: unknown, path: string): unknown {
    return path
      .split(".")
      .reduce<unknown>(
        (acc, k) => (acc && typeof acc === "object" ? (acc as Obj)[k] : undefined),
        o,
      );
  }
  const v = (path: string): unknown => get(value, path);
  const r = (path: string): unknown => get(resolved, path);
  const ph = (path: string): string => {
    const x = r(path);
    return x === undefined ? "" : String(x);
  };

  return (
    <div className="space-y-5 text-sm">
      {issues.length > 0 && (
        <Alert>
          <ul className="list-disc pl-4">
            {issues.map((i) => (
              <li key={i.field + i.code}>
                <span className="font-mono text-xs">{i.field}</span>: {i.message}
              </li>
            ))}
          </ul>
        </Alert>
      )}

      <Section
        title="Capture modes"
        lock={v("modes.locked") as boolean | undefined}
        onLock={(l) => set("modes.locked", l)}
        readOnly={readOnly}
      >
        <div className="flex flex-wrap gap-3">
          {MODES.map((m) => {
            const allowed = (v("modes.allowed") as string[] | undefined) ?? [];
            return (
              <label key={m} className="flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={allowed.includes(m)}
                  disabled={readOnly}
                  onChange={(e) =>
                    set(
                      "modes.allowed",
                      e.target.checked ? [...allowed, m] : allowed.filter((x) => x !== m),
                    )
                  }
                />
                {m}
              </label>
            );
          })}
          <label className="ml-4 flex items-center gap-2">
            Default
            <Select
              value={(v("modes.default") as string | undefined) ?? ""}
              disabled={readOnly}
              onChange={(e) => set("modes.default", e.target.value)}
              className="w-36"
            >
              <option value="">(inherit{ph("modes.default") && `: ${ph("modes.default")}`})</option>
              {MODES.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </Select>
          </label>
        </div>
      </Section>

      {linear && (
        <Section
          title="Auto-close polygons"
          lock={v("autoClose.locked") as boolean | undefined}
          onLock={(l) => set("autoClose.locked", l)}
          readOnly={readOnly}
        >
          <Toggle
            label="Enabled"
            value={v("autoClose.enabled") as boolean | undefined}
            inherited={r("autoClose.enabled") as boolean | undefined}
            onChange={(b) => set("autoClose.enabled", b)}
            readOnly={readOnly}
          />
        </Section>
      )}

      {linear && (
        <Section
          title="Streaming"
          lock={v("stream.locked") as boolean | undefined}
          onLock={(l) => set("stream.locked", l)}
          readOnly={readOnly}
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block">
              Interval (metres)
              <Select
                value={String(v("stream.intervalMeters") ?? "")}
                disabled={readOnly}
                onChange={(e) =>
                  set("stream.intervalMeters", e.target.value ? Number(e.target.value) : undefined)
                }
              >
                <option value="">
                  (inherit{ph("stream.intervalMeters") && `: ${ph("stream.intervalMeters")} m`})
                </option>
                {INTERVALS.map((i) => (
                  <option key={i} value={i}>
                    {i} m
                  </option>
                ))}
              </Select>
            </label>
            <div>
              Allowed intervals
              <div className="mt-1 flex gap-3">
                {INTERVALS.map((i) => {
                  const allowed =
                    (v("stream.allowedIntervalsMeters") as number[] | undefined) ?? [];
                  return (
                    <label key={i} className="flex items-center gap-1">
                      <input
                        type="checkbox"
                        checked={allowed.includes(i)}
                        disabled={readOnly}
                        onChange={(e) =>
                          set(
                            "stream.allowedIntervalsMeters",
                            e.target.checked
                              ? [...allowed, i].sort((a, b) => a - b)
                              : allowed.filter((x) => x !== i),
                          )
                        }
                      />
                      {i}
                    </label>
                  );
                })}
              </div>
            </div>
            <Toggle
              label="Pause when stationary"
              value={v("stream.pauseWhenStationary") as boolean | undefined}
              inherited={r("stream.pauseWhenStationary") as boolean | undefined}
              onChange={(b) => set("stream.pauseWhenStationary", b)}
              readOnly={readOnly}
            />
            <Toggle
              label="Keep raw track"
              value={v("stream.keepRawTrack") as boolean | undefined}
              inherited={r("stream.keepRawTrack") as boolean | undefined}
              onChange={(b) => set("stream.keepRawTrack", b)}
              readOnly={readOnly}
            />
            <Num
              label="Skip vertex if accuracy worse than (m)"
              path="stream.skipVertexIfAccuracyWorseThanMeters"
              v={v}
              ph={ph}
              set={set}
              readOnly={readOnly}
            />
            <Toggle
              label="Simplify on close"
              value={v("stream.simplifyOnClose.enabled") as boolean | undefined}
              inherited={r("stream.simplifyOnClose.enabled") as boolean | undefined}
              onChange={(b) => set("stream.simplifyOnClose.enabled", b)}
              readOnly={readOnly}
            />
          </div>
        </Section>
      )}

      <Section
        title="GPS"
        lock={v("gps.locked") as boolean | undefined}
        onLock={(l) => set("gps.locked", l)}
        readOnly={readOnly}
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <Num
            label="Max accuracy (m)"
            path="gps.maxAccuracyMeters"
            v={v}
            ph={ph}
            set={set}
            readOnly={readOnly}
          />
          <label className="block">
            On poor accuracy
            <Select
              value={(v("gps.onPoorAccuracy") as string | undefined) ?? ""}
              disabled={readOnly}
              onChange={(e) => set("gps.onPoorAccuracy", e.target.value || undefined)}
            >
              <option value="">
                (inherit{ph("gps.onPoorAccuracy") && `: ${ph("gps.onPoorAccuracy")}`})
              </option>
              <option value="warn">warn</option>
              <option value="block">block</option>
              <option value="ignore">ignore</option>
            </Select>
          </label>
          <Toggle
            label="Reject mock locations"
            value={v("gps.rejectMockLocation") as boolean | undefined}
            inherited={r("gps.rejectMockLocation") as boolean | undefined}
            onChange={(b) => set("gps.rejectMockLocation", b)}
            readOnly={readOnly}
          />
          <Toggle
            label="Allow external GNSS receiver"
            value={v("gps.allowExternalReceiver") as boolean | undefined}
            inherited={r("gps.allowExternalReceiver") as boolean | undefined}
            onChange={(b) => set("gps.allowExternalReceiver", b)}
            readOnly={readOnly}
          />
        </div>
        <div className="mt-3 rounded-md border border-neutral-200 p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="font-medium">GPS averaging</span>
            <Lock
              locked={v("gps.averaging.locked") as boolean | undefined}
              onChange={(l) => set("gps.averaging.locked", l)}
              readOnly={readOnly}
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Toggle
              label="Enabled"
              value={v("gps.averaging.enabled") as boolean | undefined}
              inherited={r("gps.averaging.enabled") as boolean | undefined}
              onChange={(b) => set("gps.averaging.enabled", b)}
              readOnly={readOnly}
            />
            <Num
              label="Samples"
              path="gps.averaging.samples"
              v={v}
              ph={ph}
              set={set}
              readOnly={readOnly}
              integer
            />
          </div>
        </div>
      </Section>

      {linear && (
        <Section
          title="Snapping"
          lock={v("snapping.locked") as boolean | undefined}
          onLock={(l) => set("snapping.locked", l)}
          readOnly={readOnly}
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <Toggle
              label="Enabled"
              value={v("snapping.enabled") as boolean | undefined}
              inherited={r("snapping.enabled") as boolean | undefined}
              onChange={(b) => set("snapping.enabled", b)}
              readOnly={readOnly}
            />
            <Num
              label="Tolerance (m)"
              path="snapping.toleranceMeters"
              v={v}
              ph={ph}
              set={set}
              readOnly={readOnly}
            />
            <LayerRefs
              label="Snap to layers"
              path="snapping.layers"
              v={v}
              set={set}
              layerKeys={layerKeys}
              readOnly={readOnly}
            />
          </div>
        </Section>
      )}

      <Section title="Validation (admin only)">
        <div className="grid gap-3 sm:grid-cols-2">
          <Toggle
            label="Prevent self-intersection"
            value={v("validation.preventSelfIntersection") as boolean | undefined}
            inherited={r("validation.preventSelfIntersection") as boolean | undefined}
            onChange={(b) => set("validation.preventSelfIntersection", b)}
            readOnly={readOnly}
          />
          <Num
            label="Minimum vertices"
            path="minVertices"
            v={v}
            ph={ph}
            set={set}
            readOnly={readOnly}
            integer
          />
          <Num
            label="Min area (m²)"
            path="validation.minAreaSqm"
            v={v}
            ph={ph}
            set={set}
            readOnly={readOnly}
          />
          <Num
            label="Max area (m²)"
            path="validation.maxAreaSqm"
            v={v}
            ph={ph}
            set={set}
            readOnly={readOnly}
          />
          <Num
            label="Duplicate warning distance (m)"
            path="validation.duplicateWarningMeters"
            v={v}
            ph={ph}
            set={set}
            readOnly={readOnly}
          />
          <LayerRefs
            label="No overlap with"
            path="validation.topology.noOverlapWith"
            v={v}
            set={set}
            layerKeys={layerKeys}
            readOnly={readOnly}
          />
          <label className="block">
            On overlap
            <Select
              value={(v("validation.topology.onOverlap") as string | undefined) ?? ""}
              disabled={readOnly}
              onChange={(e) => set("validation.topology.onOverlap", e.target.value || undefined)}
            >
              <option value="">
                (inherit
                {ph("validation.topology.onOverlap") && `: ${ph("validation.topology.onOverlap")}`})
              </option>
              <option value="flag">flag</option>
              <option value="block">block</option>
            </Select>
          </label>
          <Num
            label="Overlap tolerance (m²)"
            path="validation.topology.overlapToleranceSqm"
            v={v}
            ph={ph}
            set={set}
            readOnly={readOnly}
          />
        </div>
      </Section>

      <Section title="Centroid and display (admin only)">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block">
            Centroid method
            <Select
              value={(v("centroid.method") as string | undefined) ?? ""}
              disabled={readOnly}
              onChange={(e) => set("centroid.method", e.target.value || undefined)}
            >
              <option value="">(inherit)</option>
              <option value="centroid">centroid</option>
              <option value="point_on_surface">point on surface</option>
            </Select>
          </label>
          <Toggle
            label="Allow point-only capture"
            value={v("centroid.allowPointOnlyCapture") as boolean | undefined}
            inherited={r("centroid.allowPointOnlyCapture") as boolean | undefined}
            onChange={(b) => set("centroid.allowPointOnlyCapture", b)}
            readOnly={readOnly}
          />
          <label className="block">
            Units
            <Select
              value={(v("display.units") as string | undefined) ?? ""}
              disabled={readOnly}
              onChange={(e) => set("display.units", e.target.value || undefined)}
            >
              <option value="">(inherit)</option>
              <option value="metric">metric</option>
              <option value="hectares">hectares</option>
              <option value="acres">acres</option>
              <option value="imperial">imperial</option>
            </Select>
          </label>
          <Toggle
            label="Show area"
            value={v("display.showArea") as boolean | undefined}
            inherited={r("display.showArea") as boolean | undefined}
            onChange={(b) => set("display.showArea", b)}
            readOnly={readOnly}
          />
        </div>
      </Section>
    </div>
  );
}

function Section({
  title,
  lock,
  onLock,
  readOnly,
  children,
}: {
  title: string;
  lock?: boolean;
  onLock?: (l: boolean | undefined) => void;
  readOnly?: boolean;
  children: React.ReactNode;
}) {
  return (
    <fieldset className="rounded-md border border-neutral-200 p-3">
      <legend className="flex items-center gap-3 px-1 font-medium">
        {title}
        {onLock && <Lock locked={lock} onChange={onLock} readOnly={readOnly} />}
      </legend>
      {children}
    </fieldset>
  );
}

function Lock({
  locked,
  onChange,
  readOnly,
}: {
  locked?: boolean;
  onChange: (l: boolean | undefined) => void;
  readOnly?: boolean;
}) {
  return (
    <button
      type="button"
      disabled={readOnly}
      onClick={() => onChange(locked ? undefined : true)}
      title={
        locked ? "Locked: collectors cannot change this" : "Unlocked: collectors may change this"
      }
      aria-pressed={!!locked}
      className={
        "rounded px-1.5 py-0.5 text-xs " +
        (locked ? "bg-amber-100 text-amber-800" : "bg-neutral-100 text-neutral-600")
      }
    >
      {locked ? "🔒 locked" : "🔓 unlocked"}
    </button>
  );
}

function Toggle({
  label,
  value,
  inherited,
  onChange,
  readOnly,
}: {
  label: string;
  value: boolean | undefined;
  inherited: boolean | undefined;
  onChange: (b: boolean | undefined) => void;
  readOnly?: boolean;
}) {
  const state = value === undefined ? "" : value ? "on" : "off";
  return (
    <label className="block">
      {label}
      <Select
        value={state}
        disabled={readOnly}
        onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value === "on")}
      >
        <option value="">
          (inherit{inherited !== undefined ? `: ${inherited ? "on" : "off"}` : ""})
        </option>
        <option value="on">on</option>
        <option value="off">off</option>
      </Select>
    </label>
  );
}

function Num({
  label,
  path,
  v,
  ph,
  set,
  readOnly,
  integer,
}: {
  label: string;
  path: string;
  v: (p: string) => unknown;
  ph: (p: string) => string;
  set: (p: string, x: unknown) => void;
  readOnly?: boolean;
  integer?: boolean;
}) {
  const cur = v(path);
  return (
    <label className="block">
      {label}
      <Input
        type="number"
        step={integer ? 1 : "any"}
        value={cur === undefined || cur === null ? "" : String(cur)}
        placeholder={ph(path) ? `inherit: ${ph(path)}` : ""}
        disabled={readOnly}
        onChange={(e) => set(path, e.target.value === "" ? undefined : Number(e.target.value))}
      />
    </label>
  );
}

function LayerRefs({
  label,
  path,
  v,
  set,
  layerKeys,
  readOnly,
}: {
  label: string;
  path: string;
  v: (p: string) => unknown;
  set: (p: string, x: unknown) => void;
  layerKeys: string[];
  readOnly?: boolean;
}) {
  const selected = (v(path) as string[] | undefined) ?? [];
  const options = ["self", ...layerKeys];
  return (
    <div>
      {label}
      <div className="mt-1 flex flex-wrap gap-3">
        {options.map((k) => (
          <label key={k} className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={selected.includes(k)}
              disabled={readOnly}
              onChange={(e) =>
                set(
                  path,
                  e.target.checked
                    ? [...selected, k]
                    : selected.filter((x) => x !== k).length
                      ? selected.filter((x) => x !== k)
                      : undefined,
                )
              }
            />
            {k}
          </label>
        ))}
      </div>
    </div>
  );
}
