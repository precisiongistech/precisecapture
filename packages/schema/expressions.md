# PreciseCapture expression language (v1)

Expressions drive `relevant` (show/hide), `required` (when a string), `constraint`, and `calculate` fields. The same expression must give the **same result** on the phone (TypeScript), the web (TypeScript) and the server (Python). Both implementations must pass every case in `test-vectors/expressions.json`. **Never implement with `eval`.** Use a small recursive-descent or Pratt parser.

The syntax is deliberately close to XLSForm/ODK, so XLSForm import (later) maps cleanly.

## Values and types

| Type | Literal examples | Notes |
| --- | --- | --- |
| number | `3`, `2.5`, `-1` | IEEE double; integer results print without `.0` |
| string | `'cocoa'`, `"Juaboso"` | single or double quotes; `\'` escapes |
| boolean | `true()`, `false()` | results of comparisons and logic |

| null | an empty or unanswered field | |
| array | a `select_many` answer or the rows of a `repeat` | only produced by references, never by literals |

**Stored answer values:** `yes_no` stores the strings `'yes'` / `'no'`; `select_one` a string; `select_many` an array of strings; numbers as numbers; dates as `YYYY-MM-DD` strings; a `repeat` as an array of row objects.

**Field references**

- `${key}` is the value of another field in the same record. Inside a repeat item, `${key}` resolves to the sibling in the same item first, then to the parent record.
- `${repeat.key}` (dotted) is the array of `key` values across the rows of a `repeat`; a missing child yields null in that position. Only one level is supported.
- `.` is the current field's own value (used in `constraint`).
- With `fields` in the context, a reference whose root key is not listed is a parse error. Without it, unknown references evaluate to null.

**Truthiness** (used by `and`, `or`, `not()`, `if()`): `true`, non-zero numbers, non-empty strings and non-empty arrays are true; `false`, `0`, `''`, null and empty arrays are false. `and` / `or` always return a boolean and evaluate both sides.

**Coercion**

- Arithmetic (`+ - * div mod`, unary `-`): numbers stay numbers; a string that parses as a number is converted; anything else (null, non-numeric string, boolean, array) gives null. `div` and `mod` by zero give null; `mod` takes the sign of the dividend (`-7 mod 3` is `-1`).
- `=` / `!=`: null is treated as `''`. If both sides are numbers or numeric strings, compare numerically (`'1.0' = 1` is true). Two booleans compare as booleans. Otherwise compare the string forms. Arrays are equal only to an array with the same elements in order.
- `< <= > >=`: both numeric (number or numeric string) → numeric; both non-numeric strings → lexical (so ISO dates order correctly); any other combination, including null, gives null.
- String form of a number: integers print without `.0` (`concat('A', 1.0)` is `'A1'`); other numbers use the shortest round-trip decimal form.

**Null rules**

- Arithmetic with null gives null.
- In comparisons, null behaves as the empty string `''`. So `${x} = ''` is true, `${x} = 'a'` is false, and `${x} != 'a'` is **true** when `x` is null.
- To require an answer *and* exclude a value, write `${x} != '' and ${x} != 'none'`.
- `relevant` that evaluates to null is treated as **true** (the field is shown).
- `required` and `constraint` that evaluate to null are treated as **false** (not required, and the constraint is not violated).

## Operators (lowest to highest precedence)

| Operators | Meaning |
| --- | --- |
| `or` | logical or |
| `and` | logical and |
| `=` `!=` | equality (string vs number: compare as numbers if both parse, else as strings) |
| `<` `<=` `>` `>=` | numeric comparison; dates compare as ISO strings |
| `+` `-` | add, subtract |
| `*` `div` `mod` | multiply, divide, remainder (`div` by zero gives null) |
| unary `-` | negate |
| `( )` | grouping |

## Functions

| Function | Result |
| --- | --- |
| `true()`, `false()` | boolean literals |
| `not(x)` | logical not |
| `if(cond, a, b)` | a if cond is true, else b |
| `coalesce(a, b)` | a if not null and not `''`, else b (`0` is kept) |
| `concat(a, b, ...)` | string concatenation (null becomes empty) |
| `string-length(s)` | length in characters (null → 0) |
| `selected(${field}, 'value')` | true if a select_many contains the value (or a select_one equals it); null → false |
| `count-selected(${field})` | number of selected values (array length; a non-empty string → 1; null → 0) |
| `count(${repeat})` | number of items in a repeat (array length; null → 0) |
| `sum(${repeat.field})` | sum of a numeric field across repeat items; non-numeric and null entries are skipped |
| `round(x, digits)` | round half away from zero; `digits` defaults to 0 |
| `int(x)` | truncate toward zero |
| `number(x)` | parse number (null if invalid) |
| `today()` | local date `YYYY-MM-DD` (injected by the host for tests) |
| `now()` | ISO datetime (injected by the host for tests) |
| `regex(s, pattern)` | true if the ECMAScript-compatible pattern matches |
| `geom_area()` | area of the record's geometry in m² (geodesic); null if no polygon |
| `geom_length()` | length or perimeter in m (geodesic) |
| `lookup('layer', 'field')` | value of `field` from the reference-layer polygon containing this record's point/centroid. Provided by the host through `lookup` (or the `lookups` map in test vectors); null when unavailable. The server keeps the device value |
| `ghanapost_gps()` | GhanaPostGPS digital address of the centroid, provided by the host (`ghanapostGps`); null when unavailable |
| `nearest('layer', 'field')` | *Reserved for a later version.* Parsers must reject it in v1 as an unknown function |

Host-provided values (`today()`, `now()`, `geom_area()`, `geom_length()`) come from an evaluation context, so tests are deterministic.

## Evaluation context (both implementations)

```ts
interface EvalContext {
  values: Record<string, unknown>;          // current record's answers (repeats are arrays of row objects)
  fields?: string[];                        // valid root keys; enables the unknown-field parse error
  self?: unknown;                           // value for "."
  repeatItem?: Record<string, unknown>;     // the current row when evaluating inside a repeat item
  now: string;                              // ISO datetime
  today: string;                            // YYYY-MM-DD
  geomAreaM2?: number | null;
  geomLengthM?: number | null;
  lookup?: (layer: string, field: string) => unknown;   // test vectors use `lookups: {"layer.field": value}`
  ghanapostGps?: string | null;
}
```

Both implementations expose the same three operations: `parse(expr, fields?)` → AST or a parse error, `evaluate(expr, context)` → value, and `referencedFields(expr)` → the root keys an expression reads (used by the form builder and by the server's dependency ordering).

## Test vector format

Each test vector in `test-vectors/expressions.json` has one of these shapes:

```json
{ "name": "…", "expr": "…", "context": { … }, "expect": <value> }
{ "name": "…", "expr": "…", "context": { … }, "expectError": "parse" }
```

`context.now` / `context.today` fall back to the file's `defaults` when a case omits them. `lookups` and `ghanapostGps` in a context stand in for host callbacks.

**Required coverage:** at least 40 cases spanning:

- every operator and function above
- null handling
- string/number coercion
- precedence
- repeat context
- the parse errors listed below

**Parse errors that must be raised:**

- unknown function
- unbalanced parentheses
- unterminated string
- reference to an unknown field, checked only when the context includes `fields` (the list of valid root keys). Without `fields`, unknown references evaluate to null.
- missing operands, unexpected or trailing tokens, empty expressions, wrong function arity
