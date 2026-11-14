"""Project grants API: sharing a project with users and agents."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers import add_member, grant_project_role, sign_in
from todolist.models import Membership, MembershipRole, ProjectRole

FORBIDDEN = "forbidden"
PROJECT_NOT_FOUND = {"detail": "Project not found", "code": "not_found"}


async def setup(client: AsyncClient) -> tuple[dict[str, Any], str, str]:
    """Ada signs in and creates a project. Returns her /api/me body, the organization id and
    the project's grants URL."""
    ada = await sign_in(client)
    org_id = ada["organizations"][0]["id"]
    created = await client.post(f"/api/orgs/{org_id}/projects", json={"name": "Website"})
    assert created.status_code == 201, created.text
    return ada, org_id, f"/api/projects/{created.json()['id']}/grants"


async def join(
    other: AsyncClient,
    db_session: AsyncSession,
    org_id: str,
    email: str = "grace@example.com",
    name: str = "Grace",
    role: MembershipRole = MembershipRole.MEMBER,
) -> str:
    """Sign a second user in and make them a member of the organization; returns their id."""
    me = await sign_in(other, email, name)
    await add_member(db_session, org_id, me["user"]["id"], role)
    return me["user"]["id"]


async def create_agent(client: AsyncClient, org_id: str, name: str = "Claude") -> str:
    response = await client.post(f"/api/orgs/{org_id}/agents", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def user_grant(user_id: str, role: str) -> dict[str, str]:
    return {"principal_kind": "user", "principal_id": user_id, "role": role}


def agent_grant(agent_id: str, role: str) -> dict[str, str]:
    return {"principal_kind": "agent", "principal_id": agent_id, "role": role}


async def make_plain_member(db_session: AsyncSession, org_id: str, user_id: str) -> None:
    """Change a membership behind the API's back (the API never leaves an organization
    without an owner)."""
    await db_session.execute(
        update(Membership)
        .where(
            Membership.organization_id == uuid.UUID(org_id),
            Membership.user_id == uuid.UUID(user_id),
        )
        .values(role=MembershipRole.MEMBER)
    )


async def test_a_new_project_lists_the_creators_admin_grant(client: AsyncClient) -> None:
    ada, _org_id, url = await setup(client)

    response = await client.get(url)

    assert response.status_code == 200
    [grant] = response.json()
    assert grant["principal_kind"] == "user"
    assert grant["principal_id"] == ada["user"]["id"]
    assert grant["name"] == "Ada"
    assert grant["email"] == "ada@example.com"
    assert grant["role"] == "admin"
    assert set(grant) == {
        "id",
        "principal_kind",
        "principal_id",
        "name",
        "email",
        "role",
        "created_at",
        "updated_at",
    }


async def test_grant_to_a_user_gives_them_the_project(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    _ada, org_id, url = await setup(client)
    grace_id = await join(other_client, db_session, org_id)
    project_url = url.removesuffix("/grants")
    before = await other_client.get(project_url)

    response = await client.put(url, json=user_grant(grace_id, "viewer"))

    assert before.status_code == 404
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["principal_kind"], body["principal_id"]) == ("user", grace_id)
    assert (body["name"], body["email"], body["role"]) == ("Grace", "grace@example.com", "viewer")
    assert (await other_client.get(project_url)).status_code == 200
    assert (await other_client.patch(project_url, json={"name": "X"})).status_code == 403
    listed = (await client.get(url)).json()
    assert [g["name"] for g in listed] == ["Ada", "Grace"]
    assert listed[1]["id"] == body["id"]


async def test_grant_to_an_agent(client: AsyncClient) -> None:
    _ada, org_id, url = await setup(client)
    agent_id = await create_agent(client, org_id)

    response = await client.put(url, json=agent_grant(agent_id, "editor"))

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["principal_kind"], body["principal_id"]) == ("agent", agent_id)
    assert (body["name"], body["email"], body["role"]) == ("Claude", None, "editor")
    listed = (await client.get(url)).json()
    assert [(g["principal_kind"], g["name"], g["role"]) for g in listed] == [
        ("user", "Ada", "admin"),
        ("agent", "Claude", "editor"),
    ]


