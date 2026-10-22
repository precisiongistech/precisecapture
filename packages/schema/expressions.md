# PreciseCapture expression language (v1)

Expressions drive `relevant` (show/hide), `required` (when a string), `constraint`, and `calculate` fields. The same expression must give the **same result** on the phone (TypeScript), the web (TypeScript) and the server (Python). Both implementations must pass every case in `test-vectors/expressions.json`. **Never implement with `eval`.** Use a small recursive-descent or Pratt parser.

The syntax is deliberately close to XLSForm/ODK, so XLSForm import (later) maps cleanly.

## Values and types

| Type | Literal examples | Notes |
| --- | --- | --- |
| number | `3`, `2.5`, `-1` | IEEE double; integer results print without `.0` |
| string | `'cocoa'`, `"Juaboso"` | single or double quotes; `\'` escapes |
| boolean | `true()`, `false()` | results of comparisons and logic |

**Stored answer values:** `yes_no` stores the strings `'yes'` / `'no'`; `select_one` a string; `select_many` an array of strings; numbers as numbers; dates as `YYYY-MM-DD` strings.
| null | an empty or unanswered field | |

**Field references**

- `${key}` is the value of another field in the same record. Inside a repeat, `${key}` refers to the sibling in the same repeat item.
- `.` is the current field's own value (used in `constraint`).

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
| `coalesce(a, b)` | a if not null/empty, else b |
| `concat(a, b, ...)` | string concatenation (null becomes empty) |
| `string-length(s)` | length in characters |
| `selected(${field}, 'value')` | true if a select_many contains the value (or a select_one equals it) |
| `count-selected(${field})` | number of selected values |
| `count(${repeat})` | number of items in a repeat |
| `sum(${repeat_field})` | sum of a numeric field across repeat items |
| `round(x, digits)` | round half away from zero |
| `int(x)` | truncate toward zero |
| `number(x)` | parse number (null if invalid) |
| `today()` | local date `YYYY-MM-DD` (injected by the host for tests) |
| `now()` | ISO datetime (injected by the host for tests) |
| `regex(s, pattern)` | true if the ECMAScript-compatible pattern matches |
| `geom_area()` | area of the record's geometry in m² (geodesic); null if no polygon |
| `geom_length()` | length or perimeter in m (geodesic) |
| `lookup('layer', 'field')` | value of `field` from the reference-layer polygon containing this record's point/centroid. Client-side only; the server returns the stored value |
| `ghanapost_gps()` | GhanaPostGPS digital address of the centroid (client-side, when available) |
| `nearest('layer', 'field')` | *Reserved for a later version.* Parsers must reject it in v1 as an unknown function |

Host-provided values (`today()`, `now()`, `geom_area()`, `geom_length()`) come from an evaluation context, so tests are deterministic.

## Evaluation context (both implementations)

```ts
interface EvalContext {
  values: Record<string, unknown>;      // current record's answers
  fields?: string[];                    // valid keys; enables the unknown-field parse error
  self?: unknown;                       // value for "."
  repeat?: Record<string, unknown>[];   // when evaluating inside a repeat
  now: string;                          // ISO datetime
  today: string;                        // YYYY-MM-DD
  geomAreaM2?: number | null;
  geomLengthM?: number | null;
  lookup?: (layer: string, field: string) => unknown;
}
```

## Test vector format

Each test vector in `test-vectors/expressions.json` has one of these shapes:

```json
{ "name": "…", "expr": "…", "context": { … }, "expect": <value> }
{ "name": "…", "expr": "…", "context": { … }, "expectError": "parse" }
```

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
- reference to an unknown field, checked only when the context includes `fields` (the list of valid keys). Without `fields`, unknown references evaluate to null.
