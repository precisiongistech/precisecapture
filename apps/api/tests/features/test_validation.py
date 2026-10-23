"""features.validation: attributes against a published layer schema (pure, no DB)."""

from datetime import UTC, datetime
from typing import Any

import pytest

from precisecapture.common.schema_validation import load_example
from precisecapture.features.validation import AttributeContext, validate_attributes

NOW = datetime(2026, 10, 22, 10, 0, tzinfo=UTC)
UUID1 = "0192f0c1-1234-7abc-8def-000000000001"
UUID2 = "0192f0c1-1234-7abc-8def-000000000002"


def ctx(**kw: Any) -> AttributeContext:
    return AttributeContext(now=NOW, **kw)


def codes(result: Any) -> dict[str, str]:
    return {e.field: e.code for e in result.errors}


def schema(*fields: dict[str, Any], lists: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"schemaVersion": 1, "fields": list(fields), "lists": lists or {}}


# --- pilot schemas ------------------------------------------------------------------------


def test_farmers_happy_path():
    r = validate_attributes(
        load_example("farmers.layer-schema.json"),
        {
            "full_name": "Ama Mensah",
            "gender": "female",
            "year_of_birth": "1985",
            "id_type": "ghana_card",
            "id_number": "GHA-123456789-0",
            "phone": "+233241234567",
            "photo": UUID1,
            "region": "western_north",
            "district": "juaboso",
            "community": "Boinzan",
            "cooperative": "Kuapa",
            "consent": True,
        },
        context=ctx(),
    )
    assert r.ok, r.errors
    assert r.values["year_of_birth"] == 1985
    assert r.values["photo"] == [UUID1]
    assert r.values["consent"] == "yes"
    assert r.unique_checks == [("id_number", "GHA-123456789-0")]


def test_farms_happy_path_recomputes_calculations():
    r = validate_attributes(
        load_example("farms.layer-schema.json"),
        {
            "farmer": UUID1,
            "farm_code": "WN-0042",
            "crop": "cocoa",
            "planting_year": 2018,
            "ownership": "owner",
            "area_ha": 999,  # device value is overridden
            "photos": [UUID1, UUID2],
        },
        context=ctx(geom_area_m2=52000.0),
    )
    assert r.ok, r.errors
    assert r.values["area_ha"] == 5.2
    assert r.values["needs_polygon_for_eudr"] == "yes"
    assert r.relation_refs == [("farmer", "lyr_farmers", UUID1)]
    assert r.unique_checks == [("farm_code", "WN-0042")]


def test_farms_required_and_relevant():
    r = validate_attributes(
        load_example("farms.layer-schema.json"),
        {"crop": "other", "planting_year": 1800, "photos": []},
        context=ctx(geom_area_m2=100.0),
    )
    assert codes(r) == {
        "farmer": "required",
        "other_crop": "required",
        "planting_year": "min",
        "photos": "min_count",  # min: 1 wins over required for counted fields
    }


def test_farmers_consent_constraint_message():
    r = validate_attributes(
        load_example("farmers.layer-schema.json"),
        {
            "full_name": "A B",
            "region": "western_north",
            "district": "juaboso",
            "community": "x",
            "consent": "no",
        },
        context=ctx(),
    )
    assert codes(r)["consent"] == "constraint"
    assert [e.message for e in r.errors if e.field == "consent"] == [
        "Consent is required to register the farmer."
    ]


# --- relevance ------------------------------------------------------------------------------


def test_irrelevant_field_is_dropped_even_when_required():
    s = schema(
        {
            "key": "crop",
            "type": "select_one",
            "options": [{"value": "a", "label": "A"}, {"value": "other", "label": "O"}],
        },
        {"key": "other_crop", "type": "text", "relevant": "${crop} = 'other'", "required": True},
    )
    r = validate_attributes(s, {"crop": "a", "other_crop": "stale value"}, context=ctx())
    assert r.ok
    assert "other_crop" not in r.values
    r = validate_attributes(s, {"crop": "other"}, context=ctx())
    assert codes(r) == {"other_crop": "required"}


