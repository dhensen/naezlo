"""List modes: human-only lists are closed to agents, AI-only lists are read-only for people."""

import uuid
from dataclasses import dataclass

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers import add_member, grant_list_role, grant_project_role, sign_in
from todolist.errors import AppError
from todolist.models import (
    Agent,
    ItemStatus,
    ListGrant,
    ListMode,
    ListRole,
    MembershipRole,
    PrincipalKind,
    Project,
    ProjectGrant,
    ProjectRole,
    TodoList,
    User,
)
from todolist.permissions import (
    ListAction,
    effective_list_role,
    list_access,
    list_accesses,
    visible_lists,
)
from todolist.principals import Principal
from todolist.services.items import create_item, delete_item, list_items, move_item, update_item
from todolist.services.lists import list_lists

AI_ONLY_ITEMS = {
    "detail": "This list is AI-only: people can read its items only",
    "code": "list_ai_only",
}
AI_ONLY_LIST = {
    "detail": "This list is AI-only: only its admins can change it",
    "code": "list_ai_only",
}
NEEDS_EDITOR = {"detail": "This needs the editor role on the list", "code": "forbidden"}
LIST_NOT_FOUND = {"detail": "List not found", "code": "not_found"}

ALL_ACTIONS = set(ListAction)


@dataclass
class World:
    """Ada owns the organization and a project with one list; Claude is the organization's
    agent. Neither Claude nor anyone but Ada has a role until a test gives them one."""

    org_id: str
    project: Project
    todo_list: TodoList
    agent: Agent

    @property
    def list_url(self) -> str:
        return f"/api/lists/{self.todo_list.id}"

    @property
    def items_url(self) -> str:
        return f"{self.list_url}/items"

    @property
    def claude(self) -> Principal:
        return Principal.for_agent(self.agent)


async def make_world(client: AsyncClient, db_session: AsyncSession, mode: ListMode) -> World:
    ada = await sign_in(client)
    org_id = ada["organizations"][0]["id"]
    created = await client.post(f"/api/orgs/{org_id}/projects", json={"name": "Website"})
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]
    created = await client.post(
        f"/api/projects/{project_id}/lists", json={"name": "Launch", "mode": mode.value}
    )
    assert created.status_code == 201, created.text
    agent = Agent(organization_id=uuid.UUID(org_id), name="Claude")
    db_session.add(agent)
    await db_session.flush()
    project = await db_session.get(Project, uuid.UUID(project_id))
    todo_list = await db_session.get(TodoList, uuid.UUID(created.json()["id"]))
    assert project is not None
    assert todo_list is not None
    return World(org_id=org_id, project=project, todo_list=todo_list, agent=agent)


async def grant_agent(db_session: AsyncSession, world: World, role: ListRole) -> None:
    """Give Claude a role on the list (a list grant only)."""
    db_session.add(
        ListGrant(
            list_id=world.todo_list.id,
            principal_kind=PrincipalKind.AGENT,
            agent_id=world.agent.id,
            role=role,
        )
    )
    await db_session.flush()


async def join(
    db_session: AsyncSession, other: AsyncClient, world: World, role: ListRole
) -> Principal:
    """Sign Grace in on `other`, make her a member and give her `role` on the list."""
    grace = await sign_in(other, "grace@example.com", "Grace")
    grace_id = grace["user"]["id"]
    await add_member(db_session, world.org_id, grace_id, MembershipRole.MEMBER)
    await grant_list_role(db_session, str(world.todo_list.id), grace_id, role)
    user = await db_session.get(User, uuid.UUID(grace_id))
    assert user is not None
    return Principal.for_user(user, world.project.organization_id)


async def allowed(
    db_session: AsyncSession, principal: Principal, world: World
) -> set[ListAction] | None:
    """What the principal may do with the list; None when it does not exist for them."""
    access = await list_access(db_session, principal, world.todo_list, world.project)
    if access is None:
        return None
    return {action for action in ListAction if access.allows(action)}


async def set_mode(client: AsyncClient, world: World, mode: ListMode) -> None:
    response = await client.patch(world.list_url, json={"mode": mode.value})
    assert response.status_code == 200, response.text


# --- The permission service: every mode for both kinds of principal ---

VIEW = {ListAction.READ}
EDIT = {ListAction.READ, ListAction.CHANGE_ITEMS, ListAction.EDIT_LIST}


