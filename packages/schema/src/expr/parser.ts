/**
 * Tokenizer and recursive-descent parser. Never uses eval.
 *
 * Precedence (lowest → highest): or | and | = != | < <= > >= | + - | * div mod | unary - | ( )
 */
import { ExpressionParseError, FUNCTIONS, type BinaryOp, type Node } from "./ast.js";

type Token =
  | { t: "num"; v: number; pos: number }
  | { t: "str"; v: string; pos: number }
  | { t: "ref"; root: string; child: string | null; pos: number }
  | { t: "ident"; v: string; pos: number }
  | { t: "op"; v: string; pos: number }
  | { t: "dot"; pos: number }
  | { t: "lparen" | "rparen" | "comma"; pos: number }
  | { t: "eof"; pos: number };

const KEY = /^[a-z][a-z0-9_]*$/;

function tokenize(src: string): Token[] {
  const out: Token[] = [];
  let i = 0;
  const n = src.length;
  while (i < n) {
    const c = src[i]!;
    if (c === " " || c === "\t" || c === "\n" || c === "\r") {
      i++;
      continue;
    }
    const pos = i;
    if (c >= "0" && c <= "9") {
      let j = i;
      while (j < n && src[j]! >= "0" && src[j]! <= "9") j++;
      if (src[j] === "." && src[j + 1] !== undefined && src[j + 1]! >= "0" && src[j + 1]! <= "9") {
        j++;
        while (j < n && src[j]! >= "0" && src[j]! <= "9") j++;
      }
      out.push({ t: "num", v: Number(src.slice(i, j)), pos });
      i = j;
      continue;
    }
    if (c === "'" || c === '"') {
      let j = i + 1;
      let s = "";
      let closed = false;
      while (j < n) {
        const d = src[j]!;
        if (d === "\\" && j + 1 < n) {
          s += src[j + 1]!;
          j += 2;
          continue;
        }
        if (d === c) {
          closed = true;
          j++;
          break;
        }
        s += d;
        j++;
      }
      if (!closed) throw new ExpressionParseError("Unterminated string", pos);
      out.push({ t: "str", v: s, pos });
      i = j;
      continue;
    }
    if (c === "$" && src[i + 1] === "{") {
      const end = src.indexOf("}", i + 2);
      if (end < 0) throw new ExpressionParseError("Unclosed field reference", pos);
      const inner = src.slice(i + 2, end).trim();
      const parts = inner.split(".");
      if (inner === "" || parts.length > 2 || !parts.every((p) => KEY.test(p))) {
        throw new ExpressionParseError(`Invalid field reference \${${inner}}`, pos);
      }
      out.push({ t: "ref", root: parts[0]!, child: parts[1] ?? null, pos });
      i = end + 1;
      continue;
    }
    if ((c >= "a" && c <= "z") || (c >= "A" && c <= "Z") || c === "_") {
      let j = i + 1;
      while (j < n) {
        const d = src[j]!;
        const word = (d >= "a" && d <= "z") || (d >= "A" && d <= "Z") || (d >= "0" && d <= "9") || d === "_";
        const hyphen = d === "-" && j + 1 < n && src[j + 1]! >= "a" && src[j + 1]! <= "z";
        if (!word && !hyphen) break;
        j++;
      }
      out.push({ t: "ident", v: src.slice(i, j), pos });
      i = j;
      continue;
    }
    if (c === "(") out.push({ t: "lparen", pos });
    else if (c === ")") out.push({ t: "rparen", pos });
    else if (c === ",") out.push({ t: "comma", pos });
    else if (c === ".") out.push({ t: "dot", pos });
    else if (c === "!" && src[i + 1] === "=") {
      out.push({ t: "op", v: "!=", pos });
      i++;
    } else if ((c === "<" || c === ">") && src[i + 1] === "=") {
      out.push({ t: "op", v: c + "=", pos });
      i++;
    } else if ("=<>+-*".includes(c)) out.push({ t: "op", v: c, pos });
    else throw new ExpressionParseError(`Unexpected character '${c}'`, pos);
    i++;
  }
  out.push({ t: "eof", pos: n });
  return out;
}

class Parser {
  private i = 0;
  constructor(
    private readonly toks: Token[],
    private readonly fields: ReadonlySet<string> | null,
  ) {}

  parse(): Node {
    const node = this.or();
    const t = this.peek();
    if (t.t !== "eof") throw new ExpressionParseError("Unexpected token after expression", t.pos);
    return node;
  }

  private peek(): Token {
    return this.toks[this.i]!;
  }
  private next(): Token {
    return this.toks[this.i++]!;
  }
  private isIdent(v: string): boolean {
    const t = this.peek();
    return t.t === "ident" && t.v === v;
  }
  private isOp(...ops: string[]): string | null {
    const t = this.peek();
    return t.t === "op" && ops.includes(t.v) ? t.v : null;
  }

