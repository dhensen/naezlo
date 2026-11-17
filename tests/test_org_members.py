"""Organization members API: list, role changes, removal, leaving, the last-owner rule."""

import uuid
from dataclasses import dataclass

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from naezlo.models import Membership, MembershipRole
from tests.helpers import add_member, sign_in

OWNER, ADMIN, MEMBER = MembershipRole.OWNER, MembershipRole.ADMIN, MembershipRole.MEMBER


@dataclass
class Org:
    """Ada's default organization, with Grace and Linus added to it."""

    id: str
    ada: str
    grace: str
    linus: str

    @property
    def members_url(self) -> str:
        return f"/api/orgs/{self.id}/members"

    def member_url(self, user_id: str) -> str:
        return f"{self.members_url}/{user_id}"


async def make_org(
    session: AsyncSession,
    client: AsyncClient,
    other_client: AsyncClient,
    third_client: AsyncClient,
    grace_role: MembershipRole,
    linus_role: MembershipRole,
) -> Org:
    """Ada (`client`) owns the organization; Grace (`other_client`) and Linus (`third_client`)
    join with the given roles."""
    ada = await sign_in(client)
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    linus = await sign_in(third_client, "linus@example.com", "Linus")
    org_id = ada["organizations"][0]["id"]
    await add_member(session, org_id, grace["user"]["id"], grace_role)
    await add_member(session, org_id, linus["user"]["id"], linus_role)
    return Org(
        id=org_id, ada=ada["user"]["id"], grace=grace["user"]["id"], linus=linus["user"]["id"]
    )


async def roles(session: AsyncSession, org: Org) -> dict[str, str]:
    """user id → role, read from the database."""
    rows = await session.execute(
        select(Membership.user_id, Membership.role).where(
            Membership.organization_id == uuid.UUID(org.id)
        )
    )
    return {str(user_id): role.value for user_id, role in rows}


# --- list ---


@pytest.mark.parametrize("grace_role", [OWNER, ADMIN, MEMBER])
async def test_any_member_can_list_members(
    client: AsyncClient,
    other_client: AsyncClient,
    third_client: AsyncClient,
    db_session: AsyncSession,
    grace_role: MembershipRole,
) -> None:
    org = await make_org(db_session, client, other_client, third_client, grace_role, MEMBER)

    response = await other_client.get(org.members_url)

    assert response.status_code == 200
    assert response.json() == [
        {"user_id": org.ada, "email": "ada@example.com", "name": "Ada", "role": "owner"},
        {
            "user_id": org.grace,
            "email": "grace@example.com",
            "name": "Grace",
            "role": grace_role.value,
        },
        {"user_id": org.linus, "email": "linus@example.com", "name": "Linus", "role": "member"},
    ]


async def test_list_is_404_for_non_members(client: AsyncClient, other_client: AsyncClient) -> None:
    ada = await sign_in(client)
    await sign_in(other_client, "grace@example.com", "Grace")

    response = await other_client.get(f"/api/orgs/{ada['organizations'][0]['id']}/members")

    assert response.status_code == 404
    assert response.json() == {"detail": "Organization not found", "code": "not_found"}


# --- role changes ---


@pytest.mark.parametrize(
    ("grace_role", "linus_role", "new_role"),
    [
        (OWNER, MEMBER, ADMIN),
        (OWNER, MEMBER, OWNER),
        (OWNER, ADMIN, MEMBER),
        (OWNER, OWNER, ADMIN),
        (OWNER, OWNER, MEMBER),
        (ADMIN, MEMBER, ADMIN),
        (ADMIN, ADMIN, MEMBER),
    ],
)
async def test_owner_and_admin_can_change_roles(
    client: AsyncClient,
    other_client: AsyncClient,
    third_client: AsyncClient,
    db_session: AsyncSession,
    grace_role: MembershipRole,
    linus_role: MembershipRole,
    new_role: MembershipRole,
) -> None:
    org = await make_org(db_session, client, other_client, third_client, grace_role, linus_role)

    response = await other_client.patch(org.member_url(org.linus), json={"role": new_role.value})

    assert response.status_code == 200
    assert response.json() == {
        "user_id": org.linus,
        "email": "linus@example.com",
        "name": "Linus",
        "role": new_role.value,
    }
    assert (await roles(db_session, org))[org.linus] == new_role.value
    # The new role counts right away.
    me = (await third_client.get(f"/api/orgs/{org.id}")).json()
    assert me["role"] == new_role.value


