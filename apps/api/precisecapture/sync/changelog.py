"""
Changelog recording: every feature write (web, sync, review) takes the next seq for its
project inside a FOR UPDATE lock on ProjectSyncState. Called by features.services within the
write transaction, so commit order == seq order (ENGINEERING_NOTES.md §2).
"""

import uuid

from django.db import transaction

from precisecapture.features.models import Feature
from precisecapture.sync.models import ChangeLog, ChangeOp, ProjectSyncState


def lock_project_state(project_id: uuid.UUID, org_id: uuid.UUID) -> ProjectSyncState:
    """Lock (creating on first use) the per-project sync state row for this transaction."""
    state = ProjectSyncState.objects.select_for_update().filter(project_id=project_id).first()
    if state is None:
        ProjectSyncState.objects.get_or_create(project_id=project_id, defaults={"org_id": org_id})
        state = ProjectSyncState.objects.select_for_update().get(project_id=project_id)
    return state


def next_seq(state: ProjectSyncState) -> int:
    state.last_seq += 1
    state.save(update_fields=["last_seq", "updated_at"])
    return state.last_seq


def record(
    feature: Feature,
    op: str,
    *,
    change_id: uuid.UUID | None = None,
    device_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    state: ProjectSyncState | None = None,
) -> ChangeLog:
    """Append a changelog row for the feature's current version. Must run inside a transaction."""
    assert transaction.get_connection().in_atomic_block, "changelog.record needs a transaction"
    if state is None:
        state = lock_project_state(feature.project_id, feature.org_id)
    seq = next_seq(state)
    return ChangeLog.objects.create(
        org_id=feature.org_id,
        project_id=feature.project_id,
        seq=seq,
        entity="feature",
        entity_id=feature.id,
        op=op,
        feature_version=feature.version,
        device_id=device_id,
        user_id=user_id,
        change_id=change_id,
    )


__all__ = ["ChangeOp", "lock_project_state", "next_seq", "record"]
