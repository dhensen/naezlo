"""Lists: CRUD in a project, the default mode and the role each action needs."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers import add_member, grant_project_role, sign_in
from todolist.models import (
    Agent,
    ListMode,
    MembershipRole,
    PrincipalKind,
    Project,
    ProjectRole,
    TodoList,
)
from todolist.permissions import effective_list_role
from todolist.principals import Principal
from todolist.services.lists import create_list

LIST_NOT_FOUND = {"detail": "List not found", "code": "not_found"}
PROJECT_NOT_FOUND = {"detail": "Project not found", "code": "not_found"}


async def ada_project(client: AsyncClient) -> tuple[str, str, str]:
    """Sign Ada in and give her a project; returns the organization id, the project id and
    the project's lists URL."""
    ada = await sign_in(client)
    org_id = ada["organizations"][0]["id"]
    response = await client.post(f"/api/orgs/{org_id}/projects", json={"name": "Website"})
    assert response.status_code == 201, response.text
    project_id = response.json()["id"]
    return org_id, project_id, f"/api/projects/{project_id}/lists"


async def create(
    client: AsyncClient, url: str, name: str = "Launch", **extra: Any
) -> dict[str, Any]:
    response = await client.post(url, json={"name": name, **extra})
    assert response.status_code == 201, response.text
    return response.json()


async def join(
    db_session: AsyncSession,
    other_client: AsyncClient,
    org_id: str,
    project_id: str,
    role: ProjectRole | None,
) -> None:
    """Sign Grace in on `other_client`, make her a member of the organization and give her
    `role` on the project (None: no grant)."""
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    await add_member(db_session, org_id, grace["user"]["id"], MembershipRole.MEMBER)
    if role is not None:
        await grant_project_role(db_session, project_id, grace["user"]["id"], role)


async def add_agent(client: AsyncClient, org_id: str) -> str:
    response = await client.post(f"/api/orgs/{org_id}/agents", json={"name": "Claude"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def list_count(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(TodoList)) or 0


async def test_create_returns_the_list(client: AsyncClient, db_session: AsyncSession) -> None:
    _, project_id, url = await ada_project(client)
    ada_id = (await client.get("/api/me")).json()["user"]["id"]

    response = await client.post(url, json={"name": "  Launch ", "description": " Go live. "})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Launch"
    assert body["description"] == "Go live."
    assert body["project_id"] == project_id
    assert body["project_name"] == "Website"
    assert body["created_by"] == ada_id
    assert body["position"] == 1
    assert body["created_at"] is not None
    assert body["updated_at"] is not None
    assert set(body) == {
        "id",
        "project_id",
        "project_name",
        "name",
        "description",
        "mode",
        "position",
        "open_item_count",
        "created_by",
        "created_at",
        "updated_at",
    }
    assert body["open_item_count"] == 0
    assert await db_session.get(TodoList, uuid.UUID(body["id"])) is not None


@pytest.mark.parametrize("extra", [{}, {"description": None}, {"description": "   "}])
async def test_create_without_a_description(client: AsyncClient, extra: dict[str, Any]) -> None:
    _, _, url = await ada_project(client)

    body = await create(client, url, **extra)

    assert body["description"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 201},
        {"name": None},
        {"name": "Launch", "description": "x" * 2001},
        {"name": "Launch", "mode": "robots"},
    ],
)
async def test_create_rejects_invalid_input(
    client: AsyncClient, db_session: AsyncSession, payload: dict[str, Any]
) -> None:
    _, _, url = await ada_project(client)

    response = await client.post(url, json=payload)

    assert response.status_code == 422
    assert await list_count(db_session) == 0


@pytest.mark.parametrize("extra", [{}, {"mode": None}])
async def test_default_mode_is_human_only_without_agents(
    client: AsyncClient, extra: dict[str, Any]
) -> None:
    _, _, url = await ada_project(client)

    body = await create(client, url, **extra)

    assert body["mode"] == "human_only"


async def test_default_mode_is_mixed_when_the_organization_has_an_agent(
    client: AsyncClient,
) -> None:
    org_id, _, url = await ada_project(client)
    await add_agent(client, org_id)

    body = await create(client, url)

    assert body["mode"] == "mixed"


async def test_default_mode_ignores_agents_of_other_organizations(
    client: AsyncClient, other_client: AsyncClient
) -> None:
    _, _, url = await ada_project(client)
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    await add_agent(other_client, grace["organizations"][0]["id"])

    body = await create(client, url)

    assert body["mode"] == "human_only"


