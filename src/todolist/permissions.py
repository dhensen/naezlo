"""The permission service: which role a principal has on a project or a list.

Every permission check goes through here with a `Principal` (a user or an agent). Routes use
the dependencies built on it (`require_project_role` in `todolist.api.deps`); MCP tools call
these functions directly.

Rules (DECISIONS.md, "ACL"):
- Owners and admins of the project's organization are admin on every project in it.
- Everyone else has the role of their grant on the project, or no role at all.
- No role means the project does not exist for that principal (the caller answers 404).
- On a list, a list grant replaces the project role for everyone but those owners and admins:
  it can raise it, lower it, take it away (`none`) or give access without any project role.
- The list mode comes on top of the role (`list_access`, the one check for everything that
  happens to a list or its items): a human-only list does not exist for agents, and in an
  AI-only list people read but leave the items alone; only its admins still manage the list.
"""

import enum
from dataclasses import dataclass
from typing import cast

from sqlalchemy import Select, and_, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from todolist.errors import AppError, ForbiddenError
from todolist.models import (
    ListGrant,
    ListMode,
    ListRole,
    Membership,
    MembershipRole,
    PrincipalKind,
    Project,
    ProjectGrant,
    ProjectRole,
    TodoList,
)
from todolist.principals import Principal
from todolist.services.organizations import can_manage_organization

_RANK = {ProjectRole.VIEWER: 1, ProjectRole.EDITOR: 2, ProjectRole.ADMIN: 3}


def role_at_least(role: ProjectRole | None, minimum: ProjectRole) -> bool:
    """Whether `role` is `minimum` or higher. No role is never enough."""
    return role is not None and _RANK[role] >= _RANK[minimum]


async def effective_project_role(
    session: AsyncSession, principal: Principal, project: Project
) -> ProjectRole | None:
    """The principal's role on the project; None when the project does not exist for them.

    A user must (still) be a member of the project's organization and an agent must belong to
    it: a grant alone gives nothing. This is looked up here, so the caller does not have to
    have checked the membership before building the principal.
    """
    if principal.organization_id != project.organization_id:
        return None
    if principal.kind is PrincipalKind.AGENT:
        # `Principal.for_agent` takes the organization from the agent itself.
        return await session.scalar(
            select(ProjectGrant.role).where(
                ProjectGrant.project_id == project.id, ProjectGrant.agent_id == principal.id
            )
        )
    row = (
        await session.execute(
            select(Membership.role, ProjectGrant.role)
            .outerjoin(
                ProjectGrant,
                and_(
                    ProjectGrant.project_id == project.id,
                    ProjectGrant.user_id == Membership.user_id,
                ),
            )
            .where(
                Membership.organization_id == project.organization_id,
                Membership.user_id == principal.id,
            )
        )
    ).one_or_none()
    if row is None:
        return None
    membership_role, grant_role = row
    if can_manage_organization(membership_role):
        return ProjectRole.ADMIN
    return grant_role


