"""Dependencies shared by the routers.

Org-scoped routes (`/orgs/{org_id}/...`) take `org: OrgContextDep`, or `org: OrgAdminContextDep`
when the action needs an owner or admin. Project-scoped routes (`/projects/{project_id}...`) take
`ctx: ProjectContextDep` (viewer or higher), `ProjectEditorContextDep` or `ProjectAdminContextDep`,
all built with `require_project_role(...)` on the permission service (`todolist.permissions`).
List-scoped routes (`/lists/{list_id}...`) take `ctx: ListContextDep`, `ListItemEditorContextDep`,
`ListEditorContextDep` or `ListAdminContextDep`, built with `require_list_action(...)`. Item-scoped
routes (`/items/{item_id}...`) take `ctx: ItemContextDep` or `ItemEditorContextDep`, built with
`require_item_action(...)`. Both ask `list_access` of the permission service, which combines the
caller's role on the list with the list mode. The list index of
a project takes `ctx: ProjectListsContextDep`, which also lets in a caller who can only see some
of its lists.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from todolist.auth import CurrentUser
from todolist.db import SessionDep
from todolist.errors import ForbiddenError, NotFoundError
from todolist.models import (
    Item,
    Membership,
    MembershipRole,
    Organization,
    Project,
    ProjectRole,
    TodoList,
    User,
)
from todolist.permissions import (
    ListAccess,
    ListAction,
    effective_project_role,
    list_access,
    role_at_least,
)
from todolist.principals import Principal
from todolist.services.lists import list_lists
from todolist.services.organizations import can_manage_organization, get_organization_membership


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
    """The project in the path and the caller's effective role on it."""

    project: Project
    role: ProjectRole
    user: User

    @property
    def principal(self) -> Principal:
        """The caller as the actor for permission checks and audit events."""
        return Principal.for_user(self.user, self.project.organization_id)


