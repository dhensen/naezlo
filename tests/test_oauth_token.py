"""The OAuth token endpoint (POST /token), revocation (POST /revoke) and `resolve_access_token`."""

import base64
import hashlib
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient, Response
from mcp.shared.auth import OAuthToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from naezlo.db import get_session
from naezlo.models import (
    Membership,
    MembershipRole,
    OAuthAccessToken,
    OAuthAuthorizationCode,
    OAuthRefreshToken,
    PrincipalKind,
)
from naezlo.services.oauth import hash_token
from naezlo.services.oauth_tokens import resolve_access_token
from tests.helpers import add_member, sign_in
from tests.test_oauth_authorize import CALLBACK, ISSUER, callback_params, create_agent, start

VERIFIER = "v3rifier-" + "x" * 40
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=")
RESOURCE = f"{ISSUER}/mcp"


@dataclass
class Authorized:
    """An approved authorization: what the client holds when it comes to /token."""

    client_id: str
    code: str
    agent: dict[str, Any]
    org_id: str


async def register(client: AsyncClient, **metadata: Any) -> str:
    response = await client.post("/register", json={"redirect_uris": [CALLBACK], **metadata})
    assert response.status_code == 201, response.text
    return response.json()["client_id"]


async def authorize(client: AsyncClient, **metadata: Any) -> Authorized:
    """Sign in as Ada, register a client and approve it for a new agent."""
    me = await sign_in(client)
    org_id = me["organizations"][0]["id"]
    agent = await create_agent(client, org_id)
    client_id = await register(client, **metadata)
    code = await approve(client, client_id, agent["id"])
    return Authorized(client_id=client_id, code=code, agent=agent, org_id=org_id)


async def approve(client: AsyncClient, client_id: str, agent_id: str) -> str:
    """Run /authorize and the consent screen as the signed-in user; returns the code."""
    request_id = await start(client, client_id, code_challenge=CHALLENGE.decode())
    response = await client.post(
        f"/api/oauth/requests/{request_id}/approve", json={"agent_id": agent_id}
    )
    assert response.status_code == 200, response.text
    return callback_params(response.json()["redirect_url"])["code"]


def code_form(authorized: Authorized, **overrides: str | None) -> dict[str, str]:
    """A valid authorization_code token request; an override of None leaves a field out."""
    form: dict[str, str | None] = {
        "grant_type": "authorization_code",
        "code": authorized.code,
        "redirect_uri": CALLBACK,
        "client_id": authorized.client_id,
        "code_verifier": VERIFIER,
        "resource": RESOURCE,
    }
    form.update(overrides)
    return {name: value for name, value in form.items() if value is not None}


async def exchange(client: AsyncClient, authorized: Authorized) -> dict[str, Any]:
    response = await client.post("/token", data=code_form(authorized))
    assert response.status_code == 200, response.text
    return response.json()


async def refresh(client: AsyncClient, client_id: str, refresh_token: str) -> Response:
    return await client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "resource": RESOURCE,
        },
    )


async def revoke(client: AsyncClient, client_id: str, token: str) -> Response:
    return await client.post("/revoke", data={"token": token, "client_id": client_id})


def assert_oauth_error(response: Response, error: str, status_code: int = 400) -> None:
    assert response.status_code == status_code, response.text
    body = response.json()
    assert set(body) == {"error", "error_description"}
    assert body["error"] == error
    assert response.headers["cache-control"] == "no-store"


async def access_row(session: AsyncSession, token: str) -> OAuthAccessToken:
    return (
        await session.execute(
            select(OAuthAccessToken).where(OAuthAccessToken.token_hash == hash_token(token))
        )
    ).scalar_one()


async def refresh_row(session: AsyncSession, token: str) -> OAuthRefreshToken:
    return (
        await session.execute(
            select(OAuthRefreshToken).where(OAuthRefreshToken.token_hash == hash_token(token))
        )
    ).scalar_one()


