"""The Python expression evaluator passes every shared vector (TS must pass the same ones)."""

import pytest

from precisecapture.common.expr import (
    EvalContext,
    ExpressionParseError,
    evaluate,
    parse,
    referenced_fields,
)
from precisecapture.common.schema_validation import load_test_vectors

VECTORS = load_test_vectors("expressions.json")
CASES = {c["name"]: c for c in VECTORS["cases"]}


def test_vector_file_has_required_coverage():
    assert len(CASES) >= 40
    assert len(CASES) == len(VECTORS["cases"]), "vector names must be unique"


@pytest.mark.parametrize("name", sorted(CASES))
def test_vector(name: str):
    case = CASES[name]
    ctx = EvalContext.from_vector(case.get("context", {}), VECTORS["defaults"])
    if case.get("expectError") == "parse":
        with pytest.raises(ExpressionParseError):
            parse(case["expr"], ctx.fields)
        return
    assert evaluate(case["expr"], ctx) == case["expect"]


def test_referenced_fields_in_first_seen_order():
    assert referenced_fields("${b} + ${a} * ${b} + count(${rows.age}) + .") == ["b", "a", "rows"]
    assert referenced_fields("1 + 2") == []


def test_parse_error_carries_position():
    with pytest.raises(ExpressionParseError) as exc:
        parse("1 + $ 2")
    assert exc.value.position == 4
    assert "position 4" in str(exc.value)


def test_unknown_field_is_a_parse_error_only_with_fields():
    assert evaluate("${nope}", EvalContext()) is None
    with pytest.raises(ExpressionParseError):
        parse("${nope}", fields=["crop"])


def test_lookup_callback_is_used():
    ctx = EvalContext(lookup=lambda layer, fld: f"{layer}/{fld}")
    assert evaluate("lookup('districts', 'name')", ctx) == "districts/name"
