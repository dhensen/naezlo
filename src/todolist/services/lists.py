"""Lists: create, list, change and delete the todo lists of a project.

The callers check the acting principal's role (`require_project_role` / `require_list_role`,
see `todolist.permissions`).
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from todolist.models import Agent, ListMode, PrincipalKind, Project, TodoList
from todolist.permissions import visible_lists
from todolist.principals import Principal


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
    return todo_list


async def update_list(
    session: AsyncSession,
    todo_list: TodoList,
    *,
    name: str | None = None,
    description: str | None = None,
    set_description: bool = False,
    mode: ListMode | None = None,
) -> TodoList:
    """Change the name and the mode (when given) and the description (when `set_description`;
    None clears it)."""
    if name is not None:
        todo_list.name = name.strip()
    if set_description:
        todo_list.description = _clean_description(description)
    if mode is not None:
        todo_list.mode = mode
    await session.flush()
    # updated_at is set by the database.
    await session.refresh(todo_list)
    return todo_list


async def delete_list(session: AsyncSession, todo_list: TodoList) -> None:
    await session.delete(todo_list)
    await session.flush()