async def effective_list_role(
    session: AsyncSession, principal: Principal, todo_list: TodoList, project: Project
) -> ProjectRole | None:
    """The principal's role on the list; None when the list does not exist for them.

    `project` is the list's project. Owners and admins of its organization are admin. For
    everyone else a grant on the list decides when there is one (`none` means no access),
    otherwise the role on the project. As on a project, a user must be a member of the
    organization and an agent must belong to it.

    This is the role alone. What the principal may do with it also depends on the list mode:
    check that with `list_access`.
    """
    if todo_list.project_id != project.id:
        raise ValueError("project is not the list's project")
    if principal.organization_id != project.organization_id:
        return None
    if principal.kind is PrincipalKind.AGENT:
        list_role = await session.scalar(
            select(ListGrant.role).where(
                ListGrant.list_id == todo_list.id, ListGrant.agent_id == principal.id
            )
        )
        if list_role is not None:
            return list_role.project_role
        return await effective_project_role(session, principal, project)
    row = (
        await session.execute(
            select(Membership.role, ListGrant.role, ProjectGrant.role)
            .outerjoin(
                ListGrant,
                and_(ListGrant.list_id == todo_list.id, ListGrant.user_id == Membership.user_id),
            )
            .outerjoin(
                ProjectGrant,
                and_(
                    ProjectGrant.project_id == project.id,
                    ProjectGrant.user_id == Membership.user_id,
                ),
            )
            .where(
                Membership.organization_id == project.organization_id,
                Membership.user_id == principal.id,
            )
        )
    ).one_or_none()
    if row is None:
        return None
    membership_role, _, project_role = row
    # The outer joins make the grant roles optional, which the row type does not say.
    list_role = cast("ListRole | None", row[1])
    if can_manage_organization(membership_role):
        return ProjectRole.ADMIN
    if list_role is not None:
        return list_role.project_role
    return project_role


class ListAction(enum.Enum):
    """What a principal wants to do with a list. `ListAccess` decides whether they may."""

    # See the list and its items.
    READ = "read"
    # Create, edit, complete, reopen, move or delete items.
    CHANGE_ITEMS = "change_items"
    # Change the list's name, description or mode.
    EDIT_LIST = "edit_list"
    # Manage the list's grants, delete the list.
    ADMINISTER = "administer"


_MINIMUM_ROLE = {
    ListAction.READ: ProjectRole.VIEWER,
    ListAction.CHANGE_ITEMS: ProjectRole.EDITOR,
    ListAction.EDIT_LIST: ProjectRole.EDITOR,
    ListAction.ADMINISTER: ProjectRole.ADMIN,
}

LIST_AI_ONLY = "list_ai_only"


@dataclass(frozen=True)
class ListAccess:
    """What one principal may do with one list: their role, the list mode and their kind
    together. Get it from `list_access`; it exists only for a list the principal can see."""

    role: ProjectRole
    mode: ListMode
    kind: PrincipalKind

    def denial(self, action: ListAction) -> AppError | None:
        """Why the principal may not do this, as the error to raise; None when they may.

        The role is checked first (403 `forbidden`). Then the mode: in an AI-only list a
        person cannot change items, and changes the list itself only as its admin (403
        `list_ai_only`). Agents are not held back here: in a human-only list they have no
        `ListAccess` at all.
        """
        minimum = _MINIMUM_ROLE[action]
        if not role_at_least(self.role, minimum):
            return ForbiddenError(f"This needs the {minimum.value} role on the list")
        if self.mode is ListMode.AI_ONLY and self.kind is PrincipalKind.USER:
            if action is ListAction.CHANGE_ITEMS:
                return AppError(
                    403, LIST_AI_ONLY, "This list is AI-only: people can read its items only"
                )
            if action is ListAction.EDIT_LIST and self.role is not ProjectRole.ADMIN:
                return AppError(
                    403, LIST_AI_ONLY, "This list is AI-only: only its admins can change it"
                )
        return None

    def allows(self, action: ListAction) -> bool:
        return self.denial(action) is None

    def require(self, action: ListAction) -> None:
        """Raise the 403 for this action when the principal may not do it."""
        denial = self.denial(action)
        if denial is not None:
            raise denial


async def list_access(
    session: AsyncSession, principal: Principal, todo_list: TodoList, project: Project
) -> ListAccess | None:
    """The one check for every operation on a list or its items: the principal's role on the
    list (`effective_list_role`) combined with the list mode and the principal's kind.

    None when the list does not exist for the principal (the caller answers 404): they have
    no role on it, or they are an agent and the list is human-only, whatever their grants.
    Otherwise ask the result with `allows(action)` or `require(action)`.
    """
    if principal.kind is PrincipalKind.AGENT and todo_list.mode is ListMode.HUMAN_ONLY:
        return None
    role = await effective_list_role(session, principal, todo_list, project)
    if role is None:
        return None
    return ListAccess(role=role, mode=todo_list.mode, kind=principal.kind)


