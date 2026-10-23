"""
Concurrent pushes from two devices to the same project: seq is gap-free and in commit order,
and a pull from cursor 0 returns every change exactly once (ENGINEERING_NOTES.md §2).

Uses real connections per thread (transaction=True), so the FOR UPDATE lock on
ProjectSyncState is exercised for real.
"""

import threading
from typing import Any

import pytest
from django.db import connection

from precisecapture.accounts.models import Device
from precisecapture.common.tenancy import tenant_context
from precisecapture.sync import services
from precisecapture.sync.models import ChangeLog
from tests.sync.conftest import FARMER_ATTRS, change

pytestmark = pytest.mark.django_db(transaction=True)

N_PER_DEVICE = 25


def test_concurrent_pushes_keep_seq_gap_free_and_pull_sees_every_change_once(
    phones, pilot, project
):
    a, b = phones
    farmers = pilot["lyr_farmers"]["id"]
    org_id = project.org_id
    errors: list[BaseException] = []
    results: dict[str, list[dict[str, Any]]] = {}

    def run(phone: Any, label: str) -> None:
        try:
            with tenant_context(org_id):
                user = Device.objects.get(pk=phone.device_id).user
                device = Device.objects.get(pk=phone.device_id)
                batch = [
                    change(
                        op="create",
                        layer_id=farmers,
                        attributes={**FARMER_ATTRS, "full_name": f"{label} {i}"},
                        device_id=phone.device_id,
                    )
                    for i in range(N_PER_DEVICE)
                ]
                out: list[dict[str, Any]] = []
                for c in batch:  # one change per push to maximise interleaving
                    out.extend(services.push(project, user, device, [c]).results)
                results[label] = out
        except BaseException as exc:  # surfaced below
            errors.append(exc)
        finally:
            connection.close()

    threads = [
        threading.Thread(target=run, args=(a, "A")),
        threading.Thread(target=run, args=(b, "B")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [], errors
    bad = [r for r in results["A"] + results["B"] if r["status"] != "accepted"]
    assert bad == [], bad[:3]

    with tenant_context(org_id):
        seqs = list(
            ChangeLog.objects.filter(project=project).order_by("seq").values_list("seq", flat=True)
        )
    assert seqs == list(range(1, 2 * N_PER_DEVICE + 1)), "seq must be gap-free and start at 1"

    # a pull from cursor 0 (paged) returns every change exactly once, in seq order
    seen: list[str] = []
    seen_seq: list[int] = []
    cursor = 0
    while True:
        page = a.pull(cursor, limit=7).json()
        seen += [i["id"] for i in page["items"]]
        seen_seq += [i["seq"] for i in page["items"]]
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
    assert len(seen) == 2 * N_PER_DEVICE and len(set(seen)) == len(seen)
    assert seen_seq == sorted(seen_seq) == seqs