@pytest.mark.parametrize(
    ("mode", "role", "expected"),
    [
        (ListMode.MIXED, ListRole.VIEWER, VIEW),
        (ListMode.MIXED, ListRole.EDITOR, EDIT),
        (ListMode.MIXED, ListRole.ADMIN, ALL_ACTIONS),
        (ListMode.HUMAN_ONLY, ListRole.VIEWER, VIEW),
        (ListMode.HUMAN_ONLY, ListRole.EDITOR, EDIT),
        (ListMode.HUMAN_ONLY, ListRole.ADMIN, ALL_ACTIONS),
        # AI-only: people read; only an admin still manages the list itself.
        (ListMode.AI_ONLY, ListRole.VIEWER, VIEW),
        (ListMode.AI_ONLY, ListRole.EDITOR, VIEW),
        (
            ListMode.AI_ONLY,
            ListRole.ADMIN,
            {ListAction.READ, ListAction.EDIT_LIST, ListAction.ADMINISTER},
        ),
        (ListMode.MIXED, ListRole.NONE, None),
        (ListMode.AI_ONLY, ListRole.NONE, None),
    ],
)
async def test_what_a_user_may_do_in_each_mode(
    client: AsyncClient,
    other_client: AsyncClient,
    db_session: AsyncSession,
    mode: ListMode,
    role: ListRole,
    expected: set[ListAction] | None,
) -> None:
    world = await make_world(client, db_session, mode)
    grace = await join(db_session, other_client, world, role)

    assert await allowed(db_session, grace, world) == expected


@pytest.mark.parametrize(
    ("mode", "role", "expected"),
    [
        (ListMode.MIXED, ListRole.VIEWER, VIEW),
        (ListMode.MIXED, ListRole.EDITOR, EDIT),
        (ListMode.MIXED, ListRole.ADMIN, ALL_ACTIONS),
        (ListMode.AI_ONLY, ListRole.VIEWER, VIEW),
        (ListMode.AI_ONLY, ListRole.EDITOR, EDIT),
        (ListMode.AI_ONLY, ListRole.ADMIN, ALL_ACTIONS),
        # Human-only: the list does not exist for an agent, whatever its grant.
        (ListMode.HUMAN_ONLY, ListRole.VIEWER, None),
        (ListMode.HUMAN_ONLY, ListRole.EDITOR, None),
        (ListMode.HUMAN_ONLY, ListRole.ADMIN, None),
        (ListMode.MIXED, ListRole.NONE, None),
    ],
)
async def test_what_an_agent_may_do_in_each_mode(
    client: AsyncClient,
    db_session: AsyncSession,
    mode: ListMode,
    role: ListRole,
    expected: set[ListAction] | None,
) -> None:
    world = await make_world(client, db_session, mode)
    await grant_agent(db_session, world, role)

    assert await allowed(db_session, world.claude, world) == expected
    visible = await list_lists(db_session, world.claude, world.project)
    assert visible == ([] if expected is None else [world.todo_list])


@pytest.mark.parametrize("mode", list(ListMode))
async def test_without_a_role_the_list_does_not_exist_in_any_mode(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession, mode: ListMode
) -> None:
    world = await make_world(client, db_session, mode)
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    await add_member(db_session, world.org_id, grace["user"]["id"], MembershipRole.MEMBER)
    user = await db_session.get(User, uuid.UUID(grace["user"]["id"]))
    assert user is not None

    assert await allowed(db_session, world.claude, world) is None
    assert (
        await allowed(db_session, Principal.for_user(user, world.project.organization_id), world)
        is None
    )
    assert (await other_client.get(world.list_url)).json() == LIST_NOT_FOUND


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (ListMode.MIXED, ALL_ACTIONS),
        (ListMode.HUMAN_ONLY, ALL_ACTIONS),
        (ListMode.AI_ONLY, {ListAction.READ, ListAction.EDIT_LIST, ListAction.ADMINISTER}),
    ],
)
async def test_the_organization_owner_is_bound_by_ai_only_too(
    client: AsyncClient, db_session: AsyncSession, mode: ListMode, expected: set[ListAction]
) -> None:
    world = await make_world(client, db_session, mode)
    ada = await db_session.get(User, world.todo_list.created_by)
    assert ada is not None

    principal = Principal.for_user(ada, world.project.organization_id)
    assert await allowed(db_session, principal, world) == expected