async def test_put_again_updates_the_grant(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    _ada, org_id, url = await setup(client)
    grace_id = await join(other_client, db_session, org_id)
    agent_id = await create_agent(client, org_id)
    first = (await client.put(url, json=user_grant(grace_id, "viewer"))).json()
    first_agent = (await client.put(url, json=agent_grant(agent_id, "viewer"))).json()

    second = await client.put(url, json=user_grant(grace_id, "editor"))
    second_agent = await client.put(url, json=agent_grant(agent_id, "admin"))

    assert second.status_code == 200, second.text
    assert second.json()["id"] == first["id"]
    assert second.json()["role"] == "editor"
    assert second_agent.json()["id"] == first_agent["id"]
    assert second_agent.json()["role"] == "admin"
    assert [g["role"] for g in (await client.get(url)).json()] == ["admin", "editor", "admin"]
    project_url = url.removesuffix("/grants")
    assert (await other_client.patch(project_url, json={"name": "Ours"})).status_code == 200


async def test_revoke_takes_the_project_away(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    _ada, org_id, url = await setup(client)
    grace_id = await join(other_client, db_session, org_id)
    grant = (await client.put(url, json=user_grant(grace_id, "editor"))).json()

    response = await client.delete(f"{url}/{grant['id']}")
    again = await client.delete(f"{url}/{grant['id']}")

    assert response.status_code == 204
    assert again.status_code == 404
    assert again.json() == {"detail": "Grant not found", "code": "not_found"}
    assert [g["name"] for g in (await client.get(url)).json()] == ["Ada"]
    assert (await other_client.get(url.removesuffix("/grants"))).status_code == 404


async def test_revoke_an_agent_grant(client: AsyncClient) -> None:
    _ada, org_id, url = await setup(client)
    agent_id = await create_agent(client, org_id)
    grant = (await client.put(url, json=agent_grant(agent_id, "admin"))).json()

    response = await client.delete(f"{url}/{grant['id']}")

    assert response.status_code == 204
    assert len((await client.get(url)).json()) == 1


async def test_a_grant_of_another_project_is_not_found(client: AsyncClient) -> None:
    _ada, org_id, url = await setup(client)
    other = await client.post(f"/api/orgs/{org_id}/projects", json={"name": "Other"})
    [other_grant] = (await client.get(f"/api/projects/{other.json()['id']}/grants")).json()

    response = await client.delete(f"{url}/{other_grant['id']}")

    assert response.status_code == 404
    assert len((await client.get(f"/api/projects/{other.json()['id']}/grants")).json()) == 1


async def test_principal_from_another_organization_is_422(
    client: AsyncClient, other_client: AsyncClient
) -> None:
    _ada, _org_id, url = await setup(client)
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    foreign_agent = await create_agent(other_client, grace["organizations"][0]["id"])

    as_user = await client.put(url, json=user_grant(grace["user"]["id"], "viewer"))
    as_agent = await client.put(url, json=agent_grant(foreign_agent, "viewer"))
    unknown = await client.put(url, json=user_grant(str(uuid.uuid7()), "viewer"))
    # An agent's id is not a user's id, and the other way around.
    wrong_kind = await client.put(url, json=agent_grant(grace["user"]["id"], "viewer"))

    for response in (as_user, as_agent, unknown, wrong_kind):
        assert response.status_code == 422, response.text
        assert response.json()["code"] == "invalid_principal"
    assert len((await client.get(url)).json()) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"principal_kind": "robot", "principal_id": str(uuid.uuid7()), "role": "viewer"},
        {"principal_kind": "user", "principal_id": str(uuid.uuid7()), "role": "owner"},
        {"principal_kind": "user", "principal_id": str(uuid.uuid7()), "role": "none"},
        {"principal_kind": "user", "principal_id": "nope", "role": "viewer"},
        {"principal_kind": "user", "role": "viewer"},
    ],
)
async def test_invalid_body_is_422(client: AsyncClient, body: dict[str, str]) -> None:
    _ada, _org_id, url = await setup(client)

    response = await client.put(url, json=body)

    assert response.status_code == 422


@pytest.mark.parametrize("role", [ProjectRole.VIEWER, ProjectRole.EDITOR])
async def test_non_admin_callers_get_403(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession, role: ProjectRole
) -> None:
    ada, org_id, url = await setup(client)
    grace_id = await join(other_client, db_session, org_id)
    [ada_grant] = (await client.get(url)).json()
    await grant_project_role(db_session, url.split("/")[3], grace_id, role)

    listed = await other_client.get(url)
    put = await other_client.put(url, json=user_grant(grace_id, "admin"))
    deleted = await other_client.delete(f"{url}/{ada_grant['id']}")

    for response in (listed, put, deleted):
        assert response.status_code == 403, response.text
        assert response.json()["code"] == FORBIDDEN
    grants = (await client.get(url)).json()
    assert [(g["principal_id"], g["role"]) for g in grants] == [
        (ada["user"]["id"], "admin"),
        (grace_id, role.value),
    ]