async def test_default_mode_goes_back_to_human_only_when_the_last_agent_is_deleted(
    client: AsyncClient,
) -> None:
    org_id, _, url = await ada_project(client)
    agent_id = await add_agent(client, org_id)
    first = await create(client, url, "First")
    response = await client.delete(f"/api/orgs/{org_id}/agents/{agent_id}")
    assert response.status_code == 204

    second = await create(client, url, "Second")

    assert second["mode"] == "human_only"
    # The existing list keeps the mode it was given.
    assert (await client.get(f"/api/lists/{first['id']}")).json()["mode"] == "mixed"


@pytest.mark.parametrize("with_agent", [False, True])
@pytest.mark.parametrize("mode", ["human_only", "ai_only", "mixed"])
async def test_explicit_mode_wins_over_the_default(
    client: AsyncClient, mode: str, with_agent: bool
) -> None:
    org_id, _, url = await ada_project(client)
    if with_agent:
        await add_agent(client, org_id)

    body = await create(client, url, mode=mode)

    assert body["mode"] == mode


async def test_index_returns_the_lists_of_the_project_in_order(client: AsyncClient) -> None:
    org_id, _, url = await ada_project(client)
    other = await client.post(f"/api/orgs/{org_id}/projects", json={"name": "Other"})
    await create(client, f"/api/projects/{other.json()['id']}/lists", "Elsewhere")
    first = await create(client, url, "First")
    second = await create(client, url, "Second")
    third = await create(client, url, "Third")

    response = await client.get(url)

    assert response.status_code == 200
    assert response.json() == [first, second, third]
    assert [item["position"] for item in response.json()] == [1, 2, 3]


async def test_index_of_a_project_without_lists_is_empty(client: AsyncClient) -> None:
    _, _, url = await ada_project(client)

    response = await client.get(url)

    assert response.status_code == 200
    assert response.json() == []


async def test_a_new_list_goes_after_the_last_one_also_after_a_delete(
    client: AsyncClient,
) -> None:
    _, _, url = await ada_project(client)
    await create(client, url, "First")
    second = await create(client, url, "Second")
    third = await create(client, url, "Third")
    await client.delete(f"/api/lists/{second['id']}")

    fourth = await create(client, url, "Fourth")

    assert fourth["position"] > third["position"]
    assert [item["name"] for item in (await client.get(url)).json()] == [
        "First",
        "Third",
        "Fourth",
    ]


