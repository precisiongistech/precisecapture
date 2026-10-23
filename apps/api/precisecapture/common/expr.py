"""
PreciseCapture expression language, Python implementation (packages/schema/expressions.md).

The same grammar runs on the phone and the web in TypeScript; both must pass the shared
vectors in packages/schema/test-vectors/expressions.json. A hand-written tokenizer and
recursive-descent parser produce a tiny AST; nothing here ever calls eval/exec.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

Value = bool | int | float | str | list[Any] | dict[str, Any] | None

# --- Errors and context ------------------------------------------------------------


class ExpressionParseError(ValueError):
    def __init__(self, message: str, position: int) -> None:
        super().__init__(f"{message} (at position {position})")
        self.message = message
        self.position = position


@dataclass
class EvalContext:
    values: Mapping[str, Any] = field(default_factory=dict)
    fields: Sequence[str] | None = None
    self_value: Any = None
    repeat_item: Mapping[str, Any] | None = None
    now: str = ""
    today: str = ""
    geom_area_m2: float | None = None
    geom_length_m: float | None = None
    lookup: Callable[[str, str], Any] | None = None
    ghanapost_gps: str | None = None

    @classmethod
    def from_vector(cls, context: Mapping[str, Any], defaults: Mapping[str, Any]) -> EvalContext:
        """Build a context from a test-vector `context` object (camelCase keys)."""
        lookups: Mapping[str, Any] = context.get("lookups") or {}
        return cls(
            values=context.get("values") or {},
            fields=context.get("fields"),
            self_value=context.get("self"),
            repeat_item=context.get("repeatItem"),
            now=context.get("now", defaults.get("now", "")),
            today=context.get("today", defaults.get("today", "")),
            geom_area_m2=context.get("geomAreaM2"),
            geom_length_m=context.get("geomLengthM"),
            lookup=(lambda layer, fld: lookups.get(f"{layer}.{fld}")) if lookups else None,
            ghanapost_gps=context.get("ghanapostGps"),
        )


# --- AST --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Num:
    value: float


@dataclass(frozen=True)
class Str:
    value: str


@dataclass(frozen=True)
class Ref:
    root: str
    child: str | None = None


@dataclass(frozen=True)
class SelfRef:
    pass


@dataclass(frozen=True)
class Unary:
    op: str
    operand: Node


@dataclass(frozen=True)
class Binary:
    op: str
    left: Node
    right: Node


@dataclass(frozen=True)
class Call:
    name: str
    args: tuple[Node, ...]


Node = Num | Str | Ref | SelfRef | Unary | Binary | Call

# --- Tokenizer ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Token:
    kind: str  # num | str | ref | self | ident | op | end
    text: str
    pos: int


_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:-[A-Za-z][A-Za-z0-9_]*)*")
_REF = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?")
_OPS = ("!=", "<=", ">=", "=", "<", ">", "+", "-", "*", "(", ")", ",")


def tokenize(src: str) -> list[Token]:
    tokens: list[Token] = []
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        if ch.isspace():
            i += 1
            continue
        if ch.isdigit():
            m = _NUMBER.match(src, i)
            assert m is not None
            tokens.append(Token("num", m.group(), i))
            i = m.end()
            continue
        if ch in ("'", '"'):
            j = i + 1
            buf: list[str] = []
            while j < n and src[j] != ch:
                if src[j] == "\\" and j + 1 < n:
                    buf.append(src[j + 1])
                    j += 2
                else:
                    buf.append(src[j])
                    j += 1
            if j >= n:
                raise ExpressionParseError("Unterminated string", i)
            tokens.append(Token("str", "".join(buf), i))
            i = j + 1
            continue
        if src.startswith("${", i):
            end = src.find("}", i)
            if end < 0:
                raise ExpressionParseError("Unclosed field reference", i)
            name = src[i + 2 : end].strip()
            if not name or not _REF.fullmatch(name):
                raise ExpressionParseError("Invalid field reference", i)
            tokens.append(Token("ref", name, i))
            i = end + 1
            continue
        if ch == ".":
            tokens.append(Token("self", ".", i))
            i += 1
            continue
        if ch.isalpha() or ch == "_":
            m = _IDENT.match(src, i)
            assert m is not None
            tokens.append(Token("ident", m.group(), i))
            i = m.end()
            continue
        for op in _OPS:
            if src.startswith(op, i):
                tokens.append(Token("op", op, i))
                i += len(op)
                break
        else:
            raise ExpressionParseError(f"Unexpected character {ch!r}", i)
    tokens.append(Token("end", "", n))
    return tokens


# --- Parser -------------------------------------------------------------------------------

# name -> (min_args, max_args or None for variadic)
FUNCTIONS: dict[str, tuple[int, int | None]] = {
    "true": (0, 0),
    "false": (0, 0),
    "not": (1, 1),
    "if": (3, 3),
    "coalesce": (2, 2),
    "concat": (1, None),
    "string-length": (1, 1),
    "selected": (2, 2),
    "count-selected": (1, 1),
    "count": (1, 1),
    "sum": (1, 1),
    "round": (1, 2),
    "int": (1, 1),
    "number": (1, 1),
    "today": (0, 0),
    "now": (0, 0),
    "regex": (2, 2),
    "geom_area": (0, 0),
    "geom_length": (0, 0),
    "lookup": (2, 2),
    "ghanapost_gps": (0, 0),
}


class _Parser:
    def __init__(self, tokens: list[Token], fields: Sequence[str] | None) -> None:
        self.tokens = tokens
        self.i = 0
        self.fields = set(fields) if fields is not None else None

    @property
    def tok(self) -> Token:
        return self.tokens[self.i]

    def _advance(self) -> Token:
        t = self.tokens[self.i]
        self.i += 1
        return t

    def _is(self, kind: str, text: str | None = None) -> bool:
        t = self.tok
        return t.kind == kind and (text is None or t.text == text)

    def _expect(self, kind: str, text: str) -> None:
        if not self._is(kind, text):
            raise ExpressionParseError(f"Expected {text!r}", self.tok.pos)
        self._advance()

    def parse(self) -> Node:
        if self._is("end"):
            raise ExpressionParseError("Empty expression", 0)
        node = self._or()
        if not self._is("end"):
            raise ExpressionParseError("Unexpected token", self.tok.pos)
        return node

    def _or(self) -> Node:
        node = self._and()
        while self._is("ident", "or"):
            self._advance()
            node = Binary("or", node, self._and())
        return node

    def _and(self) -> Node:
        node = self._eq()
        while self._is("ident", "and"):
            self._advance()
            node = Binary("and", node, self._eq())
        return node

    def _eq(self) -> Node:
        node = self._cmp()
        while self.tok.kind == "op" and self.tok.text in ("=", "!="):
            op = self._advance().text
            node = Binary(op, node, self._cmp())
        return node

    def _cmp(self) -> Node:
        node = self._add()
        while self.tok.kind == "op" and self.tok.text in ("<", "<=", ">", ">="):
            op = self._advance().text
            node = Binary(op, node, self._add())
        return node

    def _add(self) -> Node:
        node = self._mul()
        while self.tok.kind == "op" and self.tok.text in ("+", "-"):
            op = self._advance().text
            node = Binary(op, node, self._mul())
        return node

    def _mul(self) -> Node:
        node = self._unary()
        while (self.tok.kind == "op" and self.tok.text == "*") or (
            self.tok.kind == "ident" and self.tok.text in ("div", "mod")
        ):
            op = self._advance().text
            node = Binary(op, node, self._unary())
        return node

    def _unary(self) -> Node:
        if self._is("op", "-"):
            self._advance()
            return Unary("-", self._unary())
        return self._primary()

    def _primary(self) -> Node:
        t = self.tok
        if t.kind == "num":
            self._advance()
            return Num(float(t.text))
        if t.kind == "str":
            self._advance()
            return Str(t.text)
        if t.kind == "self":
            self._advance()
            return SelfRef()
        if t.kind == "ref":
            self._advance()
            root, _, child = t.text.partition(".")
            if self.fields is not None and root not in self.fields:
                raise ExpressionParseError(f"Unknown field {root!r}", t.pos)
            return Ref(root, child or None)
        if t.kind == "op" and t.text == "(":
            self._advance()
            node = self._or()
            self._expect("op", ")")
            return node
        if t.kind == "ident":
            return self._call()
        raise ExpressionParseError("Expected a value", t.pos)

    def _call(self) -> Node:
        t = self._advance()
        if t.text not in FUNCTIONS:
            raise ExpressionParseError(f"Unknown function {t.text!r}", t.pos)
        self._expect("op", "(")
        args: list[Node] = []
        if not self._is("op", ")"):
            args.append(self._or())
            while self._is("op", ","):
                self._advance()
                args.append(self._or())
        self._expect("op", ")")
        lo, hi = FUNCTIONS[t.text]
        if len(args) < lo or (hi is not None and len(args) > hi):
            raise ExpressionParseError(f"Wrong number of arguments for {t.text}()", t.pos)
        return Call(t.text, tuple(args))


def parse(expr: str, fields: Sequence[str] | None = None) -> Node:
    return _Parser(tokenize(expr), fields).parse()


def referenced_fields(expr_or_node: str | Node) -> list[str]:
    """Root keys an expression reads, in first-seen order ('.' excluded)."""
    node = parse(expr_or_node) if isinstance(expr_or_node, str) else expr_or_node
    out: list[str] = []

    def walk(n: Node) -> None:
        if isinstance(n, Ref):
            if n.root not in out:
                out.append(n.root)
        elif isinstance(n, Unary):
            walk(n.operand)
        elif isinstance(n, Binary):
            walk(n.left)
            walk(n.right)
        elif isinstance(n, Call):
            for a in n.args:
                walk(a)

    walk(node)
    return out


# --- Coercion helpers --------------------------------------------------------------------

_NUMERIC_STR = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")


def to_number(v: Any) -> float | None:
    """Number or numeric string -> float; everything else (incl. booleans) -> None."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int | float):
        return float(v)
    if isinstance(v, str) and _NUMERIC_STR.match(v.strip()):
        return float(v.strip())
    return None


