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


# --- project level ---------------------------------------------------------------------

PROJECT_ROLE_RANK: dict[str, int] = {"viewer": 10, "collector": 20, "manager": 30}


def effective_project_role(membership: Membership, project_member_role: str | None) -> str | None:
    """
    Org owners, admins and managers manage every project. Others have the role of their
    ProjectMember row, or no access at all.
    """
    if role_at_least(membership.role, Role.MANAGER):
        return "manager"
    return project_member_role


def require_project_role(
    membership: Membership, project_member_role: str | None, minimum: str
) -> str:
    role = effective_project_role(membership, project_member_role)
    if role is None or PROJECT_ROLE_RANK[role] < PROJECT_ROLE_RANK[minimum]:
        raise Forbidden(f"This action needs the project {minimum} role or higher.")
    return role
