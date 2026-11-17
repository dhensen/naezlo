"""List ACL: a grant on a list overrides the project role, and the list grants API."""

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from naezlo.models import (
    Agent,
    ListGrant,
    ListMode,
    ListRole,
    MembershipRole,
    PrincipalKind,
    Project,
    ProjectGrant,
    ProjectRole,
    TodoList,
)
from naezlo.permissions import effective_list_role, visible_lists
from naezlo.principals import Principal
from tests.helpers import (
    add_in_savepoint,
    add_member,
    grant_list_role,
    grant_project_role,
    sign_in,
)

LIST_NOT_FOUND = {"detail": "List not found", "code": "not_found"}
PROJECT_NOT_FOUND = {"detail": "Project not found", "code": "not_found"}
GRANT_NOT_FOUND = {"detail": "Grant not found", "code": "not_found"}


@dataclass
class World:
    """Ada owns the organization and a project "Website" with the lists Launch and Backlog."""

    org_id: str
    project_id: str
    launch: str
    backlog: str

    @property
    def lists_url(self) -> str:
        return f"/api/projects/{self.project_id}/lists"

    @property
    def grants_url(self) -> str:
        return f"/api/lists/{self.launch}/grants"


async def make_world(client: AsyncClient) -> World:
    ada = await sign_in(client)
    org_id = ada["organizations"][0]["id"]
    project = await client.post(f"/api/orgs/{org_id}/projects", json={"name": "Website"})
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    ids: list[str] = []
    for name in ("Launch", "Backlog"):
        created = await client.post(f"/api/projects/{project_id}/lists", json={"name": name})
        assert created.status_code == 201, created.text
        ids.append(created.json()["id"])
    return World(org_id=org_id, project_id=project_id, launch=ids[0], backlog=ids[1])


async def join(
    db_session: AsyncSession,
    other: AsyncClient,
    world: World,
    project_role: ProjectRole | None = None,
    list_role: ListRole | None = None,
    membership: MembershipRole = MembershipRole.MEMBER,
    email: str = "grace@example.com",
    name: str = "Grace",
) -> str:
    """Sign a second user in, make them a member, and give them `project_role` on the project
    and `list_role` on Launch (None: no grant). Returns their id."""
    me = await sign_in(other, email, name)
    user_id = me["user"]["id"]
    await add_member(db_session, world.org_id, user_id, membership)
    if project_role is not None:
        await grant_project_role(db_session, world.project_id, user_id, project_role)
    if list_role is not None:
        await grant_list_role(db_session, world.launch, user_id, list_role)
    return user_id