async def project_context(
    project_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> ProjectContext:
    """Resolve `{project_id}` for the signed-in user; 404 when they have no role on the project."""
    project = await session.get(Project, project_id)
    role = (
        None
        if project is None
        # effective_project_role checks the membership itself, so this principal claims nothing.
        else await effective_project_role(
            session, Principal.for_user(user, project.organization_id), project
        )
    )
    if project is None or role is None:
        # Same answer for "does not exist" and "not yours": don't reveal which ids exist.
        raise NotFoundError("Project not found")
    return ProjectContext(project=project, role=role, user=user)


def require_project_role(minimum: ProjectRole) -> Callable[..., Awaitable[ProjectContext]]:
    """A dependency that resolves `{project_id}` and needs at least the role `minimum` on it.

    404 when the caller has no role on the project, 403 when their role is too low. Use the
    aliases below in route signatures.
    """

    async def dependency(
        ctx: Annotated[ProjectContext, Depends(project_context)],
    ) -> ProjectContext:
        if not role_at_least(ctx.role, minimum):
            raise ForbiddenError(f"This needs the {minimum.value} role on the project")
        return ctx

    return dependency


# Any role on the project (viewer or higher).
ProjectContextDep = Annotated[ProjectContext, Depends(require_project_role(ProjectRole.VIEWER))]
ProjectEditorContextDep = Annotated[
    ProjectContext, Depends(require_project_role(ProjectRole.EDITOR))
]
ProjectAdminContextDep = Annotated[ProjectContext, Depends(require_project_role(ProjectRole.ADMIN))]


@dataclass(frozen=True)
class ProjectListsContext:
    """The project in the path and the lists in it that the caller can see."""

    project: Project
    todo_lists: list[TodoList]
    user: User


async def project_lists_context(
    project_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> ProjectListsContext:
    """Resolve `{project_id}` for the list index: 404 when the caller has no role on the
    project and sees none of its lists.

    Someone with only a list grant has no role on the project, but does get their lists here.
    """
    project = await session.get(Project, project_id)
    if project is not None:
        principal = Principal.for_user(user, project.organization_id)
        todo_lists = await list_lists(session, principal, project)
        # A project without visible lists still exists for someone with a role on it.
        if todo_lists or await effective_project_role(session, principal, project) is not None:
            return ProjectListsContext(project=project, todo_lists=todo_lists, user=user)
    raise NotFoundError("Project not found")


ProjectListsContextDep = Annotated[ProjectListsContext, Depends(project_lists_context)]


@dataclass(frozen=True)
class ListContext:
    """The list in the path, its project and what the caller may do with the list."""

    todo_list: TodoList
    project: Project
    access: ListAccess
    user: User

    @property
    def role(self) -> ProjectRole:
        """The caller's effective role on the list."""
        return self.access.role

    @property
    def principal(self) -> Principal:
        """The caller as the actor for permission checks and audit events."""
        return Principal.for_user(self.user, self.project.organization_id)


async def list_context(list_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> ListContext:
    """Resolve `{list_id}` for the signed-in user; 404 when the list does not exist for them."""
    todo_list = await session.get(TodoList, list_id)
    project = None if todo_list is None else await session.get(Project, todo_list.project_id)
    access = (
        None
        if todo_list is None or project is None
        else await list_access(
            session, Principal.for_user(user, project.organization_id), todo_list, project
        )
    )
    if todo_list is None or project is None or access is None:
        # Same answer for "does not exist" and "not yours": don't reveal which ids exist.
        raise NotFoundError("List not found")
    return ListContext(todo_list=todo_list, project=project, access=access, user=user)


def require_list_action(action: ListAction) -> Callable[..., Awaitable[ListContext]]:
    """A dependency that resolves `{list_id}` and needs the caller to be allowed `action` on
    the list (`ListAccess` in the permission service: role and list mode).

    404 when the list does not exist for the caller, 403 when their role is too low
    (`forbidden`) or the list mode holds them back (`list_ai_only`). Use the aliases below in
    route signatures.
    """

    async def dependency(
        ctx: Annotated[ListContext, Depends(list_context)],
    ) -> ListContext:
        ctx.access.require(action)
        return ctx

    return dependency


# Read the list and its items: any role on the list (viewer or higher).
ListContextDep = Annotated[ListContext, Depends(require_list_action(ListAction.READ))]
# Add items: editor, and not a person in an AI-only list.
ListItemEditorContextDep = Annotated[
    ListContext, Depends(require_list_action(ListAction.CHANGE_ITEMS))
]
# Change the list's name, description or mode: editor; admin for a person in an AI-only list.
ListEditorContextDep = Annotated[ListContext, Depends(require_list_action(ListAction.EDIT_LIST))]
# Grants and deleting the list: admin.
ListAdminContextDep = Annotated[ListContext, Depends(require_list_action(ListAction.ADMINISTER))]


@dataclass(frozen=True)
class ItemContext:
    """The item in the path, its list and project, and what the caller may do with the list."""

    item: Item
    todo_list: TodoList
    project: Project
    access: ListAccess
    user: User

    @property
    def role(self) -> ProjectRole:
        """The caller's effective role on the item's list."""
        return self.access.role

    @property
    def principal(self) -> Principal:
        """The caller as the actor for permission checks and audit events."""
        return Principal.for_user(self.user, self.project.organization_id)


async def item_context(item_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> ItemContext:
    """Resolve `{item_id}` for the signed-in user; 404 when its list does not exist for them."""
    item = await session.get(Item, item_id)
    todo_list = None if item is None else await session.get(TodoList, item.list_id)
    project = None if todo_list is None else await session.get(Project, todo_list.project_id)
    access = (
        None
        if todo_list is None or project is None
        else await list_access(
            session, Principal.for_user(user, project.organization_id), todo_list, project
        )
    )
    if item is None or todo_list is None or project is None or access is None:
        # Same answer for "does not exist" and "not yours": don't reveal which ids exist.
        raise NotFoundError("Item not found")
    return ItemContext(item=item, todo_list=todo_list, project=project, access=access, user=user)


def require_item_action(action: ListAction) -> Callable[..., Awaitable[ItemContext]]:
    """A dependency that resolves `{item_id}` and needs the caller to be allowed `action` on
    the item's list (`ListAccess` in the permission service: role and list mode).

    404 when the list does not exist for the caller, 403 when their role is too low
    (`forbidden`) or the list mode holds them back (`list_ai_only`). Use the aliases below in
    route signatures.
    """

    async def dependency(
        ctx: Annotated[ItemContext, Depends(item_context)],
    ) -> ItemContext:
        ctx.access.require(action)
        return ctx

    return dependency


# Read the item: any role on its list (viewer or higher).
ItemContextDep = Annotated[ItemContext, Depends(require_item_action(ListAction.READ))]
# Change, move or delete the item: editor, and not a person in an AI-only list.
ItemEditorContextDep = Annotated[ItemContext, Depends(require_item_action(ListAction.CHANGE_ITEMS))]
