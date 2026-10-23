import pytest

from precisecapture.common.pagination import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    InvalidCursor,
    clamp_limit,
    decode_cursor,
    encode_cursor,
    paginate,
)
from tests.testapp.models import Widget


def test_cursor_round_trip_is_opaque_urlsafe():
    c = encode_cursor("0192f0c1-0000-7000-8000-000000000001")
    assert "=" not in c and "+" not in c and "/" not in c
    assert decode_cursor(c) == "0192f0c1-0000-7000-8000-000000000001"


def test_invalid_cursor_is_a_400_problem():
    with pytest.raises(InvalidCursor) as exc:
        decode_cursor("!!not base64!!")
    assert exc.value.status == 400


@pytest.mark.parametrize(
    ("given", "expected"),
    [(None, DEFAULT_LIMIT), (0, DEFAULT_LIMIT), (-5, DEFAULT_LIMIT), (10, 10), (10_000, MAX_LIMIT)],
)
def test_clamp_limit(given, expected):
    assert clamp_limit(given) == expected


@pytest.mark.django_db
def test_paginate_walks_all_rows_once_in_order():
    created = [Widget.objects.create(name=f"w{i}") for i in range(7)]
    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        page = paginate(Widget.objects.all(), cursor=cursor, limit=3)
        pages += 1
        seen += [w.name for w in page.items]
        if not page.has_more:
            assert page.next_cursor is None
            break
        assert page.next_cursor
        cursor = page.next_cursor
    assert pages == 3
    assert seen == [w.name for w in created]


@pytest.mark.django_db
def test_paginate_is_stable_when_rows_are_inserted_between_pages():
    first = [Widget.objects.create(name=f"w{i}") for i in range(3)]
    page1 = paginate(Widget.objects.all(), cursor=None, limit=2)
    Widget.objects.create(name="late")  # arrives after page 1 was read
    page2 = paginate(Widget.objects.all(), cursor=page1.next_cursor, limit=2)
    names = [w.name for w in page1.items + page2.items]
    assert names == [first[0].name, first[1].name, first[2].name, "late"]
    assert not page2.has_more


@pytest.mark.django_db
def test_paginate_empty():
    page = paginate(Widget.objects.all(), cursor=None, limit=5)
    assert page.items == [] and page.next_cursor is None and not page.has_more