def number_to_string(x: float) -> str:
    if math.isfinite(x) and x == int(x):
        return str(int(x))
    return repr(x)


def to_string(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int | float):
        return number_to_string(float(v))
    if isinstance(v, list):
        return " ".join(to_string(x) for x in v)
    return str(v)


def truthy(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    if isinstance(v, int | float):
        return v != 0
    if isinstance(v, str | list | dict):
        return len(v) > 0
    return True


def _equals(a: Any, b: Any) -> bool:
    if isinstance(a, list) or isinstance(b, list):
        return (
            isinstance(a, list)
            and isinstance(b, list)
            and len(a) == len(b)
            and all(_equals(x, y) for x, y in zip(a, b, strict=True))
        )
    if isinstance(a, bool) and isinstance(b, bool):
        return a == b
    na, nb = to_number(a), to_number(b)
    if na is not None and nb is not None:
        return na == nb
    return to_string(a) == to_string(b)


def _order(op: str, a: Any, b: Any) -> bool | None:
    if a is None or b is None:
        return None
    na, nb = to_number(a), to_number(b)
    if na is not None and nb is not None:
        x: float | str
        y: float | str
        x, y = na, nb
    elif isinstance(a, str) and isinstance(b, str) and na is None and nb is None:
        x, y = a, b
    else:
        return None
    return {"<": x < y, "<=": x <= y, ">": x > y, ">=": x >= y}[op]  # type: ignore[operator]


def _arith(op: str, a: Any, b: Any) -> float | None:
    x, y = to_number(a), to_number(b)
    if x is None or y is None:
        return None
    if op == "+":
        return x + y
    if op == "-":
        return x - y
    if op == "*":
        return x * y
    if y == 0:
        return None
    if op == "div":
        return x / y
    return math.fmod(x, y)


# --- Evaluator ------------------------------------------------------------------------


def _resolve(ref: Ref, ctx: EvalContext) -> Any:
    if ref.child is not None:
        rows = ctx.values.get(ref.root)
        if not isinstance(rows, list):
            return None
        return [row.get(ref.child) if isinstance(row, dict) else None for row in rows]
    if ctx.repeat_item is not None and ref.root in ctx.repeat_item:
        return ctx.repeat_item[ref.root]
    return ctx.values.get(ref.root)


def _call(name: str, args: tuple[Node, ...], ctx: EvalContext) -> Any:
    ev = [_eval(a, ctx) for a in args] if name != "if" else []
    match name:
        case "true":
            return True
        case "false":
            return False
        case "not":
            return not truthy(ev[0])
        case "if":
            cond = _eval(args[0], ctx)
            return _eval(args[1] if truthy(cond) else args[2], ctx)
        case "coalesce":
            return ev[0] if ev[0] is not None and ev[0] != "" else ev[1]
        case "concat":
            return "".join(to_string(v) for v in ev)
        case "string-length":
            return 0 if ev[0] is None else len(to_string(ev[0]))
        case "selected":
            if isinstance(ev[0], list):
                return any(_equals(x, ev[1]) for x in ev[0])
            return ev[0] is not None and _equals(ev[0], ev[1])
        case "count-selected":
            if isinstance(ev[0], list):
                return len(ev[0])
            return 1 if isinstance(ev[0], str) and ev[0] != "" else 0
        case "count":
            return len(ev[0]) if isinstance(ev[0], list) else 0
        case "sum":
            if not isinstance(ev[0], list):
                return 0
            return sum(n for n in (to_number(x) for x in ev[0]) if n is not None)
        case "round":
            x = to_number(ev[0])
            if x is None:
                return None
            digits = to_number(ev[1]) if len(ev) > 1 else 0.0
            q = Decimal(1).scaleb(-int(digits or 0))
            return float(Decimal(repr(x)).quantize(q, rounding=ROUND_HALF_UP))
        case "int":
            x = to_number(ev[0])
            return None if x is None else float(math.trunc(x))
        case "number":
            return to_number(ev[0])
        case "today":
            return ctx.today
        case "now":
            return ctx.now
        case "regex":
            if ev[0] is None:
                return False
            try:
                return re.search(to_string(ev[1]), to_string(ev[0])) is not None
            except re.error:
                return False
        case "geom_area":
            return ctx.geom_area_m2
        case "geom_length":
            return ctx.geom_length_m
        case "lookup":
            return ctx.lookup(to_string(ev[0]), to_string(ev[1])) if ctx.lookup else None
        case "ghanapost_gps":
            return ctx.ghanapost_gps
    raise ExpressionParseError(f"Unknown function {name!r}", 0)  # pragma: no cover


def _eval(node: Node, ctx: EvalContext) -> Any:
    if isinstance(node, Num):
        return node.value
    if isinstance(node, Str):
        return node.value
    if isinstance(node, SelfRef):
        return ctx.self_value
    if isinstance(node, Ref):
        return _resolve(node, ctx)
    if isinstance(node, Unary):
        x = to_number(_eval(node.operand, ctx))
        return None if x is None else -x
    if isinstance(node, Call):
        return _call(node.name, node.args, ctx)
    left = _eval(node.left, ctx)
    right = _eval(node.right, ctx)
    op = node.op
    if op == "or":
        return truthy(left) or truthy(right)
    if op == "and":
        return truthy(left) and truthy(right)
    if op == "=":
        return _equals(left, right)
    if op == "!=":
        return not _equals(left, right)
    if op in ("<", "<=", ">", ">="):
        return _order(op, left, right)
    return _arith(op, left, right)


def _normalise(v: Any) -> Value:
    """Integral floats come back as int so results are JSON-stable (15.0 -> 15)."""
    if isinstance(v, float) and math.isfinite(v) and v == int(v):
        return int(v)
    if isinstance(v, list):
        return [_normalise(x) for x in v]
    return v  # type: ignore[no-any-return]


def evaluate(expr_or_node: str | Node, context: EvalContext) -> Value:
    node = parse(expr_or_node, context.fields) if isinstance(expr_or_node, str) else expr_or_node
    return _normalise(_eval(node, context))