async def test_get_returns_the_list(client: AsyncClient) -> None:
    _, _, url = await ada_project(client)
    created = await create(client, url, description="Go live.", mode="ai_only")

    response = await client.get(f"/api/lists/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


async def test_patch_changes_only_the_fields_that_are_sent(client: AsyncClient) -> None:
    _, _, url = await ada_project(client)
    created = await create(client, url, description="Go live.", mode="human_only")
    list_url = f"/api/lists/{created['id']}"

    renamed = await client.patch(list_url, json={"name": " Relaunch "})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json() == {
        **created,
        "name": "Relaunch",
        "updated_at": renamed.json()["updated_at"],
    }

    switched = await client.patch(list_url, json={"mode": "ai_only"})
    assert switched.status_code == 200, switched.text
    assert switched.json()["mode"] == "ai_only"
    assert switched.json()["name"] == "Relaunch"
    assert switched.json()["description"] == "Go live."

    described = await client.patch(list_url, json={"description": " Again. "})
    assert described.json()["description"] == "Again."
    assert described.json()["mode"] == "ai_only"

    cleared = await client.patch(list_url, json={"description": None})
    assert cleared.status_code == 200
    assert cleared.json()["description"] is None
    assert (await client.get(list_url)).json() == cleared.json()


async def test_patch_all_fields_at_once(client: AsyncClient) -> None:
    _, _, url = await ada_project(client)
    created = await create(client, url)

    response = await client.patch(
        f"/api/lists/{created['id']}",
        json={"name": "Relaunch", "description": "Again.", "mode": "mixed"},
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["name"], body["description"], body["mode"]) == ("Relaunch", "Again.", "mixed")
    assert body["position"] == created["position"]


@pytest.mark.parametrize(
    "payload",
    [
        {"name": None},
        {"name": "  "},
        {"name": "x" * 201},
        {"mode": None},
        {"mode": "robots"},
        {"description": "x" * 2001},
    ],
)
async def test_patch_rejects_invalid_input(client: AsyncClient, payload: dict[str, Any]) -> None:
    _, _, url = await ada_project(client)
    created = await create(client, url, description="Go live.")

    response = await client.patch(f"/api/lists/{created['id']}", json=payload)

    assert response.status_code == 422
    assert (await client.get(f"/api/lists/{created['id']}")).json() == created


async def test_delete_removes_the_list(client: AsyncClient, db_session: AsyncSession) -> None:
    _, _, url = await ada_project(client)
    doomed = await create(client, url, "Doomed")
    kept = await create(client, url, "Kept")

    response = await client.delete(f"/api/lists/{doomed['id']}")

    assert response.status_code == 204
    assert (await client.get(f"/api/lists/{doomed['id']}")).json() == LIST_NOT_FOUND
    assert (await client.get(url)).json() == [kept]


async def test_deleting_the_project_deletes_its_lists(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, project_id, url = await ada_project(client)
    created = await create(client, url)

    response = await client.delete(f"/api/projects/{project_id}")

    assert response.status_code == 204
    assert await list_count(db_session) == 0
    assert (await client.get(f"/api/lists/{created['id']}")).status_code == 404


# Roles: (method, needs) for each route; Grace has `role` on the project.

RANK = {None: 0, ProjectRole.VIEWER: 1, ProjectRole.EDITOR: 2, ProjectRole.ADMIN: 3}
ROLES = [None, ProjectRole.VIEWER, ProjectRole.EDITOR, ProjectRole.ADMIN]


def expected_status(role: ProjectRole | None, minimum: ProjectRole, ok: int) -> int:
    if role is None:
        return 404
    return ok if RANK[role] >= RANK[minimum] else 403


@pytest.mark.parametrize("role", ROLES)
async def test_roles_on_the_project_routes(
    client: AsyncClient,
    other_client: AsyncClient,
    db_session: AsyncSession,
    role: ProjectRole | None,
) -> None:
    org_id, project_id, url = await ada_project(client)
    await create(client, url)
    await join(db_session, other_client, org_id, project_id, role)

    index = await other_client.get(url)
    created = await other_client.post(url, json={"name": "Mine"})

    assert index.status_code == expected_status(role, ProjectRole.VIEWER, 200)
    assert created.status_code == expected_status(role, ProjectRole.EDITOR, 201)
    if role is None:
        assert index.json() == PROJECT_NOT_FOUND
        assert created.json() == PROJECT_NOT_FOUND
    if created.status_code == 403:
        assert created.json()["code"] == "forbidden"
    assert await list_count(db_session) == (2 if created.status_code == 201 else 1)


@pytest.mark.parametrize("role", ROLES)
async def test_roles_on_the_list_routes(
    client: AsyncClient,
    other_client: AsyncClient,
    db_session: AsyncSession,
    role: ProjectRole | None,
) -> None:
    org_id, project_id, url = await ada_project(client)
    created = await create(client, url)
    list_url = f"/api/lists/{created['id']}"
    await join(db_session, other_client, org_id, project_id, role)

    got = await other_client.get(list_url)
    patched = await other_client.patch(list_url, json={"name": "Renamed", "mode": "mixed"})
    deleted = await other_client.delete(list_url)

    assert got.status_code == expected_status(role, ProjectRole.VIEWER, 200)
    assert patched.status_code == expected_status(role, ProjectRole.EDITOR, 200)
    assert deleted.status_code == expected_status(role, ProjectRole.ADMIN, 204)
    if role is None:
        assert got.json() == patched.json() == deleted.json() == LIST_NOT_FOUND
    for response in (patched, deleted):
        if response.status_code == 403:
            assert response.json()["code"] == "forbidden"
    after = await client.get(list_url)
    if deleted.status_code == 204:
        assert after.status_code == 404
    else:
        assert after.json()["name"] == ("Renamed" if patched.status_code == 200 else "Launch")


async def test_a_member_who_created_a_list_is_recorded_as_its_creator(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, project_id, url = await ada_project(client)
    await join(db_session, other_client, org_id, project_id, ProjectRole.EDITOR)
    grace_id = (await other_client.get("/api/me")).json()["user"]["id"]

    body = await create(other_client, url)

    assert body["created_by"] == grace_id


@pytest.mark.parametrize("role", [MembershipRole.OWNER, MembershipRole.ADMIN])
async def test_organization_owners_and_admins_manage_lists_without_a_grant(
    client: AsyncClient,
    other_client: AsyncClient,
    db_session: AsyncSession,
    role: MembershipRole,
) -> None:
    org_id, _, url = await ada_project(client)
    created = await create(client, url)
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    await add_member(db_session, org_id, grace["user"]["id"], role)

    assert (await other_client.get(url)).json() == [created]
    assert (await other_client.post(url, json={"name": "More"})).status_code == 201
    assert (await other_client.delete(f"/api/lists/{created['id']}")).status_code == 204


async def test_someone_outside_the_organization_sees_nothing(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    _, _, url = await ada_project(client)
    created = await create(client, url)
    list_url = f"/api/lists/{created['id']}"
    await sign_in(other_client, "grace@example.com", "Grace")

    for response in (
        await other_client.get(url),
        await other_client.post(url, json={"name": "Mine"}),
    ):
        assert response.status_code == 404
        assert response.json() == PROJECT_NOT_FOUND
    for response in (
        await other_client.get(list_url),
        await other_client.patch(list_url, json={"name": "Mine"}),
        await other_client.delete(list_url),
    ):
        assert response.status_code == 404
        assert response.json() == LIST_NOT_FOUND
    assert (await client.get(list_url)).json() == created


async def test_unknown_ids_are_not_found(client: AsyncClient) -> None:
    await sign_in(client)
    list_url = f"/api/lists/{uuid.uuid7()}"
    project_url = f"/api/projects/{uuid.uuid7()}/lists"

    assert (await client.get(list_url)).json() == LIST_NOT_FOUND
    assert (await client.patch(list_url, json={"name": "x"})).json() == LIST_NOT_FOUND
    assert (await client.delete(list_url)).json() == LIST_NOT_FOUND
    assert (await client.get(project_url)).json() == PROJECT_NOT_FOUND
    assert (await client.post(project_url, json={"name": "x"})).json() == PROJECT_NOT_FOUND


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/projects/{id}/lists"),
        ("POST", "/api/projects/{id}/lists"),
        ("GET", "/api/lists/{id}"),
        ("PATCH", "/api/lists/{id}"),
        ("DELETE", "/api/lists/{id}"),
    ],
)
async def test_routes_need_a_signed_in_user(client: AsyncClient, method: str, path: str) -> None:
    response = await client.request(method, path.format(id=uuid.uuid7()), json={"name": "x"})

    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"


# The service and the permission rule with an agent principal (what the MCP tools will use).


async def test_a_list_created_by_an_agent_has_no_creating_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, project_id, url = await ada_project(client)
    agent = await db_session.get(Agent, uuid.UUID(await add_agent(client, org_id)))
    project = await db_session.get(Project, uuid.UUID(project_id))
    assert agent is not None
    assert project is not None
    await create(client, url, "First")

    todo_list = await create_list(
        db_session, Principal.for_agent(agent), project, " By the agent ", None
    )

    assert todo_list.created_by is None
    assert todo_list.name == "By the agent"
    assert todo_list.mode is ListMode.MIXED
    assert todo_list.position == 2


async def test_effective_list_role_is_the_project_role_without_a_list_grant(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, project_id, url = await ada_project(client)
    created = await create(client, url)
    await join(db_session, other_client, org_id, project_id, ProjectRole.VIEWER)
    grace_id = (await other_client.get("/api/me")).json()["user"]["id"]
    agent = await db_session.get(Agent, uuid.UUID(await add_agent(client, org_id)))
    project = await db_session.get(Project, uuid.UUID(project_id))
    todo_list = await db_session.get(TodoList, uuid.UUID(created["id"]))
    assert agent is not None
    assert project is not None
    assert todo_list is not None
    grace = Principal(
        kind=PrincipalKind.USER,
        id=uuid.UUID(grace_id),
        organization_id=uuid.UUID(org_id),
        name="Grace",
    )

    assert await effective_list_role(db_session, grace, todo_list, project) is ProjectRole.VIEWER
    assert (
        await effective_list_role(db_session, Principal.for_agent(agent), todo_list, project)
        is None
    )


async def test_lists_come_with_their_open_item_count(client: AsyncClient) -> None:
    _, project_id, url = await ada_project(client)
    busy = await create(client, url, "Busy")
    empty = await create(client, url, "Empty")
    items_url = f"/api/lists/{busy['id']}/items"
    for title in ("One", "Two", "Three"):
        item = await client.post(items_url, json={"title": title})
        assert item.status_code == 201, item.text
    done = await client.patch(f"/api/items/{item.json()['id']}", json={"status": "done"})
    assert done.status_code == 200, done.text

    listed = (await client.get(url)).json()
    assert [(row["name"], row["open_item_count"]) for row in listed] == [("Busy", 2), ("Empty", 0)]
    assert (await client.get(f"/api/lists/{busy['id']}")).json()["open_item_count"] == 2
    renamed = await client.patch(f"/api/lists/{busy['id']}", json={"name": "Busier"})
    assert renamed.json()["open_item_count"] == 2
    assert (await client.get(f"/api/lists/{empty['id']}")).json()["open_item_count"] == 0
    assert project_id == busy["project_id"]