async def test_exchange(client: AsyncClient, db_session: AsyncSession) -> None:
    authorized = await authorize(client)

    response = await client.post("/token", data=code_form(authorized))

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body == {
        "access_token": body["access_token"],
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": "mcp",
        "refresh_token": body["refresh_token"],
    }
    assert body["access_token"] != body["refresh_token"]
    # What the SDK's client parses.
    parsed = OAuthToken.model_validate(body)
    assert parsed.refresh_token == body["refresh_token"]

    code = (await db_session.execute(select(OAuthAuthorizationCode))).scalar_one()
    assert code.used_at is not None
    now = datetime.now(UTC)
    access = await access_row(db_session, body["access_token"])
    assert access.token_hash != body["access_token"]
    assert timedelta(minutes=59) < access.expires_at - now <= timedelta(hours=1)
    assert access.revoked_at is None
    assert access.client_id == authorized.client_id
    assert str(access.agent_id) == authorized.agent["id"]
    assert access.user_id == code.user_id
    assert access.scope == "mcp"
    assert access.resource == RESOURCE
    assert access.authorization_code_id == code.id
    refresh_token = await refresh_row(db_session, body["refresh_token"])
    assert timedelta(days=29) < refresh_token.expires_at - now <= timedelta(days=30)
    assert refresh_token.authorization_code_id == code.id
    assert str(refresh_token.agent_id) == authorized.agent["id"]

    principal = await resolve_access_token(db_session, body["access_token"])
    assert principal is not None
    assert principal.kind is PrincipalKind.AGENT
    assert str(principal.id) == authorized.agent["id"]
    assert str(principal.organization_id) == authorized.org_id
    assert principal.name == "Claude"
    # A refresh token is not an access token.
    assert await resolve_access_token(db_session, body["refresh_token"]) is None


async def test_exchange_without_resource(client: AsyncClient, db_session: AsyncSession) -> None:
    authorized = await authorize(client)

    response = await client.post("/token", data=code_form(authorized, resource=None))

    assert response.status_code == 200, response.text
    # The code was asked for the MCP endpoint, so the token is for it.
    assert (await access_row(db_session, response.json()["access_token"])).resource == RESOURCE


async def test_wrong_resource(client: AsyncClient) -> None:
    authorized = await authorize(client)

    response = await client.post(
        "/token", data=code_form(authorized, resource="https://elsewhere.example.com/mcp")
    )

    assert_oauth_error(response, "invalid_target")


async def test_wrong_verifier(client: AsyncClient, db_session: AsyncSession) -> None:
    authorized = await authorize(client)

    for verifier in ("w" * 43, "too-short", CHALLENGE.decode()):
        response = await client.post("/token", data=code_form(authorized, code_verifier=verifier))
        assert_oauth_error(response, "invalid_grant")
    response = await client.post("/token", data=code_form(authorized, code_verifier=None))
    assert_oauth_error(response, "invalid_request")

    assert (await db_session.execute(select(OAuthAccessToken))).first() is None
    # A failed attempt does not use the code up: the real client can still exchange it.
    await exchange(client, authorized)


async def test_wrong_redirect_uri(client: AsyncClient) -> None:
    authorized = await authorize(client)

    response = await client.post(
        "/token", data=code_form(authorized, redirect_uri=CALLBACK + "/other")
    )
    assert_oauth_error(response, "invalid_grant")
    response = await client.post("/token", data=code_form(authorized, redirect_uri=None))
    assert_oauth_error(response, "invalid_request")


async def test_unknown_code(client: AsyncClient) -> None:
    authorized = await authorize(client)

    response = await client.post("/token", data=code_form(authorized, code="not-a-code"))
    assert_oauth_error(response, "invalid_grant")
    response = await client.post("/token", data=code_form(authorized, code=None))
    assert_oauth_error(response, "invalid_request")


async def test_code_of_another_client(client: AsyncClient, db_session: AsyncSession) -> None:
    authorized = await authorize(client)
    other_client_id = await register(client)

    response = await client.post("/token", data=code_form(authorized, client_id=other_client_id))

    assert_oauth_error(response, "invalid_grant")
    # The code is still good for the client it was issued to.
    await exchange(client, authorized)


