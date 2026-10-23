/** AST and errors for the PreciseCapture expression language (expressions.md). */

export type Node =
  | { kind: "number"; value: number }
  | { kind: "string"; value: string }
  | { kind: "ref"; root: string; child: string | null }
  | { kind: "self" }
  | { kind: "unary"; op: "-"; operand: Node }
  | { kind: "binary"; op: BinaryOp; left: Node; right: Node }
  | { kind: "call"; name: string; args: Node[] };

export type BinaryOp = "or" | "and" | "=" | "!=" | "<" | "<=" | ">" | ">=" | "+" | "-" | "*" | "div" | "mod";

export class ExpressionParseError extends Error {
  override readonly name = "ExpressionParseError";
  constructor(
    message: string,
    public readonly position: number,
  ) {
    super(`${message} (at ${position})`);
  }
}

/** Function name → [min arity, max arity]; Infinity = variadic. */
export const FUNCTIONS: Readonly<Record<string, readonly [number, number]>> = {
  true: [0, 0],
  false: [0, 0],
  not: [1, 1],
  if: [3, 3],
  coalesce: [2, 2],
  concat: [1, Infinity],
  "string-length": [1, 1],
  selected: [2, 2],
  "count-selected": [1, 1],
  count: [1, 1],
  sum: [1, 1],
  round: [1, 2],
  int: [1, 1],
  number: [1, 1],
  today: [0, 0],
  now: [0, 0],
  regex: [2, 2],
  geom_area: [0, 0],
  geom_length: [0, 0],
  lookup: [2, 2],
  ghanapost_gps: [0, 0],
};
