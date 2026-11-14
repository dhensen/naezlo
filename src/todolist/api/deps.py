"""Dependencies shared by the routers.

Org-scoped routes (`/orgs/{org_id}/...`) take `org: OrgContextDep`, or `org: OrgAdminContextDep`
when the action needs an owner or admin. Project-scoped routes (`/projects/{project_id}...`) take
`ctx: ProjectContextDep`.
"""

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from todolist.auth import CurrentUser
from todolist.db import SessionDep
from todolist.errors import ForbiddenError, NotFoundError
from todolist.models import Membership, MembershipRole, Organization, Project, User
from todolist.principals import Principal
from todolist.services.organizations import can_manage_organization, get_organization_membership
from todolist.services.projects import get_project_membership


@dataclass(frozen=True)
class OrgContext:
    """The organization in the path and the caller's membership in it."""

    organization: Organization
    membership: Membership
    user: User

    @property
    def role(self) -> MembershipRole:
        return self.membership.role

    @property
    def principal(self) -> Principal:
        """The caller as the actor for permission checks and audit events."""
        return Principal.for_user(self.user, self.organization.id)


async def org_context(org_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> OrgContext:
    """Resolve `{org_id}` for the signed-in user; 404 when they are not a member."""
    found = await get_organization_membership(session, org_id, user.id)
    if found is None:
        # Same answer for "does not exist" and "not yours": don't reveal which ids exist.
        raise NotFoundError("Organization not found")
    organization, membership = found
    return OrgContext(organization=organization, membership=membership, user=user)


OrgContextDep = Annotated[OrgContext, Depends(org_context)]


async def org_admin_context(org: OrgContextDep) -> OrgContext:
    """Like `org_context`, and 403 unless the caller is owner or admin of the organization."""
    if not can_manage_organization(org.role):
        raise ForbiddenError("Only organization owners and admins can do this")
    return org


OrgAdminContextDep = Annotated[OrgContext, Depends(org_admin_context)]


@dataclass(frozen=True)
class ProjectContext:
    """The project in the path and the caller's membership in the project's organization."""

    project: Project
    membership: Membership
    user: User

    @property
    def principal(self) -> Principal:
        """The caller as the actor for permission checks and audit events."""
        return Principal.for_user(self.user, self.project.organization_id)


async def project_context(
    project_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> ProjectContext:
    """Resolve `{project_id}` for the signed-in user; 404 when they can't see the project.

    For now every member of the project's organization can see and change it.
    """
    found = await get_project_membership(session, project_id, user.id)
    if found is None:
        # Same answer for "does not exist" and "not yours": don't reveal which ids exist.
        raise NotFoundError("Project not found")
    project, membership = found
    return ProjectContext(project=project, membership=membership, user=user)


ProjectContextDep = Annotated[ProjectContext, Depends(project_context)]