def visible_lists(principal: Principal, project: Project) -> Select[TodoList]:
    """A query for the lists of the project that the principal can see, in no order.

    The same rules as `list_access`, for a whole project at once: a role on the list, and for
    an agent a list that is not human-only. It can give lists to a principal without a role
    on the project itself (a list grant only).
    """
    in_project = select(TodoList).where(TodoList.project_id == project.id)
    if principal.organization_id != project.organization_id:
        return in_project.where(false())
    is_user = principal.kind is PrincipalKind.USER
    list_role = (
        select(ListGrant.role)
        .where(
            ListGrant.list_id == TodoList.id,
            (ListGrant.user_id if is_user else ListGrant.agent_id) == principal.id,
        )
        .scalar_subquery()
    )
    has_project_role = (
        select(ProjectGrant.id)
        .where(
            ProjectGrant.project_id == project.id,
            (ProjectGrant.user_id if is_user else ProjectGrant.agent_id) == principal.id,
        )
        .exists()
    )
    granted = or_(
        and_(list_role.is_not(None), list_role != ListRole.NONE),
        and_(list_role.is_(None), has_project_role),
    )
    if not is_user:
        return in_project.where(granted, TodoList.mode != ListMode.HUMAN_ONLY)
    membership_role = (
        select(Membership.role)
        .where(
            Membership.organization_id == project.organization_id,
            Membership.user_id == principal.id,
        )
        .scalar_subquery()
    )
    manages = membership_role.in_(
        [role for role in MembershipRole if can_manage_organization(role)]
    )
    return in_project.where(manages | and_(membership_role.is_not(None), granted))


def visible_projects(principal: Principal) -> Select[Project]:
    """A query for the projects of the principal's organization that the principal has a role on.

    The same rules as `effective_project_role`, for a whole organization at once.
    """
    in_organization = select(Project).where(Project.organization_id == principal.organization_id)
    if principal.kind is PrincipalKind.AGENT:
        return in_organization.where(
            Project.id.in_(
                select(ProjectGrant.project_id).where(ProjectGrant.agent_id == principal.id)
            )
        )
    membership_role = (
        select(Membership.role)
        .where(
            Membership.organization_id == principal.organization_id,
            Membership.user_id == principal.id,
        )
        .scalar_subquery()
    )
    manages = membership_role.in_(
        [role for role in MembershipRole if can_manage_organization(role)]
    )
    granted = and_(
        membership_role.is_not(None),
        Project.id.in_(select(ProjectGrant.project_id).where(ProjectGrant.user_id == principal.id)),
    )
    return in_organization.where(manages | granted)


async def project_stays_administrable(
    session: AsyncSession, project: Project, without: ProjectGrant
) -> bool:
    """Whether a person can still administer the project once the grant `without` stops being
    an admin grant (it is revoked or downgraded).

    True when the organization has an owner or admin (they are admin on every project), or when
    another member holds an admin grant. Agent grants don't count: agents get their access from
    people, so a project that only an agent administers is out of everyone's reach.
    """
    manager = await session.scalar(
        select(Membership.id)
        .where(
            Membership.organization_id == project.organization_id,
            Membership.role.in_([role for role in MembershipRole if can_manage_organization(role)]),
        )
        .limit(1)
    )
    if manager is not None:
        return True
    other_admin = await session.scalar(
        select(ProjectGrant.id)
        .join(
            Membership,
            and_(
                Membership.user_id == ProjectGrant.user_id,
                Membership.organization_id == project.organization_id,
            ),
        )
        .where(
            ProjectGrant.project_id == project.id,
            ProjectGrant.role == ProjectRole.ADMIN,
            ProjectGrant.id != without.id,
        )
        .limit(1)
    )
    return other_admin is not None