def test_null_relevant_shows_the_field():
    s = schema({"key": "n", "type": "text", "relevant": "${missing} > 1", "required": True})
    r = validate_attributes(s, {}, context=ctx())
    assert codes(r) == {"n": "required"}


# --- error codes ----------------------------------------------------------------------------


def test_unknown_and_no_value_fields():
    s = schema(
        {"key": "note1", "type": "note"},
        {"key": "g", "type": "group", "fields": [{"key": "inner", "type": "text"}]},
    )
    r = validate_attributes(s, {"bogus": 1, "note1": "x", "g": {}, "inner": "ok"}, context=ctx())
    assert codes(r) == {"bogus": "unknown_field", "note1": "not_a_value", "g": "not_a_value"}
    assert r.values == {"inner": "ok"}


@pytest.mark.parametrize(
    ("fld", "value", "code"),
    [
        ({"key": "t", "type": "text"}, 5, "type"),
        ({"key": "t", "type": "text", "validation": {"minLength": 3}}, "ab", "min_length"),
        ({"key": "t", "type": "text", "validation": {"maxLength": 3}}, "abcd", "max_length"),
        (
            {"key": "t", "type": "text", "validation": {"pattern": "^[A-Z]{2}-\\d{4}$"}},
            "wn-1",
            "pattern",
        ),
        ({"key": "n", "type": "number"}, "abc", "type"),
        ({"key": "n", "type": "integer"}, 2.5, "type"),
        ({"key": "n", "type": "integer", "validation": {"min": 1}}, 0, "min"),
        ({"key": "n", "type": "decimal", "validation": {"max": 10}}, 10.5, "max"),
        ({"key": "d", "type": "date"}, "22/10/2026", "format"),
        ({"key": "d", "type": "time"}, "9am", "format"),
        ({"key": "d", "type": "datetime"}, "2026-10-22 10:00", "format"),
        (
            {"key": "s", "type": "select_one", "options": [{"value": "a", "label": "A"}]},
            "z",
            "option",
        ),
        (
            {"key": "s", "type": "select_many", "options": [{"value": "a", "label": "A"}]},
            ["a", "z"],
            "option",
        ),
        (
            {"key": "s", "type": "select_many", "options": [{"value": "a", "label": "A"}]},
            ["a", "a"],
            "type",
        ),
        ({"key": "y", "type": "yes_no"}, "maybe", "type"),
        ({"key": "p", "type": "phone"}, "0241234567", "format"),
        ({"key": "e", "type": "email"}, "not-an-email", "format"),
        ({"key": "f", "type": "photo"}, ["nope"], "type"),
        ({"key": "f", "type": "photo", "min": 2}, [UUID1], "min_count"),
        ({"key": "f", "type": "photo", "max": 1}, [UUID1, UUID2], "max_count"),
        ({"key": "g", "type": "geopoint"}, {"lon": 200, "lat": 0}, "type"),
        ({"key": "r", "type": "relation", "relation": {"layer": "lyr_x"}}, "not-a-uuid", "type"),
        (
            {"key": "rep", "type": "repeat", "fields": [{"key": "a", "type": "text"}]},
            "rows?",
            "type",
        ),
        (
            {"key": "rep", "type": "repeat", "min": 1, "fields": [{"key": "a", "type": "text"}]},
            [],
            "min_count",
        ),
    ],
)
def test_type_error_codes(fld, value, code):
    r = validate_attributes(schema(fld), {fld["key"]: value}, context=ctx())
    assert codes(r) == {fld["key"]: code}


