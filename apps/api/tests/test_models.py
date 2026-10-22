import uuid

import pytest

from precisecapture.common.ids import uuid7
from tests.testapp.models import Widget


def test_uuid7_is_stdlib_uuid_version_7_and_time_ordered():
    a, b = uuid7(), uuid7()
    assert isinstance(a, uuid.UUID)
    assert a.version == 7
    assert a < b  # created later sorts later


@pytest.mark.django_db
def test_base_model_assigns_uuid7_pk_and_timestamps():
    w = Widget.objects.create(name="a")
    assert w.id.version == 7
    assert w.created_at is not None and w.updated_at is not None
    before = w.updated_at
    w.name = "b"
    w.save()
    w.refresh_from_db()
    assert w.updated_at > before


@pytest.mark.django_db
def test_base_model_keeps_client_supplied_id():
    client_id = uuid.UUID("0192f0c1-0000-7000-8000-000000000001")
    w = Widget.objects.create(id=client_id, name="from device")
    assert Widget.objects.get(pk=client_id) == w


@pytest.mark.django_db
def test_default_ordering_is_creation_order():
    names = [Widget.objects.create(name=str(i)).name for i in range(5)]
    assert list(Widget.objects.values_list("name", flat=True)) == names
