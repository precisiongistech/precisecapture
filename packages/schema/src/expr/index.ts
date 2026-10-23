export { ExpressionParseError, FUNCTIONS, type BinaryOp, type Node } from "./ast.js";
export { evaluate, roundHalfAwayFromZero, toNumber, toStr, truthy, type EvalContext, type Value } from "./evaluate.js";
export { parse, referencedFields } from "./parser.js";

import { parse as parseExpr } from "./parser.js";
import { ExpressionParseError } from "./ast.js";

/** Form-builder helper: null when the expression parses, else the error message and position. */
export function validateExpression(
  expr: string,
  fields?: readonly string[] | null,
): { message: string; position: number } | null {
  try {
    parseExpr(expr, fields);
    return null;
  } catch (e) {
    if (e instanceof ExpressionParseError) return { message: e.message, position: e.position };
    throw e;
  }
}