async def test_expired_code(client: AsyncClient, db_session: AsyncSession) -> None:
    authorized = await authorize(client)
    code = (await db_session.execute(select(OAuthAuthorizationCode))).scalar_one()
    code.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()

    response = await client.post("/token", data=code_form(authorized))

    assert_oauth_error(response, "invalid_grant")


async def test_invalid_client(client: AsyncClient) -> None:
    authorized = await authorize(client)

    for client_id in (str(uuid.uuid4()), "nul\x00byte", None):
        response = await client.post("/token", data=code_form(authorized, client_id=client_id))
        assert_oauth_error(response, "invalid_client", 401)
    response = await revoke(client, str(uuid.uuid4()), "some-token")
    assert_oauth_error(response, "invalid_client", 401)


async def test_grant_type_errors(client: AsyncClient) -> None:
    authorized = await authorize(client)

    response = await client.post(
        "/token", data=code_form(authorized, grant_type="client_credentials")
    )
    assert_oauth_error(response, "unsupported_grant_type")
    response = await client.post("/token", data=code_form(authorized, grant_type=None))
    assert_oauth_error(response, "invalid_request")


async def test_malformed_requests(client: AsyncClient) -> None:
    authorized = await authorize(client)

    # JSON instead of a form.
    response = await client.post("/token", json=code_form(authorized))
    assert_oauth_error(response, "invalid_request")
    # A parameter twice.
    response = await client.post(
        "/token",
        content=f"grant_type=authorization_code&code=a&code={authorized.code}",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert_oauth_error(response, "invalid_request")
    response = await client.post(
        "/token",
        content=b"grant_type=\xff",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert_oauth_error(response, "invalid_request")
    response = await client.post("/revoke", data={"client_id": authorized.client_id})
    assert_oauth_error(response, "invalid_request")


async def test_code_reuse_fails_and_revokes_its_tokens(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    authorized = await authorize(client)
    tokens = await exchange(client, authorized)
    # Tokens of a later refresh descend from the same code.
    refreshed = (await refresh(client, authorized.client_id, tokens["refresh_token"])).json()
    assert await resolve_access_token(db_session, refreshed["access_token"]) is not None

    response = await client.post("/token", data=code_form(authorized))

    assert_oauth_error(response, "invalid_grant")
    for access_token in (tokens["access_token"], refreshed["access_token"]):
        assert await resolve_access_token(db_session, access_token) is None
        assert (await access_row(db_session, access_token)).revoked_at is not None
    response = await refresh(client, authorized.client_id, refreshed["refresh_token"])
    assert_oauth_error(response, "invalid_grant")


async def test_code_reuse_does_not_touch_another_authorization(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    authorized = await authorize(client)
    tokens = await exchange(client, authorized)
    second = Authorized(
        client_id=authorized.client_id,
        code=await approve(client, authorized.client_id, authorized.agent["id"]),
        agent=authorized.agent,
        org_id=authorized.org_id,
    )
    await exchange(client, second)

    assert_oauth_error(await client.post("/token", data=code_form(second)), "invalid_grant")

    assert await resolve_access_token(db_session, tokens["access_token"]) is not None


async def test_revocation_after_reuse_survives_the_rollback_of_a_failed_request(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    """In production a raised error rolls the request's transaction back. The reuse answer
    is an error too, but the revocation it did must stay."""
    authorized = await authorize(client)
    tokens = await exchange(client, authorized)
    await db_session.commit()

    async def session_like_production() -> AsyncIterator[AsyncSession]:
        try:
            yield db_session
        except BaseException:
            await db_session.rollback()
            raise
        else:
            await db_session.commit()

    app.dependency_overrides[get_session] = session_like_production

    assert_oauth_error(await client.post("/token", data=code_form(authorized)), "invalid_grant")
    replayed = await refresh(client, authorized.client_id, tokens["refresh_token"])
    assert_oauth_error(replayed, "invalid_grant")

    db_session.expire_all()
    assert (await access_row(db_session, tokens["access_token"])).revoked_at is not None
    assert await resolve_access_token(db_session, tokens["access_token"]) is None


async def test_refresh_rotates(client: AsyncClient, db_session: AsyncSession) -> None:
    authorized = await authorize(client)
    tokens = await exchange(client, authorized)

    response = await refresh(client, authorized.client_id, tokens["refresh_token"])

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    refreshed = response.json()
    assert set(refreshed) == {"access_token", "token_type", "expires_in", "scope", "refresh_token"}
    assert refreshed["expires_in"] == 3600
    assert refreshed["access_token"] != tokens["access_token"]
    assert refreshed["refresh_token"] != tokens["refresh_token"]
    principal = await resolve_access_token(db_session, refreshed["access_token"])
    assert principal is not None
    assert str(principal.id) == authorized.agent["id"]
    old = await refresh_row(db_session, tokens["refresh_token"])
    assert old.revoked_at is not None
    new = await refresh_row(db_session, refreshed["refresh_token"])
    assert new.revoked_at is None
    assert new.authorization_code_id == old.authorization_code_id
    assert new.resource == RESOURCE
    # The access token from before the refresh lives out its hour.
    assert await resolve_access_token(db_session, tokens["access_token"]) is not None

    # The new refresh token works, once more.
    again = await refresh(client, authorized.client_id, refreshed["refresh_token"])
    assert again.status_code == 200, again.text


async def test_reused_refresh_token_is_rejected_and_ends_the_family(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    authorized = await authorize(client)
    tokens = await exchange(client, authorized)
    refreshed = (await refresh(client, authorized.client_id, tokens["refresh_token"])).json()

    response = await refresh(client, authorized.client_id, tokens["refresh_token"])

    assert_oauth_error(response, "invalid_grant")
    # Either the client or a thief used the old token: the tokens of both are gone.
    assert await resolve_access_token(db_session, refreshed["access_token"]) is None
    response = await refresh(client, authorized.client_id, refreshed["refresh_token"])
    assert_oauth_error(response, "invalid_grant")


async def test_refresh_errors(client: AsyncClient, db_session: AsyncSession) -> None:
    authorized = await authorize(client)
    tokens = await exchange(client, authorized)
    other_client_id = await register(client)

    assert_oauth_error(await refresh(client, authorized.client_id, "unknown"), "invalid_grant")
    # An access token is not a refresh token.
    response = await refresh(client, authorized.client_id, tokens["access_token"])
    assert_oauth_error(response, "invalid_grant")
    response = await refresh(client, other_client_id, tokens["refresh_token"])
    assert_oauth_error(response, "invalid_grant")
    response = await client.post(
        "/token", data={"grant_type": "refresh_token", "client_id": authorized.client_id}
    )
    assert_oauth_error(response, "invalid_request")
    response = await client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "client_id": authorized.client_id,
            "refresh_token": tokens["refresh_token"],
            "scope": "mcp admin",
        },
    )
    assert_oauth_error(response, "invalid_scope")

    # None of that used the token up.
    response = await refresh(client, authorized.client_id, tokens["refresh_token"])
    assert response.status_code == 200, response.text


async def test_expired_refresh_token(client: AsyncClient, db_session: AsyncSession) -> None:
    authorized = await authorize(client)
    tokens = await exchange(client, authorized)
    row = await refresh_row(db_session, tokens["refresh_token"])
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()

    response = await refresh(client, authorized.client_id, tokens["refresh_token"])

    assert_oauth_error(response, "invalid_grant")


async def test_client_without_the_refresh_grant(client: AsyncClient) -> None:
    authorized = await authorize(client, grant_types=["authorization_code"])

    tokens = await exchange(client, authorized)

    assert "refresh_token" not in tokens
    response = await refresh(client, authorized.client_id, "anything")
    assert_oauth_error(response, "unauthorized_client")


async def test_revoke_access_token(client: AsyncClient, db_session: AsyncSession) -> None:
    authorized = await authorize(client)
    tokens = await exchange(client, authorized)

    response = await client.post(
        "/revoke",
        data={
            "token": tokens["access_token"],
            "token_type_hint": "access_token",
            "client_id": authorized.client_id,
        },
    )

    assert response.status_code == 200, response.text
    assert response.content == b""
    assert await resolve_access_token(db_session, tokens["access_token"]) is None
    # Only that token: the client can still refresh.
    response = await refresh(client, authorized.client_id, tokens["refresh_token"])
    assert response.status_code == 200, response.text


async def test_revoke_refresh_token(client: AsyncClient, db_session: AsyncSession) -> None:
    authorized = await authorize(client)
    tokens = await exchange(client, authorized)

    response = await revoke(client, authorized.client_id, tokens["refresh_token"])

    assert response.status_code == 200, response.text
    response = await refresh(client, authorized.client_id, tokens["refresh_token"])
    assert_oauth_error(response, "invalid_grant")
    # The access token of the same authorization goes with it.
    assert await resolve_access_token(db_session, tokens["access_token"]) is None
    # Revoking again, or something that is no token, is not an error.
    assert (await revoke(client, authorized.client_id, tokens["refresh_token"])).status_code == 200
    assert (await revoke(client, authorized.client_id, "no-such-token")).status_code == 200


async def test_revoke_ignores_the_token_of_another_client(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    authorized = await authorize(client)
    tokens = await exchange(client, authorized)
    other_client_id = await register(client)

    for token in (tokens["access_token"], tokens["refresh_token"]):
        assert (await revoke(client, other_client_id, token)).status_code == 200

    assert await resolve_access_token(db_session, tokens["access_token"]) is not None
    assert (await refresh_row(db_session, tokens["refresh_token"])).revoked_at is None


async def test_resolve_unknown_and_expired_tokens(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    authorized = await authorize(client)
    tokens = await exchange(client, authorized)

    assert await resolve_access_token(db_session, "unknown") is None
    assert await resolve_access_token(db_session, "") is None
    # The stored hash is not a token.
    assert await resolve_access_token(db_session, hash_token(tokens["access_token"])) is None

    row = await access_row(db_session, tokens["access_token"])
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()
    assert await resolve_access_token(db_session, tokens["access_token"]) is None


async def test_resolve_after_the_agent_was_deleted(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    authorized = await authorize(client)
    tokens = await exchange(client, authorized)

    response = await client.delete(f"/api/orgs/{authorized.org_id}/agents/{authorized.agent['id']}")
    assert response.status_code == 204, response.text

    assert await resolve_access_token(db_session, tokens["access_token"]) is None
    response = await refresh(client, authorized.client_id, tokens["refresh_token"])
    assert_oauth_error(response, "invalid_grant")


async def test_tokens_stop_working_when_the_approver_may_no_longer_authorize_the_agent(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    ada = await sign_in(client)
    org_id = ada["organizations"][0]["id"]
    agent = await create_agent(client, org_id)
    bob = await sign_in(other_client, "bob@example.com", "Bob")
    await add_member(db_session, org_id, bob["user"]["id"], MembershipRole.ADMIN)
    client_id = await register(other_client)
    code = await approve(other_client, client_id, agent["id"])
    authorized = Authorized(client_id=client_id, code=code, agent=agent, org_id=org_id)
    tokens = await exchange(other_client, authorized)
    unused_code = await approve(other_client, client_id, agent["id"])
    assert await resolve_access_token(db_session, tokens["access_token"]) is not None

    membership = (
        await db_session.execute(
            select(Membership).where(
                Membership.organization_id == uuid.UUID(org_id),
                Membership.user_id == uuid.UUID(bob["user"]["id"]),
            )
        )
    ).scalar_one()
    membership.role = MembershipRole.MEMBER
    await db_session.flush()

    assert await resolve_access_token(db_session, tokens["access_token"]) is None
    response = await refresh(other_client, client_id, tokens["refresh_token"])
    assert_oauth_error(response, "invalid_grant")
    response = await other_client.post("/token", data=code_form(authorized, code=unused_code))
    assert_oauth_error(response, "invalid_grant")

    # The approval counts again when the role comes back.
    membership.role = MembershipRole.ADMIN
    await db_session.flush()
    assert await resolve_access_token(db_session, tokens["access_token"]) is not None
