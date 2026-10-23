/**
 * resolveCaptureProfile: org → project → layer → collector, honouring locks.
 * Rules are pinned by capture-profile-resolution.md and the shared vectors.
 */
import type { CaptureProfile } from "../types.js";

export type PartialProfile = Record<string, unknown>;

/** Objects whose schema carries a `locked` flag. Collectors may only change keys inside these. */
export const LOCKABLE_PATHS: readonly string[] = [
  "modes",
  "autoClose",
  "snapping",
  "trace",
  "stream",
  "gps",
  "gps.averaging",
  "offsetPoints",
];

type Obj = Record<string, unknown>;

const isObj = (v: unknown): v is Obj => v !== null && typeof v === "object" && !Array.isArray(v);

function clone<T>(v: T): T {
  return v === undefined ? v : (JSON.parse(JSON.stringify(v)) as T);
}

/** Deep-merge `lower` into `base` (objects merge, arrays/scalars replace), respecting locks. */
function mergeLevel(base: Obj, lower: Obj, path: string, locked: Set<string>): Obj {
  const out: Obj = { ...base };
  for (const [key, value] of Object.entries(lower)) {
    const p = path ? `${path}.${key}` : key;
    if (locked.has(p)) continue; // frozen by a level above
    const lockable = LOCKABLE_PATHS.includes(p);
    if (lockable && isObj(value) && value.locked === true) {
      // A lock is a statement of the complete object: take it whole, then freeze it.
      out[key] = clone(value);
      lockPath(p, locked);
      continue;
    }
    if (isObj(value) && isObj(out[key])) {
      out[key] = mergeLevel(out[key] as Obj, value, p, locked);
    } else {
      out[key] = clone(value);
    }
  }
  return out;
}

function lockPath(p: string, locked: Set<string>): void {
  locked.add(p);
  for (const other of LOCKABLE_PATHS) if (other.startsWith(p + ".")) locked.add(other);
}

/** Locks already present in a merged admin profile (so `locked: true` set at org level counts). */
function collectLocks(profile: Obj, locked: Set<string>): void {
  for (const p of LOCKABLE_PATHS) {
    const obj = getPath(profile, p);
    if (isObj(obj) && obj.locked === true) lockPath(p, locked);
  }
}

function getPath(obj: Obj, path: string): unknown {
  let cur: unknown = obj;
  for (const part of path.split(".")) {
    if (!isObj(cur)) return undefined;
    cur = cur[part];
  }
  return cur;
}

function applyCollector(profile: Obj, overrides: Obj, path: string, locked: Set<string>): Obj {
  const out: Obj = { ...profile };
  for (const [key, value] of Object.entries(overrides)) {
    const p = path ? `${path}.${key}` : key;
    const insideLockable = LOCKABLE_PATHS.some((l) => p === l || p.startsWith(l + "."));
    if (!insideLockable) continue; // admin-only or unknown
    if (locked.has(p) || [...locked].some((l) => p.startsWith(l + "."))) continue;
    if (key === "locked") continue; // collectors never change locks
    if (isObj(value)) {
      const base = isObj(out[key]) ? (out[key] as Obj) : {};
      out[key] = applyCollector(base, value, p, locked);
    } else if (LOCKABLE_PATHS.includes(p)) {
      continue; // a lockable object replaced by a scalar: ignore
    } else {
      out[key] = clone(value);
    }
  }
  return out;
}

export function resolveCaptureProfile(
  org: PartialProfile | null | undefined,
  project: PartialProfile | null | undefined,
  layer: PartialProfile | null | undefined,
  collectorOverrides: PartialProfile | null | undefined,
): CaptureProfile {
  const locked = new Set<string>();
  let merged: Obj = {};
  for (const level of [org, project, layer]) {
    if (!level) continue;
    merged = mergeLevel(merged, level, "", locked);
    collectLocks(merged, locked);
  }
  if (collectorOverrides) merged = applyCollector(merged, collectorOverrides, "", locked);
  return merged as CaptureProfile;
}
