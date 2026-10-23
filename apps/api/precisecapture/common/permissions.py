"""
Role checks for tenant endpoints.

    membership = require_role(request, Role.ADMIN)   # admin or owner

Project-level checks (ProjectMember roles, assigned areas) plug in here in M3 through
`require_project_role`, so every permission decision lives in one module.
"""

from django.http import HttpRequest

from precisecapture.common.auth import current_membership
from precisecapture.common.errors import Forbidden
from precisecapture.orgs.models import Membership, Role, role_at_least


def require_role(request: HttpRequest, minimum: str) -> Membership:
    membership = current_membership(request)
    if not role_at_least(membership.role, minimum):
        raise Forbidden(f"This action needs the {minimum} role or higher.")
    return membership


def can_assign_role(actor_role: str, target_role: str) -> bool:
    """Nobody can grant a role above their own; only owners can grant owner."""
    if target_role == Role.OWNER:
        return actor_role == Role.OWNER
    return role_at_least(actor_role, Role.ADMIN) and role_at_least(actor_role, target_role)
