"""Invitations: invite by email, join on sign-in, list, revoke, conflicts and permissions."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers import add_in_savepoint, add_member, sign_in
from todolist.models import Invitation, InvitationRole, MembershipRole, Organization, User
from todolist.services.users import get_or_create_user


async def ada_org(client: AsyncClient) -> tuple[str, str]:
    """Sign Ada in; returns her default organization's id and its invitations URL."""
    ada = await sign_in(client)
    org_id = ada["organizations"][0]["id"]
    return org_id, f"/api/orgs/{org_id}/invitations"


async def invitation_count(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(Invitation)) or 0


async def test_inviting_an_existing_user_adds_them_right_away(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, url = await ada_org(client)
    grace = await sign_in(other_client, "grace@example.com", "Grace")

    response = await client.post(url, json={"email": "Grace@Example.com", "role": "admin"})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "added"
    assert body["invitation"] is None
    assert body["member"] == {
        "user_id": grace["user"]["id"],
        "email": "grace@example.com",
        "name": "Grace",
        "role": "admin",
    }
    assert "now a member" in body["message"]
    assert await invitation_count(db_session) == 0

    # Grace sees the organization without signing in again.
    me = (await other_client.get("/api/me")).json()
    assert [(o["id"], o["role"]) for o in me["organizations"]][1:] == [(org_id, "admin")]
    assert (await client.get(url)).json() == []


async def test_inviting_an_unknown_email_stores_an_invitation_that_is_accepted_on_sign_in(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, url = await ada_org(client)
    ada_id = (await client.get("/api/me")).json()["user"]["id"]

    response = await client.post(url, json={"email": " Grace@Example.com", "role": "member"})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "invited"
    assert body["member"] is None
    assert "No email is sent" in body["message"]
    assert "next time they sign in" in body["message"]
    invitation = body["invitation"]
    assert invitation["email"] == "grace@example.com"
    assert invitation["role"] == "member"
    assert invitation["invited_by"] == {"user_id": ada_id, "name": "Ada"}
    assert invitation["created_at"]

    assert (await client.get(url)).json() == [invitation]
    # Not a member yet.
    members = (await client.get(f"/api/orgs/{org_id}/members")).json()
    assert [m["email"] for m in members] == ["ada@example.com"]

    grace = await sign_in(other_client, "grace@example.com", "Grace")

    # Her own default organization first, then the one she was invited to.
    assert [(o["name"], o["role"]) for o in grace["organizations"]] == [
        ("Grace's organization", "owner"),
        ("Ada's organization", "member"),
    ]
    assert grace["organizations"][1]["id"] == org_id
    assert (await client.get(url)).json() == []
    assert await invitation_count(db_session) == 0
    members = (await client.get(f"/api/orgs/{org_id}/members")).json()
    assert [(m["email"], m["role"]) for m in members] == [
        ("ada@example.com", "owner"),
        ("grace@example.com", "member"),
    ]


async def test_role_defaults_to_member(client: AsyncClient) -> None:
    _org_id, url = await ada_org(client)
    response = await client.post(url, json={"email": "grace@example.com"})
    assert response.json()["invitation"]["role"] == "member"


async def test_sign_in_accepts_invitations_from_several_organizations(
    client: AsyncClient, other_client: AsyncClient, third_client: AsyncClient
) -> None:
    _org_id, url = await ada_org(client)
    linus = await sign_in(third_client, "linus@example.com", "Linus")
    linus_url = f"/api/orgs/{linus['organizations'][0]['id']}/invitations"
    await client.post(url, json={"email": "grace@example.com", "role": "member"})
    await third_client.post(linus_url, json={"email": "grace@example.com", "role": "admin"})

    grace = await sign_in(other_client, "grace@example.com", "Grace")

    assert [(o["name"], o["role"]) for o in grace["organizations"]] == [
        ("Grace's organization", "owner"),
        ("Ada's organization", "member"),
        ("Linus's organization", "admin"),
    ]


async def test_existing_user_accepts_a_leftover_invitation_on_sign_in(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    """An invitation can outlive the moment the account appears (it was stored just before the
    first sign-in finished); any later sign-in picks it up."""
    org_id, url = await ada_org(client)
    await sign_in(other_client, "grace@example.com", "Grace")
    db_session.add(
        Invitation(
            organization_id=uuid.UUID(org_id), email="grace@example.com", role=InvitationRole.ADMIN
        )
    )
    await db_session.flush()

    grace = await sign_in(other_client, "grace@example.com", "Grace")

    assert [(o["id"], o["role"]) for o in grace["organizations"]][1:] == [(org_id, "admin")]
    assert (await client.get(url)).json() == []


async def test_invitation_for_someone_who_is_a_member_already_is_dropped_on_sign_in(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, _url = await ada_org(client)
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    await add_member(db_session, org_id, grace["user"]["id"], MembershipRole.MEMBER)
    db_session.add(
        Invitation(
            organization_id=uuid.UUID(org_id), email="grace@example.com", role=InvitationRole.ADMIN
        )
    )
    await db_session.flush()

    grace = await sign_in(other_client, "grace@example.com", "Grace")

    # The membership she had is kept as it was.
    assert [(o["id"], o["role"]) for o in grace["organizations"]][1:] == [(org_id, "member")]
    assert await invitation_count(db_session) == 0


async def test_get_or_create_user_converts_invitations(db_session: AsyncSession) -> None:
    ada = await get_or_create_user(db_session, "ada@example.com", "Ada")
    organization = (await db_session.scalars(select(Organization))).one()
    db_session.add(
        Invitation(
            organization_id=organization.id,
            email="Grace@Example.com",
            role=InvitationRole.MEMBER,
            invited_by=ada.id,
        )
    )
    await db_session.flush()

    await get_or_create_user(db_session, "GRACE@example.com", "Grace", google_sub="sub-grace")

    assert await invitation_count(db_session) == 0
    organizations = (await db_session.scalars(select(Organization.name))).all()
    assert sorted(organizations) == ["Ada's organization", "Grace's organization"]


async def test_revoke(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, url = await ada_org(client)
    invitation_id = (await client.post(url, json={"email": "grace@example.com"})).json()[
        "invitation"
    ]["id"]

    response = await client.delete(f"{url}/{invitation_id}")

    assert response.status_code == 204
    assert (await client.get(url)).json() == []
    assert (await client.delete(f"{url}/{invitation_id}")).status_code == 404

    # Signing in afterwards does not join the organization.
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    assert [o["name"] for o in grace["organizations"]] == ["Grace's organization"]
    # The address can be invited again (Grace exists now, so she is added).
    again = await client.post(url, json={"email": "grace@example.com"})
    assert again.status_code == 201
    assert again.json()["status"] == "added"
    assert org_id in [o["id"] for o in (await other_client.get("/api/me")).json()["organizations"]]


async def test_duplicate_invitation_is_a_conflict(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _org_id, url = await ada_org(client)
    assert (await client.post(url, json={"email": "grace@example.com"})).status_code == 201

    response = await client.post(url, json={"email": "GRACE@example.com", "role": "admin"})

    assert response.status_code == 409
    assert response.json()["code"] == "already_invited"
    assert await invitation_count(db_session) == 1
    assert [i["role"] for i in (await client.get(url)).json()] == ["member"]


async def test_inviting_an_existing_member_is_a_conflict(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, url = await ada_org(client)
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    await add_member(db_session, org_id, grace["user"]["id"], MembershipRole.MEMBER)

    for email in ("grace@example.com", "ada@example.com"):
        response = await client.post(url, json={"email": email, "role": "admin"})
        assert response.status_code == 409
        assert response.json()["code"] == "already_member"

    members = (await client.get(f"/api/orgs/{org_id}/members")).json()
    assert [(m["email"], m["role"]) for m in members] == [
        ("ada@example.com", "owner"),
        ("grace@example.com", "member"),
    ]


async def test_same_email_can_be_invited_to_two_organizations(client: AsyncClient) -> None:
    _org_id, url = await ada_org(client)
    second = (await client.post("/api/orgs", json={"name": "Second"})).json()
    second_url = f"/api/orgs/{second['id']}/invitations"

    assert (await client.post(url, json={"email": "grace@example.com"})).status_code == 201
    assert (await client.post(second_url, json={"email": "grace@example.com"})).status_code == 201
    assert len((await client.get(second_url)).json()) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"email": "grace@example.com", "role": "owner"},
        {"email": "grace@example.com", "role": "viewer"},
        {"email": "not-an-email", "role": "member"},
        {"role": "member"},
    ],
)
async def test_invalid_invitation_is_rejected(
    client: AsyncClient, db_session: AsyncSession, body: dict[str, str]
) -> None:
    _org_id, url = await ada_org(client)
    assert (await client.post(url, json=body)).status_code == 422
    assert await invitation_count(db_session) == 0


async def test_admin_can_invite_list_and_revoke(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, url = await ada_org(client)
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    await add_member(db_session, org_id, grace["user"]["id"], MembershipRole.ADMIN)

    created = await other_client.post(url, json={"email": "linus@example.com", "role": "admin"})
    assert created.status_code == 201
    invitation = created.json()["invitation"]
    assert invitation["invited_by"] == {"user_id": grace["user"]["id"], "name": "Grace"}
    assert (await other_client.get(url)).json() == [invitation]
    assert (await other_client.delete(f"{url}/{invitation['id']}")).status_code == 204


async def test_member_cannot_invite_list_or_revoke(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, url = await ada_org(client)
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    await add_member(db_session, org_id, grace["user"]["id"], MembershipRole.MEMBER)
    invitation_id = (await client.post(url, json={"email": "linus@example.com"})).json()[
        "invitation"
    ]["id"]

    responses = [
        await other_client.post(url, json={"email": "new@example.com"}),
        await other_client.get(url),
        await other_client.delete(f"{url}/{invitation_id}"),
    ]

    assert [r.status_code for r in responses] == [403, 403, 403]
    assert await invitation_count(db_session) == 1


async def test_outsider_and_anonymous_get_404_and_401(
    client: AsyncClient, other_client: AsyncClient, third_client: AsyncClient
) -> None:
    _org_id, url = await ada_org(client)
    invitation_id = (await client.post(url, json={"email": "linus@example.com"})).json()[
        "invitation"
    ]["id"]
    await sign_in(other_client, "grace@example.com", "Grace")

    assert (await other_client.get(url)).status_code == 404
    assert (await other_client.post(url, json={"email": "x@example.com"})).status_code == 404
    assert (await other_client.delete(f"{url}/{invitation_id}")).status_code == 404
    assert (await third_client.get(url)).status_code == 401
    assert len((await client.get(url)).json()) == 1


async def test_invitation_of_another_organization_cannot_be_revoked(
    client: AsyncClient, other_client: AsyncClient
) -> None:
    _org_id, url = await ada_org(client)
    invitation_id = (await client.post(url, json={"email": "linus@example.com"})).json()[
        "invitation"
    ]["id"]
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    grace_url = f"/api/orgs/{grace['organizations'][0]['id']}/invitations"

    assert (await other_client.delete(f"{grace_url}/{invitation_id}")).status_code == 404
    assert len((await client.get(url)).json()) == 1


async def test_model_lowercases_email_and_constraints_hold(db_session: AsyncSession) -> None:
    ada = await get_or_create_user(db_session, "ada@example.com", "Ada")
    organization = (await db_session.scalars(select(Organization))).one()
    invitation = Invitation(
        organization_id=organization.id,
        email=" Grace@Example.COM ",
        role=InvitationRole.ADMIN,
        invited_by=ada.id,
    )
    db_session.add(invitation)
    await db_session.flush()
    assert invitation.email == "grace@example.com"
    assert invitation.created_at is not None

    duplicate = Invitation(
        organization_id=organization.id, email="GRACE@example.com", role=InvitationRole.MEMBER
    )
    with pytest.raises(IntegrityError) as error:
        await add_in_savepoint(db_session, duplicate)
    assert "uq_invitations_organization_id_email" in str(error.value)

    # Deleting the inviter keeps the invitation; deleting the organization removes it.
    await db_session.execute(delete(User).where(User.id == ada.id))
    await db_session.refresh(invitation)
    assert invitation.invited_by is None
    await db_session.execute(delete(Organization).where(Organization.id == organization.id))
    assert await invitation_count(db_session) == 0