async def create_agent(client: AsyncClient, org_id: str, name: str = "Claude") -> str:
    response = await client.post(f"/api/orgs/{org_id}/agents", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def user_grant(user_id: str, role: str) -> dict[str, str]:
    return {"principal_kind": "user", "principal_id": user_id, "role": role}


def agent_grant(agent_id: str, role: str) -> dict[str, str]:
    return {"principal_kind": "agent", "principal_id": agent_id, "role": role}


async def statuses(other: AsyncClient, list_id: str) -> tuple[int, int, int, int]:
    """What GET, PATCH, GET grants and DELETE answer on a list, in that order (the DELETE
    goes last and may remove the list)."""
    url = f"/api/lists/{list_id}"
    return (
        (await other.get(url)).status_code,
        (await other.patch(url, json={"description": "Changed"})).status_code,
        (await other.get(f"{url}/grants")).status_code,
        (await other.delete(url)).status_code,
    )


async def index_names(other: AsyncClient, world: World) -> list[str]:
    response = await other.get(world.lists_url)
    assert response.status_code == 200, response.text
    return [todo_list["name"] for todo_list in response.json()]


# --- The effect of a list grant ---


async def test_override_up_project_viewer_is_editor_on_one_list(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    world = await make_world(client)
    await join(db_session, other_client, world, ProjectRole.VIEWER, ListRole.EDITOR)

    # Editor on Launch: may change it, may not delete it or manage its grants.
    assert await statuses(other_client, world.launch) == (200, 200, 403, 403)
    # Still a viewer on the other list and on the project.
    assert await statuses(other_client, world.backlog) == (200, 403, 403, 403)
    created = await other_client.post(world.lists_url, json={"name": "Mine"})
    assert created.status_code == 403
    assert await index_names(other_client, world) == ["Launch", "Backlog"]


async def test_override_down_project_editor_is_viewer_on_one_list(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    world = await make_world(client)
    await join(db_session, other_client, world, ProjectRole.EDITOR, ListRole.VIEWER)

    assert await statuses(other_client, world.launch) == (200, 403, 403, 403)
    assert await statuses(other_client, world.backlog) == (200, 200, 403, 403)
    assert await index_names(other_client, world) == ["Launch", "Backlog"]


async def test_a_list_admin_grant_gives_admin_on_that_list_only(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    world = await make_world(client)
    await join(db_session, other_client, world, ProjectRole.VIEWER, ListRole.ADMIN)

    assert await statuses(other_client, world.backlog) == (200, 403, 403, 403)
    assert await statuses(other_client, world.launch) == (200, 200, 200, 204)
    assert await db_session.get(TodoList, uuid.UUID(world.launch)) is None


@pytest.mark.parametrize("project_role", [ProjectRole.VIEWER, ProjectRole.ADMIN])
async def test_none_hides_the_list(
    client: AsyncClient,
    other_client: AsyncClient,
    db_session: AsyncSession,
    project_role: ProjectRole,
) -> None:
    world = await make_world(client)
    await join(db_session, other_client, world, project_role, ListRole.NONE)
    url = f"/api/lists/{world.launch}"

    for response in (
        await other_client.get(url),
        await other_client.patch(url, json={"name": "Hacked"}),
        await other_client.get(f"{url}/grants"),
        await other_client.delete(url),
    ):
        assert response.status_code == 404
        assert response.json() == LIST_NOT_FOUND
    assert await index_names(other_client, world) == ["Backlog"]
    assert (await other_client.get(f"/api/lists/{world.backlog}")).status_code == 200
    assert await db_session.get(TodoList, uuid.UUID(world.launch)) is not None


async def test_list_only_access_opens_the_list_but_not_the_project(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    world = await make_world(client)
    await join(db_session, other_client, world, None, ListRole.EDITOR)

    opened = await other_client.get(f"/api/lists/{world.launch}")
    assert opened.status_code == 200
    assert opened.json()["name"] == "Launch"
    assert opened.json()["project_id"] == world.project_id
    assert opened.json()["project_name"] == "Website"
    patched = await other_client.patch(f"/api/lists/{world.launch}", json={"name": "Launch!"})
    assert patched.status_code == 200

    # The project's other list does not exist for her.
    other_list = await other_client.get(f"/api/lists/{world.backlog}")
    assert other_list.status_code == 404
    assert other_list.json() == LIST_NOT_FOUND
    # The index gives only her list.
    assert await index_names(other_client, world) == ["Launch!"]
    # The project itself stays out of reach.
    project = await other_client.get(f"/api/projects/{world.project_id}")
    assert project.status_code == 404
    assert project.json() == PROJECT_NOT_FOUND
    projects = await other_client.get(f"/api/orgs/{world.org_id}/projects")
    assert projects.json() == []
    created = await other_client.post(world.lists_url, json={"name": "Mine"})
    assert created.status_code == 404
    assert created.json() == PROJECT_NOT_FOUND
    grants = await other_client.get(f"/api/projects/{world.project_id}/grants")
    assert grants.status_code == 404


async def test_the_index_is_not_found_without_any_visible_list(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    world = await make_world(client)
    await join(db_session, other_client, world, None, ListRole.NONE)

    response = await other_client.get(world.lists_url)

    assert response.status_code == 404
    assert response.json() == PROJECT_NOT_FOUND


async def test_the_index_is_empty_when_every_list_is_hidden_from_a_project_viewer(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    world = await make_world(client)
    grace_id = await join(db_session, other_client, world, ProjectRole.VIEWER, ListRole.NONE)
    await grant_list_role(db_session, world.backlog, grace_id, ListRole.NONE)

    assert await index_names(other_client, world) == []


@pytest.mark.parametrize("membership", [MembershipRole.OWNER, MembershipRole.ADMIN])
@pytest.mark.parametrize("list_role", [None, ListRole.NONE, ListRole.VIEWER])
async def test_organization_owners_and_admins_are_admin_whatever_the_grants_say(
    client: AsyncClient,
    other_client: AsyncClient,
    db_session: AsyncSession,
    membership: MembershipRole,
    list_role: ListRole | None,
) -> None:
    world = await make_world(client)
    await join(db_session, other_client, world, None, list_role, membership=membership)

    assert await index_names(other_client, world) == ["Launch", "Backlog"]
    assert await statuses(other_client, world.launch) == (200, 200, 200, 204)


async def test_a_list_grant_gives_nothing_without_a_membership(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    world = await make_world(client)
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    await grant_list_role(db_session, world.launch, grace["user"]["id"], ListRole.ADMIN)

    assert (await other_client.get(f"/api/lists/{world.launch}")).json() == LIST_NOT_FOUND
    assert (await other_client.get(world.lists_url)).json() == PROJECT_NOT_FOUND


async def test_removing_a_member_deletes_their_list_grants(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    world = await make_world(client)
    grace_id = await join(db_session, other_client, world, None, ListRole.EDITOR)

    removed = await client.delete(f"/api/orgs/{world.org_id}/members/{grace_id}")
    assert removed.status_code == 204, removed.text

    assert await db_session.scalar(select(func.count()).select_from(ListGrant)) == 0
    # Joining again does not bring the old access back.
    await add_member(db_session, world.org_id, grace_id, MembershipRole.MEMBER)
    assert (await other_client.get(f"/api/lists/{world.launch}")).status_code == 404


# --- The permission service ---


async def test_effective_list_role_and_visible_lists_for_an_agent(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    world = await make_world(client)
    agent = await db_session.get(Agent, uuid.UUID(await create_agent(client, world.org_id)))
    project = await db_session.get(Project, uuid.UUID(world.project_id))
    launch = await db_session.get(TodoList, uuid.UUID(world.launch))
    backlog = await db_session.get(TodoList, uuid.UUID(world.backlog))
    assert agent is not None
    assert project is not None
    assert launch is not None
    assert backlog is not None
    # The lists were made before the agent, so they are human-only: invisible to any agent.
    launch.mode = backlog.mode = ListMode.MIXED
    await db_session.flush()
    principal = Principal.for_agent(agent)

    async def roles() -> tuple[ProjectRole | None, ProjectRole | None, list[str]]:
        visible = await db_session.scalars(
            visible_lists(principal, project).order_by(TodoList.position)
        )
        return (
            await effective_list_role(db_session, principal, launch, project),
            await effective_list_role(db_session, principal, backlog, project),
            [todo_list.name for todo_list in visible],
        )

    assert await roles() == (None, None, [])

    # A list grant only.
    put = await client.put(world.grants_url, json=agent_grant(str(agent.id), "editor"))
    assert put.status_code == 200, put.text
    assert await roles() == (ProjectRole.EDITOR, None, ["Launch"])

    # A project grant on top: the list grant still decides on its list.
    db_session.add(
        ProjectGrant(
            project_id=project.id,
            principal_kind=PrincipalKind.AGENT,
            agent_id=agent.id,
            role=ProjectRole.VIEWER,
        )
    )
    await db_session.flush()
    assert await roles() == (ProjectRole.EDITOR, ProjectRole.VIEWER, ["Launch", "Backlog"])

    put = await client.put(world.grants_url, json=agent_grant(str(agent.id), "none"))
    assert put.status_code == 200, put.text
    assert await roles() == (None, ProjectRole.VIEWER, ["Backlog"])


async def test_a_principal_of_another_organization_has_no_role(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    world = await make_world(client)
    grace_id = await join(db_session, other_client, world, None, ListRole.ADMIN)
    project = await db_session.get(Project, uuid.UUID(world.project_id))
    launch = await db_session.get(TodoList, uuid.UUID(world.launch))
    assert project is not None
    assert launch is not None
    elsewhere = Principal(
        kind=PrincipalKind.USER, id=uuid.UUID(grace_id), organization_id=uuid.uuid7(), name="Grace"
    )

    assert await effective_list_role(db_session, elsewhere, launch, project) is None
    assert list(await db_session.scalars(visible_lists(elsewhere, project))) == []


async def test_effective_list_role_rejects_another_project(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    world = await make_world(client)
    other = await client.post(f"/api/orgs/{world.org_id}/projects", json={"name": "Other"})
    project = await db_session.get(Project, uuid.UUID(other.json()["id"]))
    launch = await db_session.get(TodoList, uuid.UUID(world.launch))
    agent = await db_session.get(Agent, uuid.UUID(await create_agent(client, world.org_id)))
    assert project is not None
    assert launch is not None
    assert agent is not None

    with pytest.raises(ValueError, match="not the list's project"):
        await effective_list_role(db_session, Principal.for_agent(agent), launch, project)


# --- The table ---


async def test_one_grant_per_list_and_principal(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    world = await make_world(client)
    grace_id = await join(db_session, other_client, world, None, ListRole.VIEWER)

    with pytest.raises(IntegrityError):
        await add_in_savepoint(
            db_session,
            ListGrant(
                list_id=uuid.UUID(world.launch),
                principal_kind=PrincipalKind.USER,
                user_id=uuid.UUID(grace_id),
                role=ListRole.EDITOR,
            ),
        )


async def test_the_principal_column_must_match_the_kind(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    world = await make_world(client)
    grace = await sign_in(other_client, "grace@example.com", "Grace")

    with pytest.raises(IntegrityError):
        await add_in_savepoint(
            db_session,
            ListGrant(
                list_id=uuid.UUID(world.launch),
                principal_kind=PrincipalKind.AGENT,
                user_id=uuid.UUID(grace["user"]["id"]),
                role=ListRole.VIEWER,
            ),
        )


async def test_deleting_the_list_deletes_its_grants(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    world = await make_world(client)
    await join(db_session, other_client, world, None, ListRole.VIEWER)

    assert (await client.delete(f"/api/lists/{world.launch}")).status_code == 204

    assert await db_session.scalar(select(func.count()).select_from(ListGrant)) == 0


# --- The grants API ---


async def test_put_creates_a_grant_and_get_lists_them(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    world = await make_world(client)
    grace_id = await join(db_session, other_client, world)
    agent_id = await create_agent(client, world.org_id)
    assert (await client.get(world.grants_url)).json() == []

    first = await client.put(world.grants_url, json=user_grant(grace_id, "editor"))
    second = await client.put(world.grants_url, json=agent_grant(agent_id, "none"))

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    body: dict[str, Any] = first.json()
    assert set(body) == {
        "id",
        "principal_kind",
        "principal_id",
        "name",
        "email",
        "role",
        "created_at",
        "updated_at",
    }
    assert body["principal_kind"] == "user"
    assert body["principal_id"] == grace_id
    assert body["name"] == "Grace"
    assert body["email"] == "grace@example.com"
    assert body["role"] == "editor"
    assert second.json()["name"] == "Claude"
    assert second.json()["email"] is None
    assert second.json()["role"] == "none"
    listed = await client.get(world.grants_url)
    assert listed.status_code == 200
    assert listed.json() == [first.json(), second.json()]
    # Grants of one list only.
    assert (await client.get(f"/api/lists/{world.backlog}/grants")).json() == []
    # And it works: Grace edits the list.
    assert await statuses(other_client, world.launch) == (200, 200, 403, 403)


async def test_put_again_changes_the_role_of_the_same_grant(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    world = await make_world(client)
    grace_id = await join(db_session, other_client, world, ProjectRole.EDITOR)
    first = await client.put(world.grants_url, json=user_grant(grace_id, "viewer"))

    second = await client.put(world.grants_url, json=user_grant(grace_id, "none"))

    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["role"] == "none"
    assert len((await client.get(world.grants_url)).json()) == 1
    assert (await other_client.get(f"/api/lists/{world.launch}")).status_code == 404


async def test_delete_revokes_and_the_project_role_applies_again(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    world = await make_world(client)
    grace_id = await join(db_session, other_client, world, ProjectRole.EDITOR)
    grant = await client.put(world.grants_url, json=user_grant(grace_id, "none"))
    assert (await other_client.get(f"/api/lists/{world.launch}")).status_code == 404

    response = await client.delete(f"{world.grants_url}/{grant.json()['id']}")

    assert response.status_code == 204
    assert (await client.get(world.grants_url)).json() == []
    patched = await other_client.patch(f"/api/lists/{world.launch}", json={"name": "Again"})
    assert patched.status_code == 200


async def test_delete_of_an_unknown_grant_or_one_of_another_list_is_not_found(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    world = await make_world(client)
    grace_id = await join(db_session, other_client, world)
    grant = await client.put(world.grants_url, json=user_grant(grace_id, "viewer"))
    project_grants = await client.get(f"/api/projects/{world.project_id}/grants")

    backlog_grants_url = f"/api/lists/{world.backlog}/grants"
    for url in (
        f"{world.grants_url}/{uuid.uuid7()}",
        # Exists, but on Launch.
        f"{backlog_grants_url}/{grant.json()['id']}",
        # A project grant is not a list grant.
        f"{world.grants_url}/{project_grants.json()[0]['id']}",
    ):
        response = await client.delete(url)
        assert response.status_code == 404
        assert response.json() == GRANT_NOT_FOUND
    assert len((await client.get(world.grants_url)).json()) == 1


@pytest.mark.parametrize("kind", ["user", "agent"])
async def test_put_rejects_a_principal_outside_the_organization(
    client: AsyncClient, other_client: AsyncClient, kind: str
) -> None:
    world = await make_world(client)
    # Grace has her own organization, with her own agent.
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    agent_id = await create_agent(other_client, grace["organizations"][0]["id"])
    principal_id = grace["user"]["id"] if kind == "user" else agent_id

    for candidate in (principal_id, str(uuid.uuid7())):
        response = await client.put(
            world.grants_url,
            json={"principal_kind": kind, "principal_id": candidate, "role": "viewer"},
        )
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_principal"
    assert (await client.get(world.grants_url)).json() == []


@pytest.mark.parametrize(
    "payload",
    [
        {"principal_kind": "user", "principal_id": str(uuid.uuid7())},
        {"principal_kind": "user", "principal_id": str(uuid.uuid7()), "role": "owner"},
        {"principal_kind": "robot", "principal_id": str(uuid.uuid7()), "role": "viewer"},
        {"principal_kind": "user", "principal_id": "nope", "role": "viewer"},
    ],
)
async def test_put_rejects_invalid_input(client: AsyncClient, payload: dict[str, Any]) -> None:
    world = await make_world(client)

    response = await client.put(world.grants_url, json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("project_role", "list_role", "expected"),
    [
        (None, None, 404),
        (ProjectRole.ADMIN, ListRole.NONE, 404),
        (ProjectRole.VIEWER, None, 403),
        (ProjectRole.EDITOR, None, 403),
        (ProjectRole.ADMIN, ListRole.EDITOR, 403),
        (ProjectRole.ADMIN, None, 200),
        (None, ListRole.ADMIN, 200),
    ],
)
async def test_the_grants_routes_need_list_admin(
    client: AsyncClient,
    other_client: AsyncClient,
    third_client: AsyncClient,
    db_session: AsyncSession,
    project_role: ProjectRole | None,
    list_role: ListRole | None,
    expected: int,
) -> None:
    world = await make_world(client)
    await join(db_session, other_client, world, project_role, list_role)
    linus_id = await join(db_session, third_client, world, email="linus@example.com", name="Linus")
    existing = await client.put(world.grants_url, json=user_grant(linus_id, "viewer"))

    listed = await other_client.get(world.grants_url)
    put = await other_client.put(world.grants_url, json=user_grant(linus_id, "admin"))
    revoked = await other_client.delete(f"{world.grants_url}/{existing.json()['id']}")

    assert listed.status_code == expected
    assert put.status_code == expected
    assert revoked.status_code == (204 if expected == 200 else expected)
    if expected == 404:
        assert listed.json() == LIST_NOT_FOUND
    if expected == 403:
        assert put.json()["code"] == "forbidden"
        # Nothing changed.
        linus = [g for g in (await client.get(world.grants_url)).json() if g["name"] == "Linus"]
        assert [g["role"] for g in linus] == ["viewer"]


async def test_inherited_gives_the_project_grants_to_a_list_admin(
    client: AsyncClient,
    other_client: AsyncClient,
    third_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    world = await make_world(client)
    # Grace administers Launch without a role on the project; Linus is a viewer of the project.
    grace_id = await join(db_session, other_client, world, None, ListRole.ADMIN)
    linus_id = await join(
        db_session, third_client, world, ProjectRole.VIEWER, email="linus@example.com", name="Linus"
    )
    agent_id = await create_agent(client, world.org_id)
    project_grants_url = f"/api/projects/{world.project_id}/grants"
    assert (
        await client.put(project_grants_url, json=agent_grant(agent_id, "editor"))
    ).status_code == 200
    ada_id = (await client.get("/api/me")).json()["user"]["id"]

    response = await other_client.get(f"{world.grants_url}/inherited")

    assert response.status_code == 200, response.text
    body = response.json()
    assert [(g["principal_kind"], g["principal_id"], g["name"], g["role"]) for g in body] == [
        ("user", ada_id, "Ada", "admin"),
        ("user", linus_id, "Linus", "viewer"),
        ("agent", agent_id, "Claude", "editor"),
    ]
    assert set(body[0]) == {
        "id",
        "principal_kind",
        "principal_id",
        "name",
        "email",
        "role",
        "created_at",
        "updated_at",
    }
    # The same rows as the project's own grants API, which stays closed to Grace.
    assert body == (await client.get(project_grants_url)).json()
    assert (await other_client.get(project_grants_url)).status_code == 404
    assert grace_id not in [g["principal_id"] for g in body]


@pytest.mark.parametrize(
    ("project_role", "list_role", "expected"),
    [
        (None, None, 404),
        (ProjectRole.ADMIN, ListRole.NONE, 404),
        (ProjectRole.EDITOR, None, 403),
        (ProjectRole.ADMIN, ListRole.EDITOR, 403),
        (ProjectRole.ADMIN, None, 200),
    ],
)
async def test_inherited_needs_list_admin(
    client: AsyncClient,
    other_client: AsyncClient,
    db_session: AsyncSession,
    project_role: ProjectRole | None,
    list_role: ListRole | None,
    expected: int,
) -> None:
    world = await make_world(client)
    await join(db_session, other_client, world, project_role, list_role)

    response = await other_client.get(f"{world.grants_url}/inherited")

    assert response.status_code == expected
    assert (await client.get(f"/api/lists/{uuid.uuid7()}/grants/inherited")).json() == (
        LIST_NOT_FOUND
    )


async def test_a_list_admin_can_hide_the_list_from_themselves(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    world = await make_world(client)
    grace_id = await join(db_session, other_client, world, None, ListRole.ADMIN)

    response = await other_client.put(world.grants_url, json=user_grant(grace_id, "none"))

    assert response.status_code == 200
    assert (await other_client.get(world.grants_url)).status_code == 404
    # The organization's owner still administers it.
    assert (await client.get(world.grants_url)).status_code == 200


@pytest.mark.parametrize(
    ("method", "suffix"),
    [("GET", ""), ("GET", "/inherited"), ("PUT", ""), ("DELETE", f"/{uuid.uuid7()}")],
)
async def test_routes_need_a_signed_in_user(client: AsyncClient, method: str, suffix: str) -> None:
    response = await client.request(method, f"/api/lists/{uuid.uuid7()}/grants{suffix}")

    assert response.status_code == 401