@pytest.mark.parametrize(
    ("linus_role", "new_role"),
    [
        (MEMBER, OWNER),  # granting the owner role
        (ADMIN, OWNER),
        (OWNER, ADMIN),  # taking it away
        (OWNER, MEMBER),
    ],
)
async def test_admin_cannot_grant_or_take_away_the_owner_role(
    client: AsyncClient,
    other_client: AsyncClient,
    third_client: AsyncClient,
    db_session: AsyncSession,
    linus_role: MembershipRole,
    new_role: MembershipRole,
) -> None:
    org = await make_org(db_session, client, other_client, third_client, ADMIN, linus_role)

    response = await other_client.patch(org.member_url(org.linus), json={"role": new_role.value})

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    assert (await roles(db_session, org))[org.linus] == linus_role.value


async def test_admin_cannot_make_themselves_owner(
    client: AsyncClient,
    other_client: AsyncClient,
    third_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org = await make_org(db_session, client, other_client, third_client, ADMIN, MEMBER)

    response = await other_client.patch(org.member_url(org.grace), json={"role": "owner"})

    assert response.status_code == 403
    assert (await roles(db_session, org))[org.grace] == "admin"


@pytest.mark.parametrize("target", ["linus", "grace"])
async def test_member_cannot_change_roles(
    client: AsyncClient,
    other_client: AsyncClient,
    third_client: AsyncClient,
    db_session: AsyncSession,
    target: str,
) -> None:
    org = await make_org(db_session, client, other_client, third_client, MEMBER, MEMBER)
    before = await roles(db_session, org)

    response = await other_client.patch(
        org.member_url(getattr(org, target)), json={"role": "admin"}
    )

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    assert await roles(db_session, org) == before


async def test_owner_can_step_down_when_there_is_another_owner(
    client: AsyncClient,
    other_client: AsyncClient,
    third_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org = await make_org(db_session, client, other_client, third_client, OWNER, MEMBER)

    response = await client.patch(org.member_url(org.ada), json={"role": "member"})

    assert response.status_code == 200
    assert (await roles(db_session, org))[org.ada] == "member"


@pytest.mark.parametrize("new_role", ["admin", "member"])
async def test_last_owner_cannot_be_demoted(
    client: AsyncClient,
    other_client: AsyncClient,
    third_client: AsyncClient,
    db_session: AsyncSession,
    new_role: str,
) -> None:
    org = await make_org(db_session, client, other_client, third_client, ADMIN, MEMBER)

    response = await client.patch(org.member_url(org.ada), json={"role": new_role})

    assert response.status_code == 409
    assert response.json()["code"] == "last_owner"
    assert (await roles(db_session, org))[org.ada] == "owner"


async def test_last_owner_can_keep_the_owner_role(
    client: AsyncClient,
    other_client: AsyncClient,
    third_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org = await make_org(db_session, client, other_client, third_client, ADMIN, MEMBER)

    response = await client.patch(org.member_url(org.ada), json={"role": "owner"})

    assert response.status_code == 200
    assert response.json()["role"] == "owner"


async def test_change_role_rejects_an_unknown_role(client: AsyncClient) -> None:
    me = await sign_in(client)
    url = f"/api/orgs/{me['organizations'][0]['id']}/members/{me['user']['id']}"

    assert (await client.patch(url, json={"role": "superuser"})).status_code == 422
    assert (await client.patch(url, json={})).status_code == 422


# --- removal ---


@pytest.mark.parametrize(
    ("grace_role", "linus_role"),
    [(OWNER, MEMBER), (OWNER, ADMIN), (OWNER, OWNER), (ADMIN, MEMBER), (ADMIN, ADMIN)],
)
async def test_owner_and_admin_can_remove_members(
    client: AsyncClient,
    other_client: AsyncClient,
    third_client: AsyncClient,
    db_session: AsyncSession,
    grace_role: MembershipRole,
    linus_role: MembershipRole,
) -> None:
    org = await make_org(db_session, client, other_client, third_client, grace_role, linus_role)

    response = await other_client.delete(org.member_url(org.linus))

    assert response.status_code == 204
    assert org.linus not in await roles(db_session, org)
    # Linus is out: the organization no longer exists for him.
    assert (await third_client.get(f"/api/orgs/{org.id}")).status_code == 404
    assert [m["user_id"] for m in (await client.get(org.members_url)).json()] == [
        org.ada,
        org.grace,
    ]


async def test_admin_cannot_remove_an_owner(
    client: AsyncClient,
    other_client: AsyncClient,
    third_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org = await make_org(db_session, client, other_client, third_client, ADMIN, OWNER)

    response = await other_client.delete(org.member_url(org.linus))

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    assert (await roles(db_session, org))[org.linus] == "owner"


async def test_member_cannot_remove_someone_else(
    client: AsyncClient,
    other_client: AsyncClient,
    third_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org = await make_org(db_session, client, other_client, third_client, MEMBER, MEMBER)

    response = await other_client.delete(org.member_url(org.linus))

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    assert org.linus in await roles(db_session, org)


@pytest.mark.parametrize("grace_role", [OWNER, ADMIN, MEMBER])
async def test_a_member_can_leave(
    client: AsyncClient,
    other_client: AsyncClient,
    third_client: AsyncClient,
    db_session: AsyncSession,
    grace_role: MembershipRole,
) -> None:
    org = await make_org(db_session, client, other_client, third_client, grace_role, MEMBER)

    response = await other_client.delete(org.member_url(org.grace))

    assert response.status_code == 204
    assert org.grace not in await roles(db_session, org)
    assert (await other_client.get(f"/api/orgs/{org.id}")).status_code == 404
    # Grace keeps her own organization.
    assert len((await other_client.get("/api/orgs")).json()) == 1


async def test_last_owner_cannot_leave(
    client: AsyncClient,
    other_client: AsyncClient,
    third_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org = await make_org(db_session, client, other_client, third_client, ADMIN, MEMBER)

    response = await client.delete(org.member_url(org.ada))

    assert response.status_code == 409
    assert response.json()["code"] == "last_owner"
    assert (await roles(db_session, org))[org.ada] == "owner"


async def test_sole_member_cannot_leave_their_organization(client: AsyncClient) -> None:
    me = await sign_in(client)
    org_id = me["organizations"][0]["id"]

    response = await client.delete(f"/api/orgs/{org_id}/members/{me['user']['id']}")

    assert response.status_code == 409
    assert (await client.get(f"/api/orgs/{org_id}")).status_code == 200


async def test_an_owner_can_leave_after_making_someone_else_owner(
    client: AsyncClient,
    other_client: AsyncClient,
    third_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org = await make_org(db_session, client, other_client, third_client, ADMIN, MEMBER)

    promoted = await client.patch(org.member_url(org.grace), json={"role": "owner"})
    left = await client.delete(org.member_url(org.ada))

    assert promoted.status_code == 200
    assert left.status_code == 204
    assert await roles(db_session, org) == {org.grace: "owner", org.linus: "member"}


# --- unknown targets and outsiders ---


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
async def test_target_who_is_not_a_member_is_404(
    client: AsyncClient, other_client: AsyncClient, method: str
) -> None:
    ada = await sign_in(client)
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    base = f"/api/orgs/{ada['organizations'][0]['id']}/members"

    # Grace exists but is not in Ada's organization; the other id belongs to nobody.
    for user_id in (grace["user"]["id"], str(uuid.uuid4())):
        response = await client.request(method, f"{base}/{user_id}", json={"role": "admin"})
        assert response.status_code == 404
        assert response.json() == {"detail": "Member not found", "code": "not_found"}


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
async def test_non_members_cannot_change_or_remove(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession, method: str
) -> None:
    ada = await sign_in(client)
    await sign_in(other_client, "grace@example.com", "Grace")
    org_id = ada["organizations"][0]["id"]

    response = await other_client.request(
        method, f"/api/orgs/{org_id}/members/{ada['user']['id']}", json={"role": "member"}
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Organization not found", "code": "not_found"}
    assert (await client.get(f"/api/orgs/{org_id}")).json()["role"] == "owner"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", f"/api/orgs/{uuid.uuid4()}/members"),
        ("PATCH", f"/api/orgs/{uuid.uuid4()}/members/{uuid.uuid4()}"),
        ("DELETE", f"/api/orgs/{uuid.uuid4()}/members/{uuid.uuid4()}"),
    ],
)
async def test_endpoints_need_a_signed_in_user(client: AsyncClient, method: str, path: str) -> None:
    response = await client.request(method, path, json={"role": "member"})

    assert response.status_code == 401
