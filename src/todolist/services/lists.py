"""Lists: create, list, change and delete the todo lists of a project.

The callers check what the acting principal may do (`effective_project_role` / `list_access`
in `todolist.permissions`).
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from todolist.models import Agent, AuditAction, ListMode, PrincipalKind, Project, TodoList
from todolist.permissions import accessible_lists, visible_lists
from todolist.principals import Principal
from todolist.services.audit import changes, record_event


def _clean_description(description: str | None) -> str | None:
    """Trimmed; an empty description is stored as no description."""
    if description is None:
        return None
    return description.strip() or None


async def default_list_mode(session: AsyncSession, organization_id: uuid.UUID) -> ListMode:
    """The mode of a new list when none is chosen: mixed once the organization has an agent,
    human-only before that."""
    agent = await session.scalar(
        select(Agent.id).where(Agent.organization_id == organization_id).limit(1)
    )
    return ListMode.HUMAN_ONLY if agent is None else ListMode.MIXED


async def list_lists(
    session: AsyncSession, principal: Principal, project: Project
) -> list[TodoList]:
    """The lists of the project that the principal can see, in their order (position, then
    age). Empty when they can see none; that includes a principal without any access."""
    todo_lists = await session.scalars(
        visible_lists(principal, project).order_by(TodoList.position, TodoList.id)
    )
    return list(todo_lists)


async def list_accessible_lists(
    session: AsyncSession, principal: Principal, project: Project | None = None
) -> list[tuple[TodoList, Project]]:
    """The lists the principal can see with their project: in all projects of the
    principal's organization, or in `project` only. Ordered by project (oldest first), then
    as within a project (position, then age)."""
    query = (
        accessible_lists(principal)
        .join(Project, Project.id == TodoList.project_id)
        .add_columns(Project)
        .order_by(Project.id, TodoList.position, TodoList.id)
    )
    if project is not None:
        query = query.where(TodoList.project_id == project.id)
    return [(todo_list, its_project) for todo_list, its_project in await session.execute(query)]


async def create_list(
    session: AsyncSession,
    principal: Principal,
    project: Project,
    name: str,
    description: str | None,
    mode: ListMode | None = None,
) -> TodoList:
    """Add a list at the end of the project. Without a `mode` it gets `default_list_mode`."""
    # Two lists created at the same moment must not get the same position.
    await session.execute(select(Project.id).where(Project.id == project.id).with_for_update())
    last = await session.scalar(
        select(func.max(TodoList.position)).where(TodoList.project_id == project.id)
    )
    todo_list = TodoList(
        project_id=project.id,
        name=name.strip(),
        description=_clean_description(description),
        mode=mode or await default_list_mode(session, project.organization_id),
        position=1 if last is None else last + 1,
        # created_by refers to a user; a list made by an agent has none.
        created_by=principal.id if principal.kind is PrincipalKind.USER else None,
    )
    session.add(todo_list)
    await session.flush()
    await record_event(
        session,
        principal,
        AuditAction.LIST_CREATED,
        target_kind="list",
        target_id=todo_list.id,
        project_id=project.id,
        list_id=todo_list.id,
        details={"name": todo_list.name, "mode": todo_list.mode.value},
    )
    return todo_list


def _audited_fields(todo_list: TodoList) -> dict[str, object]:
    return {
        "name": todo_list.name,
        "description": todo_list.description,
        "mode": todo_list.mode,
    }


async def update_list(
    session: AsyncSession,
    principal: Principal,
    todo_list: TodoList,
    *,
    name: str | None = None,
    description: str | None = None,
    set_description: bool = False,
    mode: ListMode | None = None,
) -> TodoList:
    """Change the name and the mode (when given) and the description (when `set_description`;
    None clears it)."""
    old = _audited_fields(todo_list)
    if name is not None:
        todo_list.name = name.strip()
    if set_description:
        todo_list.description = _clean_description(description)
    if mode is not None:
        todo_list.mode = mode
    await session.flush()
    # updated_at is set by the database.
    await session.refresh(todo_list)
    # A mode change is in here too, with the old and the new mode.
    changed = changes(old, _audited_fields(todo_list))
    if changed:
        await record_event(
            session,
            principal,
            AuditAction.LIST_UPDATED,
            target_kind="list",
            target_id=todo_list.id,
            project_id=todo_list.project_id,
            list_id=todo_list.id,
            details={"name": todo_list.name, "changes": changed},
        )
    return todo_list


async def delete_list(session: AsyncSession, principal: Principal, todo_list: TodoList) -> None:
    """Delete the list with its items. One event is recorded, for the list."""
    list_id, project_id, name = todo_list.id, todo_list.project_id, todo_list.name
    await session.delete(todo_list)
    await session.flush()
    await record_event(
        session,
        principal,
        AuditAction.LIST_DELETED,
        target_kind="list",
        target_id=list_id,
        project_id=project_id,
        list_id=list_id,
        details={"name": name},
    )