async def test_human_only_hides_the_list_from_an_agent_with_every_grant(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    world = await make_world(client, db_session, ListMode.HUMAN_ONLY)
    await grant_agent(db_session, world, ListRole.ADMIN)
    db_session.add(
        ProjectGrant(
            project_id=world.project.id,
            principal_kind=PrincipalKind.AGENT,
            agent_id=world.agent.id,
            role=ProjectRole.ADMIN,
        )
    )
    await db_session.flush()

    # The grants are there, the mode decides.
    role = await effective_list_role(db_session, world.claude, world.todo_list, world.project)
    assert role is ProjectRole.ADMIN
    assert await list_access(db_session, world.claude, world.todo_list, world.project) is None
    assert list(await db_session.scalars(visible_lists(world.claude, world.project))) == []

    # Opening the list to agents is all it takes.
    await set_mode(client, world, ListMode.MIXED)
    assert await allowed(db_session, world.claude, world) == ALL_ACTIONS
    assert await list_lists(db_session, world.claude, world.project) == [world.todo_list]

    await set_mode(client, world, ListMode.HUMAN_ONLY)
    assert await allowed(db_session, world.claude, world) is None


@pytest.mark.parametrize(
    ("role", "action", "status", "code"),
    [
        (ListRole.VIEWER, ListAction.CHANGE_ITEMS, 403, "forbidden"),
        (ListRole.VIEWER, ListAction.EDIT_LIST, 403, "forbidden"),
        (ListRole.EDITOR, ListAction.CHANGE_ITEMS, 403, "list_ai_only"),
        (ListRole.EDITOR, ListAction.EDIT_LIST, 403, "list_ai_only"),
        (ListRole.EDITOR, ListAction.ADMINISTER, 403, "forbidden"),
        (ListRole.ADMIN, ListAction.CHANGE_ITEMS, 403, "list_ai_only"),
    ],
)
async def test_the_error_for_a_user_in_an_ai_only_list(
    client: AsyncClient,
    other_client: AsyncClient,
    db_session: AsyncSession,
    role: ListRole,
    action: ListAction,
    status: int,
    code: str,
) -> None:
    world = await make_world(client, db_session, ListMode.AI_ONLY)
    grace = await join(db_session, other_client, world, role)
    access = await list_access(db_session, grace, world.todo_list, world.project)
    assert access is not None

    with pytest.raises(AppError) as raised:
        access.require(action)

    assert (raised.value.status_code, raised.value.code) == (status, code)


async def test_an_agent_works_on_an_ai_only_list_and_people_watch(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    world = await make_world(client, db_session, ListMode.AI_ONLY)
    await grant_agent(db_session, world, ListRole.EDITOR)
    await join(db_session, other_client, world, ListRole.VIEWER)
    access = await list_access(db_session, world.claude, world.todo_list, world.project)
    assert access is not None
    access.require(ListAction.CHANGE_ITEMS)

    first = await create_item(db_session, world.claude, world.todo_list, "Draft copy")
    second = await create_item(db_session, world.claude, world.todo_list, "Check links")
    await update_item(db_session, world.claude, first, status=ItemStatus.DONE)
    await move_item(db_session, world.claude, second, first.id)
    third = await create_item(db_session, world.claude, world.todo_list, "Oops")
    await delete_item(db_session, world.claude, third)

    titles = [item.title for item in await list_items(db_session, world.todo_list)]
    assert titles == ["Check links", "Draft copy"]
    # People with a role read along.
    for reader in (client, other_client):
        response = await reader.get(world.items_url)
        assert response.status_code == 200, response.text
        assert [(item["title"], item["status"]) for item in response.json()] == [
            ("Check links", "open"),
            ("Draft copy", "done"),
        ]
        assert (await reader.get(f"/api/items/{first.id}")).status_code == 200


# --- The API (people) ---


@pytest.mark.parametrize("who", ["owner", "admin", "editor"])
async def test_ai_only_items_are_read_only_for_people(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession, who: str
) -> None:
    world = await make_world(client, db_session, ListMode.MIXED)
    first = (await client.post(world.items_url, json={"title": "Buy domain"})).json()
    second = (await client.post(world.items_url, json={"title": "Write copy"})).json()
    if who == "owner":
        caller = client
    else:
        caller = other_client
        role = ListRole.ADMIN if who == "admin" else ListRole.EDITOR
        await join(db_session, other_client, world, role)
    await set_mode(client, world, ListMode.AI_ONLY)
    item_url = f"/api/items/{first['id']}"
    before = (await caller.get(world.items_url)).json()

    responses = [
        await caller.post(world.items_url, json={"title": "New"}),
        await caller.patch(item_url, json={"title": "Renamed"}),
        await caller.patch(item_url, json={"notes": "Soon"}),
        await caller.patch(item_url, json={"status": "done"}),
        await caller.post(f"{item_url}/move", json={"before_item_id": None}),
        await caller.post(f"/api/items/{second['id']}/move", json={"before_item_id": first["id"]}),
        await caller.delete(item_url),
    ]

    for response in responses:
        assert response.status_code == 403, response.text
        assert response.json() == AI_ONLY_ITEMS
    # Reading still works and nothing changed.
    assert (await caller.get(world.list_url)).json()["mode"] == "ai_only"
    assert (await caller.get(item_url)).json() == first
    assert (await caller.get(world.items_url)).json() == before == [first, second]

    # Back to mixed, the same person can work again.
    await set_mode(client, world, ListMode.MIXED)
    done = await caller.patch(item_url, json={"status": "done"})
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "done"


async def test_ai_only_viewer_gets_the_role_error(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    world = await make_world(client, db_session, ListMode.AI_ONLY)
    await join(db_session, other_client, world, ListRole.VIEWER)

    response = await other_client.post(world.items_url, json={"title": "New"})

    assert response.status_code == 403
    assert response.json() == NEEDS_EDITOR
    assert (await other_client.get(world.items_url)).json() == []


@pytest.mark.parametrize("who", ["owner", "admin"])
async def test_ai_only_list_admins_still_manage_the_list(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession, who: str
) -> None:
    world = await make_world(client, db_session, ListMode.AI_ONLY)
    caller = client
    if who == "admin":
        caller = other_client
        await join(db_session, other_client, world, ListRole.ADMIN)
    grants_url = f"{world.list_url}/grants"

    renamed = await caller.patch(world.list_url, json={"name": "Relaunch", "description": "Go."})
    assert renamed.status_code == 200, renamed.text
    assert (renamed.json()["name"], renamed.json()["mode"]) == ("Relaunch", "ai_only")

    granted = await caller.put(
        grants_url,
        json={"principal_kind": "agent", "principal_id": str(world.agent.id), "role": "editor"},
    )
    assert granted.status_code == 200, granted.text
    listed = await caller.get(grants_url)
    assert listed.status_code == 200, listed.text
    assert str(world.agent.id) in [grant["principal_id"] for grant in listed.json()]
    revoked = await caller.delete(f"{grants_url}/{granted.json()['id']}")
    assert revoked.status_code == 204, revoked.text

    switched = await caller.patch(world.list_url, json={"mode": "mixed"})
    assert switched.status_code == 200, switched.text
    assert switched.json()["mode"] == "mixed"
    assert (await caller.post(world.items_url, json={"title": "New"})).status_code == 201


async def test_ai_only_list_admin_can_delete_the_list(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    world = await make_world(client, db_session, ListMode.AI_ONLY)

    assert (await client.delete(world.list_url)).status_code == 204
    assert (await client.get(world.list_url)).status_code == 404


async def test_ai_only_editor_cannot_change_the_list(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    world = await make_world(client, db_session, ListMode.AI_ONLY)
    await join(db_session, other_client, world, ListRole.EDITOR)

    for body in ({"name": "Mine"}, {"mode": "mixed"}, {"description": None}):
        response = await other_client.patch(world.list_url, json=body)
        assert response.status_code == 403, response.text
        assert response.json() == AI_ONLY_LIST
    unchanged = (await other_client.get(world.list_url)).json()
    assert (unchanged["name"], unchanged["mode"]) == ("Launch", "ai_only")


async def test_project_role_is_bound_by_ai_only_like_a_list_grant(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    world = await make_world(client, db_session, ListMode.AI_ONLY)
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    await add_member(db_session, world.org_id, grace["user"]["id"], MembershipRole.MEMBER)
    await grant_project_role(
        db_session, str(world.project.id), grace["user"]["id"], ProjectRole.EDITOR
    )

    response = await other_client.post(world.items_url, json={"title": "New"})

    assert response.status_code == 403
    assert response.json() == AI_ONLY_ITEMS
    listed = await other_client.get(f"/api/projects/{world.project.id}/lists")
    assert [todo_list["mode"] for todo_list in listed.json()] == ["ai_only"]


@pytest.mark.parametrize("mode", [ListMode.HUMAN_ONLY, ListMode.MIXED])
async def test_people_work_by_their_role_in_human_only_and_mixed_lists(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession, mode: ListMode
) -> None:
    world = await make_world(client, db_session, mode)
    await join(db_session, other_client, world, ListRole.EDITOR)

    created = await other_client.post(world.items_url, json={"title": "Buy domain"})
    assert created.status_code == 201, created.text
    item_url = f"/api/items/{created.json()['id']}"
    assert (await other_client.patch(item_url, json={"status": "done"})).status_code == 200
    assert (await other_client.post(f"{item_url}/move", json={"before_item_id": None})).json()[
        "position"
    ] == 1
    assert (await other_client.patch(world.list_url, json={"name": "Mine"})).status_code == 200
    assert (await other_client.delete(item_url)).status_code == 204


# --- What the API tells the UI: the caller's role and allowed actions on each list ---

READ_ONLY = ["read"]
EDITOR_ACTIONS = ["read", "change_items", "edit_list"]
EVERYTHING = ["read", "change_items", "edit_list", "administer"]


@pytest.mark.parametrize(
    ("mode", "role", "actions"),
    [
        (ListMode.HUMAN_ONLY, ListRole.VIEWER, READ_ONLY),
        (ListMode.MIXED, ListRole.EDITOR, EDITOR_ACTIONS),
        (ListMode.MIXED, ListRole.ADMIN, EVERYTHING),
        (ListMode.AI_ONLY, ListRole.EDITOR, READ_ONLY),
        (ListMode.AI_ONLY, ListRole.ADMIN, ["read", "edit_list", "administer"]),
    ],
)
async def test_the_list_shape_has_the_callers_role_and_actions(
    client: AsyncClient,
    other_client: AsyncClient,
    db_session: AsyncSession,
    mode: ListMode,
    role: ListRole,
    actions: list[str],
) -> None:
    world = await make_world(client, db_session, mode)
    await join(db_session, other_client, world, role)

    one = (await other_client.get(world.list_url)).json()
    index = (await other_client.get(f"/api/projects/{world.project.id}/lists")).json()

    assert (one["role"], one["actions"]) == (role.value, actions)
    assert [(row["id"], row["role"], row["actions"]) for row in index] == [
        (one["id"], role.value, actions)
    ]


async def test_a_mode_change_answers_with_the_new_actions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    world = await make_world(client, db_session, ListMode.MIXED)

    response = await client.patch(world.list_url, json={"mode": "ai_only"})

    assert response.status_code == 200, response.text
    assert response.json()["actions"] == ["read", "edit_list", "administer"]


async def test_list_accesses_agrees_with_list_access(
    client: AsyncClient,
    other_client: AsyncClient,
    third_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Four lists in one project: human-only, AI-only, and two mixed ones of which one has a
    list grant. Every kind of principal gets the same answer from both functions."""
    world = await make_world(client, db_session, ListMode.MIXED)
    lists_url = f"/api/projects/{world.project.id}/lists"
    todo_lists = [world.todo_list]
    for name, mode in [("Private", "human_only"), ("Queue", "ai_only"), ("Open", "mixed")]:
        created = await client.post(lists_url, json={"name": name, "mode": mode})
        assert created.status_code == 201, created.text
        todo_list = await db_session.get(TodoList, uuid.UUID(created.json()["id"]))
        assert todo_list is not None
        todo_lists.append(todo_list)
    ada = await db_session.get(User, uuid.UUID((await client.get("/api/me")).json()["user"]["id"]))
    assert ada is not None
    # Grace: editor on the project, but no access to the first list.
    grace = await join(db_session, other_client, world, ListRole.NONE)
    await grant_project_role(db_session, str(world.project.id), str(grace.id), ProjectRole.EDITOR)
    # Linus: a member with only a viewer grant on the first list.
    linus_me = await sign_in(third_client, "linus@example.com", "Linus")
    await add_member(db_session, world.org_id, linus_me["user"]["id"], MembershipRole.MEMBER)
    await grant_list_role(
        db_session, str(world.todo_list.id), linus_me["user"]["id"], ListRole.VIEWER
    )
    linus = await db_session.get(User, uuid.UUID(linus_me["user"]["id"]))
    assert linus is not None
    # Claude: admin on the first list, viewer on the project.
    await grant_agent(db_session, world, ListRole.ADMIN)
    db_session.add(
        ProjectGrant(
            project_id=world.project.id,
            principal_kind=PrincipalKind.AGENT,
            agent_id=world.agent.id,
            role=ProjectRole.VIEWER,
        )
    )
    await db_session.flush()
    organization_id = world.project.organization_id
    principals = [
        Principal.for_user(ada, organization_id),
        grace,
        Principal.for_user(linus, organization_id),
        world.claude,
        # Someone of another organization sees nothing.
        Principal.for_user(ada, uuid.uuid4()),
    ]

    seen: list[int] = []
    for principal in principals:
        expected = {
            todo_list.id: access
            for todo_list in todo_lists
            if (access := await list_access(db_session, principal, todo_list, world.project))
        }
        assert await list_accesses(db_session, principal, world.project, todo_lists) == expected
        seen.append(len(expected))

    assert seen == [4, 3, 1, 3, 0]
