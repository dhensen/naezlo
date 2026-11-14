"""Organization API: list, create, read, rename."""

import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers import sign_in
from todolist.models import Membership, MembershipRole, Organization


@pytest.fixture
async def other_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """A second browser, for a second user."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def add_member(
    session: AsyncSession, organization_id: str, user_id: str, role: MembershipRole
) -> None:
    session.add(
        Membership(
            organization_id=uuid.UUID(organization_id), user_id=uuid.UUID(user_id), role=role
        )
    )
    await session.flush()


async def test_list_returns_my_organizations_with_role(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    ada = await sign_in(client)
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    grace_org = grace["organizations"][0]
    await add_member(db_session, grace_org["id"], ada["user"]["id"], MembershipRole.MEMBER)

    response = await client.get("/api/orgs")

    assert response.status_code == 200
    assert response.json() == [ada["organizations"][0], {**grace_org, "role": "member"}]
    # Grace is not in Ada's organization and does not see it.
    assert (await other_client.get("/api/orgs")).json() == [grace_org]


async def test_create_makes_the_creator_owner(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    me = await sign_in(client)

    response = await client.post("/api/orgs", json={"name": "  Analytical Engines  "})

    assert response.status_code == 201
    created = response.json()
    assert created["name"] == "Analytical Engines"
    assert created["slug"] == "analytical-engines"
    assert created["role"] == "owner"
    membership = (
        await db_session.execute(
            select(Membership).where(Membership.organization_id == uuid.UUID(created["id"]))
        )
    ).scalar_one()
    assert membership.user_id == uuid.UUID(me["user"]["id"])
    assert membership.role is MembershipRole.OWNER
    assert (await client.get("/api/orgs")).json() == [me["organizations"][0], created]


async def test_create_gives_a_unique_slug(client: AsyncClient, other_client: AsyncClient) -> None:
    await sign_in(client)
    await sign_in(other_client, "grace@example.com", "Grace")

    first = await client.post("/api/orgs", json={"name": "Engines"})
    second = await client.post("/api/orgs", json={"name": "Engines"})
    third = await other_client.post("/api/orgs", json={"name": "engines!"})

    assert [r.json()["slug"] for r in (first, second, third)] == [
        "engines",
        "engines-2",
        "engines-3",
    ]


@pytest.mark.parametrize("name", ["", "   ", "x" * 201, None])
async def test_create_rejects_a_bad_name(client: AsyncClient, name: str | None) -> None:
    await sign_in(client)

    response = await client.post("/api/orgs", json={"name": name})

    assert response.status_code == 422


async def test_get_returns_the_organization_for_a_member(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    ada = await sign_in(client)
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    org = ada["organizations"][0]
    await add_member(db_session, org["id"], grace["user"]["id"], MembershipRole.MEMBER)

    assert (await client.get(f"/api/orgs/{org['id']}")).json() == org
    response = await other_client.get(f"/api/orgs/{org['id']}")
    assert response.status_code == 200
    assert response.json() == {**org, "role": "member"}


async def test_get_is_404_for_non_members_and_unknown_ids(
    client: AsyncClient, other_client: AsyncClient
) -> None:
    ada = await sign_in(client)
    await sign_in(other_client, "grace@example.com", "Grace")
    org_id = ada["organizations"][0]["id"]

    not_member = await other_client.get(f"/api/orgs/{org_id}")
    unknown = await other_client.get(f"/api/orgs/{uuid.uuid4()}")

    assert not_member.status_code == 404
    assert not_member.json() == {"detail": "Organization not found", "code": "not_found"}
    # An organization that exists looks exactly like one that doesn't.
    assert unknown.status_code == 404
    assert unknown.json() == not_member.json()


@pytest.mark.parametrize("role", [MembershipRole.OWNER, MembershipRole.ADMIN])
async def test_owner_and_admin_can_rename(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession, role: MembershipRole
) -> None:
    ada = await sign_in(client)
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    org = ada["organizations"][0]
    await add_member(db_session, org["id"], grace["user"]["id"], role)

    response = await other_client.patch(f"/api/orgs/{org['id']}", json={"name": " Renamed "})

    assert response.status_code == 200
    # The slug does not follow the name.
    assert response.json() == {**org, "name": "Renamed", "role": role.value}
    assert (await client.get(f"/api/orgs/{org['id']}")).json()["name"] == "Renamed"
    organization = await db_session.get(Organization, uuid.UUID(org["id"]))
    assert organization is not None
    assert organization.name == "Renamed"


async def test_member_cannot_rename(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    ada = await sign_in(client)
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    org = ada["organizations"][0]
    await add_member(db_session, org["id"], grace["user"]["id"], MembershipRole.MEMBER)

    response = await other_client.patch(f"/api/orgs/{org['id']}", json={"name": "Mine now"})

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    assert (await client.get(f"/api/orgs/{org['id']}")).json()["name"] == org["name"]


async def test_rename_is_404_for_non_members(
    client: AsyncClient, other_client: AsyncClient
) -> None:
    ada = await sign_in(client)
    await sign_in(other_client, "grace@example.com", "Grace")
    org = ada["organizations"][0]

    response = await other_client.patch(f"/api/orgs/{org['id']}", json={"name": "Mine now"})

    assert response.status_code == 404
    assert (await client.get(f"/api/orgs/{org['id']}")).json()["name"] == org["name"]


async def test_rename_rejects_an_empty_name(client: AsyncClient) -> None:
    me = await sign_in(client)

    response = await client.patch(f"/api/orgs/{me['organizations'][0]['id']}", json={"name": "  "})

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/orgs"),
        ("POST", "/api/orgs"),
        ("GET", f"/api/orgs/{uuid.uuid4()}"),
        ("PATCH", f"/api/orgs/{uuid.uuid4()}"),
    ],
)
async def test_endpoints_need_a_signed_in_user(client: AsyncClient, method: str, path: str) -> None:
    response = await client.request(method, path, json={"name": "Engines"})

    assert response.status_code == 401