async def test_without_a_role_the_grants_are_not_found(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    _ada, org_id, url = await setup(client)
    grace_id = await join(other_client, db_session, org_id)

    listed = await other_client.get(url)
    put = await other_client.put(url, json=user_grant(grace_id, "admin"))
    deleted = await other_client.delete(f"{url}/{uuid.uuid7()}")

    for response in (listed, put, deleted):
        assert response.status_code == 404
        assert response.json() == PROJECT_NOT_FOUND


async def test_signed_out_is_401(client: AsyncClient) -> None:
    response = await client.get(f"/api/projects/{uuid.uuid7()}/grants")

    assert response.status_code == 401


async def test_a_member_with_an_admin_grant_manages_grants(
    client: AsyncClient,
    other_client: AsyncClient,
    third_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    _ada, org_id, url = await setup(client)
    grace_id = await join(other_client, db_session, org_id)
    linus_id = await join(third_client, db_session, org_id, "linus@example.com", "Linus")
    await client.put(url, json=user_grant(grace_id, "admin"))

    granted = await other_client.put(url, json=user_grant(linus_id, "editor"))
    revoked = await other_client.delete(f"{url}/{granted.json()['id']}")

    assert granted.status_code == 200, granted.text
    assert revoked.status_code == 204
    assert len((await other_client.get(url)).json()) == 2


async def test_the_only_admin_grant_can_go_while_the_organization_has_an_owner(
    client: AsyncClient,
) -> None:
    ada, _org_id, url = await setup(client)
    [grant] = (await client.get(url)).json()

    downgraded = await client.put(url, json=user_grant(ada["user"]["id"], "viewer"))
    revoked = await client.delete(f"{url}/{grant['id']}")

    assert downgraded.status_code == 200, downgraded.text
    assert revoked.status_code == 204
    # Ada is the organization's owner, so she still administers the project.
    assert (await client.get(url)).json() == []


async def test_last_admin_grant_cannot_go_without_an_organization_owner_or_admin(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    ada, org_id, url = await setup(client)
    grace_id = await join(other_client, db_session, org_id)
    agent_id = await create_agent(client, org_id)
    await client.put(url, json=user_grant(grace_id, "editor"))
    # An agent that is admin does not keep the project within people's reach.
    await client.put(url, json=agent_grant(agent_id, "admin"))
    await make_plain_member(db_session, org_id, ada["user"]["id"])
    [ada_grant, _grace_grant, _agent_grant] = (await client.get(url)).json()

    downgraded = await client.put(url, json=user_grant(ada["user"]["id"], "editor"))
    revoked = await client.delete(f"{url}/{ada_grant['id']}")
    same_role = await client.put(url, json=user_grant(ada["user"]["id"], "admin"))

    for response in (downgraded, revoked):
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "last_project_admin"
    assert same_role.status_code == 200
    assert [g["role"] for g in (await client.get(url)).json()] == ["admin", "editor", "admin"]


async def test_an_admin_grant_can_go_when_another_member_is_admin(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    ada, org_id, url = await setup(client)
    grace_id = await join(other_client, db_session, org_id)
    await client.put(url, json=user_grant(grace_id, "admin"))
    await make_plain_member(db_session, org_id, ada["user"]["id"])
    [ada_grant, grace_grant] = (await client.get(url)).json()

    downgraded = await client.put(url, json=user_grant(ada["user"]["id"], "viewer"))
    # Grace is the last admin now.
    grace_downgraded = await other_client.put(url, json=user_grant(grace_id, "viewer"))
    grace_revoked = await other_client.delete(f"{url}/{grace_grant['id']}")
    # Revoking a grant that is not an admin grant is always fine.
    ada_revoked = await other_client.delete(f"{url}/{ada_grant['id']}")

    assert downgraded.status_code == 200, downgraded.text
    assert grace_downgraded.status_code == 409
    assert grace_revoked.status_code == 409
    assert ada_revoked.status_code == 204
    assert [(g["name"], g["role"]) for g in (await other_client.get(url)).json()] == [
        ("Grace", "admin")
    ]