  private or(): Node {
    let left = this.and();
    while (this.isIdent("or")) {
      this.next();
      left = { kind: "binary", op: "or", left, right: this.and() };
    }
    return left;
  }
  private and(): Node {
    let left = this.eq();
    while (this.isIdent("and")) {
      this.next();
      left = { kind: "binary", op: "and", left, right: this.eq() };
    }
    return left;
  }
  private eq(): Node {
    let left = this.cmp();
    let op: string | null;
    while ((op = this.isOp("=", "!="))) {
      this.next();
      left = { kind: "binary", op: op as BinaryOp, left, right: this.cmp() };
    }
    return left;
  }
  private cmp(): Node {
    let left = this.add();
    let op: string | null;
    while ((op = this.isOp("<", "<=", ">", ">="))) {
      this.next();
      left = { kind: "binary", op: op as BinaryOp, left, right: this.add() };
    }
    return left;
  }
  private add(): Node {
    let left = this.mul();
    let op: string | null;
    while ((op = this.isOp("+", "-"))) {
      this.next();
      left = { kind: "binary", op: op as BinaryOp, left, right: this.mul() };
    }
    return left;
  }
  private mul(): Node {
    let left = this.unary();
    for (;;) {
      if (this.isOp("*")) {
        this.next();
        left = { kind: "binary", op: "*", left, right: this.unary() };
      } else if (this.isIdent("div") || this.isIdent("mod")) {
        const op = (this.next() as { v: string }).v as BinaryOp;
        left = { kind: "binary", op, left, right: this.unary() };
      } else return left;
    }
  }
  private unary(): Node {
    if (this.isOp("-")) {
      this.next();
      return { kind: "unary", op: "-", operand: this.unary() };
    }
    return this.primary();
  }
  private primary(): Node {
    const t = this.next();
    switch (t.t) {
      case "num":
        return { kind: "number", value: t.v };
      case "str":
        return { kind: "string", value: t.v };
      case "dot":
        return { kind: "self" };
      case "ref":
        if (this.fields && !this.fields.has(t.root)) {
          throw new ExpressionParseError(`Unknown field \${${t.root}}`, t.pos);
        }
        return { kind: "ref", root: t.root, child: t.child };
      case "lparen": {
        const inner = this.or();
        const close = this.next();
        if (close.t !== "rparen") throw new ExpressionParseError("Expected ')'", close.pos);
        return inner;
      }
      case "ident": {
        if (t.v === "and" || t.v === "or" || t.v === "div" || t.v === "mod") {
          throw new ExpressionParseError(`Unexpected '${t.v}'`, t.pos);
        }
        const arity = FUNCTIONS[t.v];
        if (!arity) throw new ExpressionParseError(`Unknown function ${t.v}()`, t.pos);
        const open = this.next();
        if (open.t !== "lparen") throw new ExpressionParseError(`Expected '(' after ${t.v}`, open.pos);
        const args: Node[] = [];
        if (this.peek().t !== "rparen") {
          for (;;) {
            args.push(this.or());
            if (this.peek().t === "comma") {
              this.next();
              continue;
            }
            break;
          }
        }
        const close = this.next();
        if (close.t !== "rparen") throw new ExpressionParseError("Expected ')' to close the argument list", close.pos);
        const [min, max] = arity;
        if (args.length < min || args.length > max) {
          throw new ExpressionParseError(`${t.v}() takes ${min === max ? min : `${min} to ${max}`} argument(s)`, t.pos);
        }
        return { kind: "call", name: t.v, args };
      }
      case "eof":
        throw new ExpressionParseError("Unexpected end of expression", t.pos);
      default:
        throw new ExpressionParseError("Unexpected token", t.pos);
    }
  }
}

/**
 * Parse an expression. With `fields` (the valid root keys of the record), a reference to an
 * unknown field is a parse error; without it, unknown references evaluate to null.
 */
export function parse(expr: string, fields?: readonly string[] | null): Node {
  const parser = new Parser(tokenize(expr), fields ? new Set(fields) : null);
  return parser.parse();
}

/** Root keys an expression reads, in first-seen order (excludes "."). */
export function referencedFields(exprOrNode: string | Node): string[] {
  const node = typeof exprOrNode === "string" ? parse(exprOrNode) : exprOrNode;
  const out: string[] = [];
  const walk = (n: Node): void => {
    switch (n.kind) {
      case "ref":
        if (!out.includes(n.root)) out.push(n.root);
        break;
      case "unary":
        walk(n.operand);
        break;
      case "binary":
        walk(n.left);
        walk(n.right);
        break;
      case "call":
        n.args.forEach(walk);
        break;
      default:
        break;
    }
  };
  walk(node);
  return out;
}
