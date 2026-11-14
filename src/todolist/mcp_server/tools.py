"""The MCP tools. They call the same service functions as the HTTP API, with the agent's
`Principal`; every permission check goes through `todolist.permissions`."""

import uuid
from datetime import datetime
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from todolist.errors import AppError, NotFoundError
from todolist.mcp_server.context import AgentContext, AgentContextFactory
from todolist.models import (
    Item,
    ItemStatus,
    ListMode,
    Organization,
    Project,
    ProjectRole,
    TodoList,
)
from todolist.permissions import (
    ListAccess,
    ListAction,
    accessible_lists,
    effective_project_role,
    list_access,
)
from todolist.services.items import (
    ItemCounts,
    ItemNotes,
    ItemTitle,
    count_items,
    create_item,
    delete_item,
    list_items,
    move_item,
    update_item,
)
from todolist.services.lists import list_accessible_lists
from todolist.services.projects import list_projects_with_lists


class OrganizationInfo(BaseModel):
    id: uuid.UUID
    name: str
    slug: str


class WhoAmI(BaseModel):
    agent_id: uuid.UUID
    name: str = Field(description="The agent you act as")
    organization: OrganizationInfo
    accessible_list_count: int = Field(description="How many lists you can read")


class ProjectInfo(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None


class ProjectList(BaseModel):
    projects: list[ProjectInfo] = Field(
        description="The projects with at least one list you can access, oldest first"
    )


class ProjectRef(BaseModel):
    id: uuid.UUID
    name: str


class ListInfo(BaseModel):
    id: uuid.UUID = Field(description="Pass this as list_id to get_list")
    name: str
    description: str | None
    mode: ListMode = Field(
        description="mixed: people and agents work on the list; ai_only: only agents change it"
    )
    project: ProjectRef
    role: ProjectRole = Field(
        description="Your role on the list: a viewer reads, an editor also changes items, "
        "an admin also manages the list"
    )
    open_item_count: int
    done_item_count: int


class ListList(BaseModel):
    lists: list[ListInfo] = Field(
        description="The lists you can access, by project and then in the project's order"
    )


class ItemInfo(BaseModel):
    id: uuid.UUID
    title: str
    notes: str | None
    status: ItemStatus
    position: int = Field(description="Place in the list, starting at 1")
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class ListWithItems(ListInfo):
    items: list[ItemInfo] = Field(
        description="In position order. Without include_done only the open items; "
        "done_item_count says how many were left out"
    )


class ChangedItem(ItemInfo):
    list_id: uuid.UUID = Field(description="The list the item is in")


class DeletedItem(BaseModel):
    id: uuid.UUID
    list_id: uuid.UUID = Field(description="The list the item was in")
    title: str = Field(description="The title of the item that no longer exists")


ItemId = Annotated[uuid.UUID, Field(description="The id of an item from get_list or add_item")]


def _list_info(
    todo_list: TodoList, project: Project, access: ListAccess, counts: ItemCounts
) -> ListInfo:
    return ListInfo(
        id=todo_list.id,
        name=todo_list.name,
        description=todo_list.description,
        mode=todo_list.mode,
        project=ProjectRef(id=project.id, name=project.name),
        role=access.role,
        open_item_count=counts.open,
        done_item_count=counts.done,
    )


def _item_info(item: Item) -> ItemInfo:
    return ItemInfo(
        id=item.id,
        title=item.title,
        notes=item.notes,
        status=item.status,
        position=item.position,
        created_at=item.created_at,
        updated_at=item.updated_at,
        completed_at=item.completed_at,
    )


def _changed_item(item: Item) -> ChangedItem:
    return ChangedItem(**_item_info(item).model_dump(), list_id=item.list_id)


async def _project_with_lists(ctx: AgentContext, project_id: uuid.UUID) -> Project:
    """The project, when it exists for the agent: it has a role on it or sees a list in it
    (the rule of the HTTP list index). Otherwise the error the agent reads."""
    project = await ctx.session.get(Project, project_id)
    if project is not None and (
        await effective_project_role(ctx.session, ctx.principal, project) is not None
        or await list_accessible_lists(ctx.session, ctx.principal, project)
    ):
        return project
    raise NotFoundError(
        f"Project {project_id} not found: it does not exist or you have no access to it. "
        "Call list_projects for the projects you can use."
    )


async def _accessible_list(
    ctx: AgentContext, list_id: uuid.UUID, action: ListAction
) -> tuple[TodoList, Project, ListAccess]:
    """The list with its project and the agent's access, checked for `action`. An unknown
    list and one the agent cannot see give the same error."""
    todo_list = await ctx.session.get(TodoList, list_id)
    if todo_list is not None:
        project = await ctx.session.get_one(Project, todo_list.project_id)
        access = await list_access(ctx.session, ctx.principal, todo_list, project)
        if access is not None:
            access.require(action)
            return todo_list, project, access
    raise NotFoundError(
        f"List {list_id} not found: it does not exist or you have no access to it. "
        "Call list_lists for the lists you can use."
    )


async def _accessible_item(ctx: AgentContext, item_id: uuid.UUID, action: ListAction) -> Item:
    """The item, when the agent may do `action` on its list. An unknown item and one in a
    list the agent cannot see give the same error."""
    item = await ctx.session.get(Item, item_id)
    todo_list = None if item is None else await ctx.session.get(TodoList, item.list_id)
    if item is not None and todo_list is not None:
        project = await ctx.session.get_one(Project, todo_list.project_id)
        access = await list_access(ctx.session, ctx.principal, todo_list, project)
        if access is not None:
            access.require(action)
            return item
    raise NotFoundError(
        f"Item {item_id} not found: it does not exist or you have no access to its list. "
        "Call get_list for the items of a list."
    )


def register_tools(server: MCPServer, agent_context: AgentContextFactory) -> None:
    @server.tool()
    async def whoami() -> WhoAmI:  # pyright: ignore[reportUnusedFunction]
        """Who you are: the agent you act as, its organization and how many lists you can
        access."""
        async with agent_context() as ctx:
            principal = ctx.principal
            organization = (
                await ctx.session.execute(
                    select(Organization).where(Organization.id == principal.organization_id)
                )
            ).scalar_one()
            count = await ctx.session.scalar(
                select(func.count()).select_from(accessible_lists(principal).subquery())
            )
            return WhoAmI(
                agent_id=principal.id,
                name=principal.name,
                organization=OrganizationInfo(
                    id=organization.id, name=organization.name, slug=organization.slug
                ),
                accessible_list_count=count or 0,
            )

    @server.tool()
    async def list_projects() -> ProjectList:  # pyright: ignore[reportUnusedFunction]
        """The projects that contain at least one list you can access. A project groups
        lists; pass a project's id to list_lists to see only its lists."""
        async with agent_context() as ctx:
            projects = await list_projects_with_lists(ctx.session, ctx.principal)
            return ProjectList(
                projects=[
                    ProjectInfo(id=project.id, name=project.name, description=project.description)
                    for project in projects
                ]
            )

    @server.tool()
    async def list_lists(  # pyright: ignore[reportUnusedFunction]
        project_id: Annotated[
            uuid.UUID | None,
            Field(description="Only the lists of this project (an id from list_projects)"),
        ] = None,
    ) -> ListList:
        """The todo lists you can access, in all projects or in one, each with its project,
        your role on it and how many of its items are open and done. Use get_list to read
        a list's items."""
        async with agent_context() as ctx:
            project = None
            if project_id is not None:
                project = await _project_with_lists(ctx, project_id)
            found = await list_accessible_lists(ctx.session, ctx.principal, project)
            counts = await count_items(ctx.session, [todo_list.id for todo_list, _ in found])
            lists: list[ListInfo] = []
            for todo_list, its_project in found:
                access = await list_access(ctx.session, ctx.principal, todo_list, its_project)
                if access is not None:
                    lists.append(_list_info(todo_list, its_project, access, counts[todo_list.id]))
            return ListList(lists=lists)

    @server.tool()
    async def get_list(  # pyright: ignore[reportUnusedFunction]
        list_id: Annotated[uuid.UUID, Field(description="The id of a list from list_lists")],
        include_done: Annotated[
            bool, Field(description="Also return the items that are done, not only the open ones")
        ] = False,
    ) -> ListWithItems:
        """One todo list with its items in position order (the order to work through them).
        By default only the open items; set include_done to also get the completed ones."""
        async with agent_context() as ctx:
            todo_list, project, access = await _accessible_list(ctx, list_id, ListAction.READ)
            counts = await count_items(ctx.session, [todo_list.id])
            items = await list_items(ctx.session, todo_list, include_done=include_done)
            info = _list_info(todo_list, project, access, counts[todo_list.id])
            return ListWithItems(**info.model_dump(), items=[_item_info(item) for item in items])

    @server.tool()
    async def add_item(  # pyright: ignore[reportUnusedFunction]
        list_id: Annotated[uuid.UUID, Field(description="The id of a list from list_lists")],
        title: Annotated[ItemTitle, Field(description="What has to be done, 1 to 500 characters")],
        notes: Annotated[
            ItemNotes | None, Field(description="Optional details, up to 10000 characters")
        ] = None,
    ) -> ChangedItem:
        """Add an open item at the end of a list. Needs the editor role on the list (see
        role in list_lists). Use move_item to put it somewhere else in the list."""
        async with agent_context() as ctx:
            todo_list, _, _ = await _accessible_list(ctx, list_id, ListAction.CHANGE_ITEMS)
            item = await create_item(ctx.session, ctx.principal, todo_list, title, notes)
            return _changed_item(item)

    @server.tool(name="update_item")
    async def update_item_tool(  # pyright: ignore[reportUnusedFunction]
        item_id: ItemId,
        title: Annotated[
            ItemTitle | None, Field(description="The new title; leave out to keep the title")
        ] = None,
        notes: Annotated[
            ItemNotes | None,
            Field(
                description="The new notes; leave out to keep the notes, "
                "pass an empty string to remove them"
            ),
        ] = None,
    ) -> ChangedItem:
        """Change the title or the notes of an item (or both). Needs the editor role on the
        item's list. Use complete_item and reopen_item for the status, move_item for the place."""
        async with agent_context() as ctx:
            item = await _accessible_item(ctx, item_id, ListAction.CHANGE_ITEMS)
            if title is None and notes is None:
                raise AppError(
                    422, "nothing_to_update", "Nothing to change: pass title, notes or both."
                )
            item = await update_item(
                ctx.session,
                ctx.principal,
                item,
                title=title,
                notes=notes,
                set_notes=notes is not None,
            )
            return _changed_item(item)

    @server.tool()
    async def complete_item(item_id: ItemId) -> ChangedItem:  # pyright: ignore[reportUnusedFunction]
        """Mark an item as done. Needs the editor role on the item's list. An item that is
        already done stays as it is."""
        async with agent_context() as ctx:
            item = await _accessible_item(ctx, item_id, ListAction.CHANGE_ITEMS)
            item = await update_item(ctx.session, ctx.principal, item, status=ItemStatus.DONE)
            return _changed_item(item)

    @server.tool()
    async def reopen_item(item_id: ItemId) -> ChangedItem:  # pyright: ignore[reportUnusedFunction]
        """Make a done item open again. Needs the editor role on the item's list. An item
        that is already open stays as it is."""
        async with agent_context() as ctx:
            item = await _accessible_item(ctx, item_id, ListAction.CHANGE_ITEMS)
            item = await update_item(ctx.session, ctx.principal, item, status=ItemStatus.OPEN)
            return _changed_item(item)

    @server.tool(name="move_item")
    async def move_item_tool(  # pyright: ignore[reportUnusedFunction]
        item_id: ItemId,
        before_item_id: Annotated[
            uuid.UUID | None,
            Field(
                description="Put the item just before this item of the same list; "
                "leave out to move it to the end of the list"
            ),
        ] = None,
    ) -> ChangedItem:
        """Move an item to another place in its list: before another item, or to the end.
        Needs the editor role on the list. The result has the item's new position; the items
        in between shift one place."""
        async with agent_context() as ctx:
            item = await _accessible_item(ctx, item_id, ListAction.CHANGE_ITEMS)
            item = await move_item(ctx.session, ctx.principal, item, before_item_id)
            return _changed_item(item)

    @server.tool(name="delete_item")
    async def delete_item_tool(item_id: ItemId) -> DeletedItem:  # pyright: ignore[reportUnusedFunction]
        """Remove an item from its list for good; this cannot be undone. Needs the editor
        role on the item's list. Use complete_item for work that is finished."""
        async with agent_context() as ctx:
            item = await _accessible_item(ctx, item_id, ListAction.CHANGE_ITEMS)
            deleted = DeletedItem(id=item.id, list_id=item.list_id, title=item.title)
            await delete_item(ctx.session, ctx.principal, item)
            return deleted
