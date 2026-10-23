/** Evaluator. Semantics are pinned by expressions.md and test-vectors/expressions.json. */
import type { Node } from "./ast.js";
import { parse } from "./parser.js";

export type Value = null | boolean | number | string | Value[] | { [key: string]: unknown };

export interface EvalContext {
  values: Record<string, unknown>;
  fields?: readonly string[] | null;
  self?: unknown;
  repeatItem?: Record<string, unknown> | null;
  now: string;
  today: string;
  geomAreaM2?: number | null;
  geomLengthM?: number | null;
  lookup?: (layer: string, field: string) => unknown;
  ghanapostGps?: string | null;
}

const NUMERIC = /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/;

function normalise(v: unknown): Value {
  if (v === undefined || v === null) return null;
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return null;
    return Object.is(v, -0) ? 0 : v;
  }
  if (typeof v === "boolean" || typeof v === "string" || Array.isArray(v)) return v as Value;
  if (typeof v === "object") return v as Value;
  return null;
}

export function toNumber(v: Value): number | null {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "string") {
    const s = v.trim();
    return s !== "" && NUMERIC.test(s) ? Number(s) : null;
  }
  return null;
}

export function numberToString(n: number): string {
  return String(n);
}

export function toStr(v: Value): string {
  if (v === null) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number") return numberToString(v);
  if (typeof v === "boolean") return v ? "true" : "false";
  if (Array.isArray(v)) return v.map(toStr).join(" ");
  return JSON.stringify(v);
}

export function truthy(v: Value): boolean {
  if (v === null) return false;
  if (typeof v === "boolean") return v;
  if (typeof v === "number") return v !== 0;
  if (typeof v === "string") return v.length > 0;
  if (Array.isArray(v)) return v.length > 0;
  return true;
}

function equals(a: Value, b: Value): boolean {
  if (a === null) a = "";
  if (b === null) b = "";
  if (typeof a === "boolean" && typeof b === "boolean") return a === b;
  const na = toNumber(a);
  const nb = toNumber(b);
  if (na !== null && nb !== null) return na === nb;
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((x, i) => equals(x, b[i] ?? null));
  }
  if (Array.isArray(a) || Array.isArray(b)) return false;
  return toStr(a) === toStr(b);
}

function compare(a: Value, b: Value): number | null {
  const na = toNumber(a);
  const nb = toNumber(b);
  if (na !== null && nb !== null) return na < nb ? -1 : na > nb ? 1 : 0;
  if (typeof a === "string" && typeof b === "string" && na === null && nb === null) {
    return a < b ? -1 : a > b ? 1 : 0;
  }
  return null;
}

/** Round half away from zero on the decimal representation (matches Python's Decimal(str(x))). */
export function roundHalfAwayFromZero(x: number, digits: number): number {
  const sign = x < 0 ? -1 : 1;
  const s = Math.abs(x).toString();
  if (s.includes("e")) return sign * Math.round(Math.abs(x) * 10 ** digits) / 10 ** digits;
  const [intPart = "0", fracPart = ""] = s.split(".");
  const shifted = intPart + fracPart.slice(0, digits).padEnd(digits, "0");
  const rest = fracPart.slice(digits);
  let n = Number(shifted);
  if (rest !== "" && rest[0]! >= "5") n += 1;
  return sign * (n / 10 ** digits);
}

function resolveRef(ctx: EvalContext, root: string, child: string | null): Value {
  let base: unknown;
  if (ctx.repeatItem && Object.prototype.hasOwnProperty.call(ctx.repeatItem, root)) base = ctx.repeatItem[root];
  else base = ctx.values[root];
  const v = normalise(base);
  if (child === null) return v;
  if (Array.isArray(v)) {
    return v.map((row) =>
      row !== null && typeof row === "object" && !Array.isArray(row) ? normalise((row as Record<string, unknown>)[child]) : null,
    );
  }
  if (v !== null && typeof v === "object" && !Array.isArray(v)) return normalise((v as Record<string, unknown>)[child]);
  return null;
}

function arithmetic(op: string, a: Value, b: Value): Value {
  const x = toNumber(a);
  const y = toNumber(b);
  if (x === null || y === null) return null;
  switch (op) {
    case "+":
      return normalise(x + y);
    case "-":
      return normalise(x - y);
    case "*":
      return normalise(x * y);
    case "div":
      return y === 0 ? null : normalise(x / y);
    case "mod":
      return y === 0 ? null : normalise(x % y);
    default:
      return null;
  }
}