def test_coercions():
    s = schema(
        {"key": "n", "type": "number"},
        {"key": "i", "type": "integer"},
        {"key": "y", "type": "yes_no"},
        {"key": "f", "type": "photo"},
        {"key": "g", "type": "geopoint"},
        {"key": "m", "type": "select_many", "options": [{"value": "a", "label": "A"}]},
        {"key": "e", "type": "integer"},
    )
    r = validate_attributes(
        s,
        {
            "n": "2.50",
            "i": "12",
            "y": False,
            "f": UUID1,
            "g": {"lon": -2.5, "lat": 6.2},
            "m": "a",
            "e": "",
        },
        context=ctx(),
    )
    assert r.ok, r.errors
    assert r.values == {
        "n": 2.5,
        "i": 12,
        "y": "no",
        "f": [UUID1],
        "g": {"type": "Point", "coordinates": [-2.5, 6.2]},
        "m": ["a"],
        "e": None,
    }


def test_integer_valued_floats_become_ints():
    r = validate_attributes(
        schema({"key": "n", "type": "number"}, {"key": "i", "type": "integer"}),
        {"n": 3.0, "i": 12.0},
        context=ctx(),
    )
    assert r.values == {"n": 3, "i": 12} and all(isinstance(v, int) for v in r.values.values())


def test_empty_text_stays_empty_text_but_other_types_become_null():
    s = schema({"key": "t", "type": "text"}, {"key": "d", "type": "date", "required": True})
    r = validate_attributes(s, {"t": "", "d": ""}, context=ctx())
    assert r.values["t"] == ""
    assert codes(r) == {"d": "required"}


# --- select cascades -----------------------------------------------------------------------


def test_choice_filter_parent_limits_options():
    s = load_example("farmers.layer-schema.json")
    base = {"full_name": "Ama", "community": "x", "consent": "yes"}
    r = validate_attributes(s, {**base, "region": "ashanti", "district": "juaboso"}, context=ctx())
    assert codes(r) == {"district": "option"}
    r = validate_attributes(
        s, {**base, "region": "western_north", "district": "juaboso"}, context=ctx()
    )
    assert r.ok


def test_select_many_with_cascade():
    s = schema(
        {
            "key": "region",
            "type": "select_one",
            "options": [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}],
        },
        {
            "key": "towns",
            "type": "select_many",
            "choiceFilterParent": "region",
            "options": [
                {"value": "a1", "label": "A1", "filter": {"region": "a"}},
                {"value": "b1", "label": "B1", "filter": {"region": "b"}},
            ],
        },
    )
    assert validate_attributes(s, {"region": "a", "towns": ["a1"]}, context=ctx()).ok
    assert codes(validate_attributes(s, {"region": "a", "towns": ["a1", "b1"]}, context=ctx())) == {
        "towns": "option"
    }


# --- calculate trust table ----------------------------------------------------------------


def test_calculate_recomputed_from_geometry():
    s = schema({"key": "area_ha", "type": "calculate", "expression": "geom_area() div 10000"})
    r = validate_attributes(s, {"area_ha": 42}, context=ctx(geom_area_m2=12345))
    assert r.values == {"area_ha": 1.2345}


def test_calculate_recomputed_from_attributes_and_absent_when_no_geometry():
    s = schema(
        {"key": "a", "type": "integer"},
        {"key": "b", "type": "integer"},
        {"key": "total", "type": "calculate", "expression": "${a} + ${b}"},
        {"key": "area_ha", "type": "calculate", "expression": "geom_area() div 10000"},
    )
    r = validate_attributes(s, {"a": 2, "b": "3"}, context=ctx())
    assert r.values == {"a": 2, "b": 3, "total": 5, "area_ha": None}


