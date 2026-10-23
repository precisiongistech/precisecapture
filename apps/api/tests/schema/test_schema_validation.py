"""The server validates contract documents with the same JSON Schemas as the apps."""

from precisecapture.common.schema_validation import (
    load_example,
    validate_capture_profile,
    validate_layer_schema,
    validate_sync_document,
)

UUID = "0192f0c1-0000-7000-8000-000000000001"


def test_pilot_examples_validate():
    assert validate_layer_schema(load_example("farmers.layer-schema.json")) == []
    assert validate_layer_schema(load_example("farms.layer-schema.json")) == []
    assert validate_capture_profile(load_example("farms.capture-profile.json")) == []


def test_layer_schema_errors_are_per_field():
    issues = validate_layer_schema(
        {
            "schemaVersion": 1,
            "fields": [{"key": "Bad Key", "type": "select_one"}, {"key": "ok", "type": "nope"}],
        }
    )
    fields = {i.field for i in issues}
    assert "fields.0.key" in fields
    assert "fields.0.options" in fields
    assert "fields.1.type" in fields
    assert all(i.code and i.message for i in issues)


def test_unknown_keys_are_errors_on_the_server():
    issues = validate_layer_schema(
        {"schemaVersion": 1, "fields": [{"key": "a", "type": "text", "futureKey": 1}], "top": 1}
    )
    assert {i.field for i in issues} == {"top", "fields.0.futureKey"}
    assert {i.code for i in issues} == {"additionalProperties"}


def test_relation_layer_must_be_a_key():
    issues = validate_layer_schema(
        {
            "schemaVersion": 1,
            "fields": [{"key": "f", "type": "relation", "relation": {"layer": "Not-A-Key"}}],
        }
    )
    assert [i.field for i in issues] == ["fields.0.relation.layer"]


def test_capture_profile_layer_refs_and_bounds():
    issues = validate_capture_profile(
        {"snapping": {"layers": ["self", "Roads!"]}, "stream": {"intervalMeters": 0.5}}
    )
    assert {(i.field, i.code) for i in issues} == {
        ("snapping.layers.1", "pattern"),
        ("stream.intervalMeters", "minimum"),
    }


def test_partial_profiles_are_valid():
    assert validate_capture_profile({"gps": {"averaging": {"enabled": True, "locked": True}}}) == []


def _change(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "change_id": UUID,
        "op": "create",
        "entity": "feature",
        "id": UUID,
        "layer_id": UUID,
        "base_version": None,
        "schema_version": 1,
        "geom": {"type": "Point", "coordinates": [-2.1, 6.2]},
        "attributes": {},
        "meta": {"device_id": UUID, "captured_at": "2026-10-22T10:00:00Z"},
    }
    base.update(over)
    return base


def test_sync_push_request():
    assert validate_sync_document("PushRequest", {"project_id": UUID, "changes": [_change()]}) == []
    issues = validate_sync_document(
        "PushRequest", {"project_id": UUID, "changes": [_change(layer_id="lyr_farms")]}
    )
    assert [(i.field, i.code) for i in issues] == [("changes.0.layer_id", "format")]
    issues = validate_sync_document(
        "PushRequest", {"project_id": UUID, "changes": [_change(op="update", base_version=3)]}
    )
    assert "changes.0.changed_fields" in {i.field for i in issues}


def test_sync_responses():
    assert (
        validate_sync_document(
            "PushResponse",
            {"results": [{"change_id": UUID, "status": "accepted"}], "last_seq": 1},
        )
        == []
    )
    assert (
        validate_sync_document(
            "PullResponse",
            {
                "items": [
                    {
                        "seq": 1,
                        "entity": "feature",
                        "id": UUID,
                        "layer_id": UUID,
                        "version": 1,
                        "deleted": False,
                    }
                ],
                "next_cursor": 1,
                "has_more": False,
                "config_version": 3,
            },
        )
        == []
    )