function call(name: string, args: Node[], ctx: EvalContext): Value {
  const ev = (i: number): Value => evalNode(args[i]!, ctx);
  switch (name) {
    case "true":
      return true;
    case "false":
      return false;
    case "not":
      return !truthy(ev(0));
    case "if":
      return truthy(ev(0)) ? ev(1) : ev(2);
    case "coalesce": {
      const a = ev(0);
      return a !== null && a !== "" ? a : ev(1);
    }
    case "concat":
      return args.map((_, i) => toStr(ev(i))).join("");
    case "string-length":
      return toStr(ev(0)).length;
    case "selected": {
      const f = ev(0);
      const v = ev(1);
      if (f === null) return false;
      if (Array.isArray(f)) return f.some((x) => equals(x, v));
      return equals(f, v);
    }
    case "count-selected": {
      const f = ev(0);
      if (f === null || f === "") return 0;
      return Array.isArray(f) ? f.length : 1;
    }
    case "count": {
      const f = ev(0);
      if (f === null) return 0;
      return Array.isArray(f) ? f.length : 1;
    }
    case "sum": {
      const f = ev(0);
      const items = Array.isArray(f) ? f : [f];
      let total = 0;
      for (const item of items) {
        const n = toNumber(item);
        if (n !== null) total += n;
      }
      return normalise(total);
    }
    case "round": {
      const x = toNumber(ev(0));
      if (x === null) return null;
      const d = args.length > 1 ? toNumber(ev(1)) : 0;
      if (d === null) return null;
      return normalise(roundHalfAwayFromZero(x, Math.max(0, Math.trunc(d))));
    }
    case "int": {
      const x = toNumber(ev(0));
      return x === null ? null : normalise(Math.trunc(x));
    }
    case "number":
      return toNumber(ev(0));
    case "today":
      return ctx.today;
    case "now":
      return ctx.now;
    case "regex": {
      const s = ev(0);
      if (s === null) return false;
      return new RegExp(toStr(ev(1))).test(toStr(s));
    }
    case "geom_area":
      return normalise(ctx.geomAreaM2);
    case "geom_length":
      return normalise(ctx.geomLengthM);
    case "lookup":
      return ctx.lookup ? normalise(ctx.lookup(toStr(ev(0)), toStr(ev(1)))) : null;
    case "ghanapost_gps":
      return normalise(ctx.ghanapostGps);
    default:
      return null;
  }
}

function evalNode(node: Node, ctx: EvalContext): Value {
  switch (node.kind) {
    case "number":
      return node.value;
    case "string":
      return node.value;
    case "self":
      return normalise(ctx.self);
    case "ref":
      return resolveRef(ctx, node.root, node.child);
    case "unary": {
      const x = toNumber(evalNode(node.operand, ctx));
      return x === null ? null : normalise(-x);
    }
    case "binary": {
      const { op } = node;
      if (op === "and") {
        const l = truthy(evalNode(node.left, ctx));
        const r = truthy(evalNode(node.right, ctx));
        return l && r;
      }
      if (op === "or") {
        const l = truthy(evalNode(node.left, ctx));
        const r = truthy(evalNode(node.right, ctx));
        return l || r;
      }
      const a = evalNode(node.left, ctx);
      const b = evalNode(node.right, ctx);
      switch (op) {
        case "=":
          return equals(a, b);
        case "!=":
          return !equals(a, b);
        case "<":
        case "<=":
        case ">":
        case ">=": {
          const c = compare(a, b);
          if (c === null) return null;
          return op === "<" ? c < 0 : op === "<=" ? c <= 0 : op === ">" ? c > 0 : c >= 0;
        }
        default:
          return arithmetic(op, a, b);
      }
    }
    case "call":
      return call(node.name, node.args, ctx);
  }
}

/** Evaluate an expression (or a parsed node) against a context. */
export function evaluate(exprOrNode: string | Node, ctx: EvalContext): Value {
  const node = typeof exprOrNode === "string" ? parse(exprOrNode, ctx.fields ?? null) : exprOrNode;
  return evalNode(node, ctx);
}