def test_calculate_with_host_functions_keeps_device_value_or_previous():
    s = schema(
        {"key": "district", "type": "calculate", "expression": "lookup('districts', 'name')"},
        {"key": "gpgps", "type": "calculate", "expression": "ghanapost_gps()"},
        {"key": "captured", "type": "calculate", "expression": "today()"},
    )
    r = validate_attributes(
        s,
        {"district": "Juaboso", "captured": "2026-10-01"},
        context=ctx(previous={"gpgps": "WN-0001-0001"}),
    )
    assert r.values == {"district": "Juaboso", "gpgps": "WN-0001-0001", "captured": "2026-10-01"}
    r = validate_attributes(s, {}, context=ctx())
    assert r.values == {"district": None, "gpgps": None, "captured": None}


def test_calculated_fields_are_never_required():
    s = schema(
        {"key": "x", "type": "calculate", "expression": "lookup('a', 'b')", "required": True}
    )
    assert validate_attributes(s, {}, context=ctx()).ok


# --- repeats ---------------------------------------------------------------------------------


def test_repeat_rows_validate_recursively_with_paths():
    s = schema(
        {
            "key": "occupants",
            "type": "repeat",
            "max": 2,
            "fields": [
                {"key": "name", "type": "text", "required": True},
                {"key": "age", "type": "integer", "validation": {"min": 0}},
                {
                    "key": "adult",
                    "type": "calculate",
                    "expression": "if(${age} >= 18, 'yes', 'no')",
                },
            ],
        }
    )
    r = validate_attributes(
        s,
        {
            "occupants": [
                {"name": "A", "age": "30"},
                {"age": -1},
                {"name": "C", "age": 5, "bogus": 1},
            ]
        },
        context=ctx(),
    )
    assert codes(r) == {
        "occupants": "max_count",
        "occupants.1.name": "required",
        "occupants.1.age": "min",
        "occupants.2.bogus": "unknown_field",
    }
    assert r.values["occupants"][0] == {"name": "A", "age": 30, "adult": "yes"}
    assert r.values["occupants"][2]["adult"] == "no"


def test_repeat_row_expressions_see_the_parent_record():
    s = schema(
        {"key": "household", "type": "text"},
        {
            "key": "members",
            "type": "repeat",
            "fields": [{"key": "name", "type": "text", "required": "${household} = 'yes'"}],
        },
    )
    assert codes(validate_attributes(s, {"household": "yes", "members": [{}]}, context=ctx())) == {
        "members.0.name": "required"
    }
    assert validate_attributes(s, {"household": "no", "members": [{}]}, context=ctx()).ok


# --- misc -----------------------------------------------------------------------------------


def test_errors_are_collected_for_every_field():
    s = schema(
        {"key": "a", "type": "integer"},
        {"key": "b", "type": "date"},
        {"key": "c", "type": "text", "required": True},
    )
    r = validate_attributes(s, {"a": "x", "b": "y"}, context=ctx())
    assert codes(r) == {"a": "type", "b": "format", "c": "required"}


def test_required_expression_and_none_attributes():
    s = schema(
        {"key": "crop", "type": "text"},
        {"key": "why", "type": "text", "required": "${crop} = 'other'"},
    )
    assert validate_attributes(s, None, context=ctx()).ok
    assert codes(validate_attributes(s, {"crop": "other"}, context=ctx())) == {"why": "required"}


def test_group_children_are_stored_flat_and_unique_relation_outputs():
    s = schema(
        {
            "key": "ids",
            "type": "group",
            "fields": [
                {"key": "card", "type": "text", "unique": True},
                {"key": "owner", "type": "relation", "relation": {"layer": "lyr_farmers"}},
            ],
        }
    )
    r = validate_attributes(s, {"card": "GHA-1", "owner": UUID2}, context=ctx())
    assert r.ok and r.values == {"card": "GHA-1", "owner": UUID2}
    assert r.unique_checks == [("card", "GHA-1")]
    assert r.relation_refs == [("owner", "lyr_farmers", UUID2)]


def test_present_null_is_kept_as_null():
    s = schema({"key": "notes", "type": "text"})
    assert validate_attributes(s, {"notes": None}, context=ctx()).values == {"notes": None}
