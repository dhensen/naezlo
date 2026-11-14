"""The OAuth authorization endpoint (GET /authorize) and the consent API behind the SPA page."""

import base64
import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit

from httpx import AsyncClient
from mcp.client.auth.utils import validate_authorization_response_iss
from mcp.shared.auth import OAuthMetadata
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers import add_member, sign_in
from todolist.auth import safe_next_path
from todolist.models import MembershipRole, OAuthAuthorizationCode, OAuthAuthorizationRequest
from todolist.services.oauth import hash_token

CALLBACK = "http://localhost:33418/callback"
ISSUER = "http://localhost:8000"
STATE = "st4te-with spaces&symbols="
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(b"a-code-verifier").digest()).rstrip(b"=").decode()
)


async def register(client: AsyncClient, *redirect_uris: str, name: str = "Claude Code") -> str:
    response = await client.post(
        "/register", json={"redirect_uris": list(redirect_uris or [CALLBACK]), "client_name": name}
    )
    assert response.status_code == 201, response.text
    return response.json()["client_id"]


def authorize_params(client_id: str | None, **overrides: str | None) -> dict[str, str]:
    """A valid authorization request; an override of None leaves that parameter out."""
    params: dict[str, str | None] = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": CALLBACK,
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
        "state": STATE,
        "scope": "mcp",
        "resource": f"{ISSUER}/mcp",
    }
    params.update(overrides)
    return {name: value for name, value in params.items() if value is not None}


async def create_agent(client: AsyncClient, org_id: str, name: str = "Claude") -> dict[str, Any]:
    response = await client.post(f"/api/orgs/{org_id}/agents", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


async def start(client: AsyncClient, client_id: str, **overrides: str | None) -> str:
    """Open /authorize as the signed-in user and return the id of the pending request."""
    response = await client.get("/authorize", params=authorize_params(client_id, **overrides))
    assert response.status_code == 302, response.text
    location = urlsplit(response.headers["location"])
    assert location.path == "/oauth/consent"
    assert location.netloc == ""
    return parse_qs(location.query)["request"][0]


def callback_params(redirect_url: str, callback: str = CALLBACK) -> dict[str, str]:
    """The parameters an authorization response adds to the client's redirect URI."""
    assert redirect_url.startswith(callback)
    return dict(parse_qsl(urlsplit(redirect_url).query))


async def count(session: AsyncSession, model: type[Any]) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def test_happy_path(client: AsyncClient, db_session: AsyncSession) -> None:
    me = await sign_in(client)
    agent = await create_agent(client, me["organizations"][0]["id"])
    client_id = await register(client)

    response = await client.get("/authorize", params=authorize_params(client_id))
    assert response.status_code == 302
    assert response.headers["cache-control"] == "no-store"
    request_id = parse_qs(urlsplit(response.headers["location"]).query)["request"][0]
    assert response.headers["location"] == f"/oauth/consent?request={request_id}"

    response = await client.get(f"/api/oauth/requests/{request_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    expires_at = datetime.fromisoformat(body.pop("expires_at"))
    assert timedelta(minutes=9) < expires_at - datetime.now(UTC) <= timedelta(minutes=10)
    assert body == {
        "id": request_id,
        "client_name": "Claude Code",
        "redirect_host": "localhost:33418",
        "scope": "mcp",
        "agents": [
            {
                "id": agent["id"],
                "name": "Claude",
                "description": None,
                "organization": {
                    "id": me["organizations"][0]["id"],
                    "name": me["organizations"][0]["name"],
                },
            }
        ],
    }

    response = await client.post(
        f"/api/oauth/requests/{request_id}/approve", json={"agent_id": agent["id"]}
    )
    assert response.status_code == 200, response.text
    params = callback_params(response.json()["redirect_url"])
    assert params == {"code": params["code"], "state": STATE, "iss": ISSUER}

    # The code is stored hashed and bound to everything the token request must match.
    code = (await db_session.execute(select(OAuthAuthorizationCode))).scalar_one()
    assert code.code_hash == hash_token(params["code"])
    assert code.code_hash != params["code"]
    assert code.client_id == client_id
    assert code.redirect_uri == CALLBACK
    assert code.code_challenge == CHALLENGE
    assert str(code.user_id) == me["user"]["id"]
    assert str(code.agent_id) == agent["id"]
    assert code.scope == "mcp"
    assert code.resource == f"{ISSUER}/mcp"
    assert code.used_at is None
    assert timedelta(minutes=9) < code.expires_at - datetime.now(UTC) <= timedelta(minutes=10)

    # The request is used up: it cannot be read or answered again.
    assert (await client.get(f"/api/oauth/requests/{request_id}")).status_code == 404
    again = await client.post(
        f"/api/oauth/requests/{request_id}/approve", json={"agent_id": agent["id"]}
    )
    assert again.status_code == 404
    assert again.json()["detail"] == "Authorization request not found"
    assert await count(db_session, OAuthAuthorizationCode) == 1
    assert await count(db_session, OAuthAuthorizationRequest) == 0


async def test_the_response_is_what_the_sdk_client_accepts(client: AsyncClient) -> None:
    me = await sign_in(client)
    agent = await create_agent(client, me["organizations"][0]["id"])
    request_id = await start(client, await register(client))
    response = await client.post(
        f"/api/oauth/requests/{request_id}/approve", json={"agent_id": agent["id"]}
    )
    metadata = OAuthMetadata.model_validate(
        (await client.get("/.well-known/oauth-authorization-server")).json()
    )

    assert metadata.authorization_response_iss_parameter_supported is True
    # Raises when `iss` is missing or is not the issuer of the metadata.
    validate_authorization_response_iss(
        callback_params(response.json()["redirect_url"])["iss"], metadata
    )


async def test_minimal_request_without_state_scope_and_resource(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    me = await sign_in(client)
    agent = await create_agent(client, me["organizations"][0]["id"])
    request_id = await start(client, await register(client), state=None, scope=None, resource=None)

    response = await client.post(
        f"/api/oauth/requests/{request_id}/approve", json={"agent_id": agent["id"]}
    )

    params = callback_params(response.json()["redirect_url"])
    assert set(params) == {"code", "iss"}
    code = (await db_session.execute(select(OAuthAuthorizationCode))).scalar_one()
    assert code.scope == "mcp"
    assert code.resource is None


async def test_redirect_uri_keeps_its_own_query(client: AsyncClient) -> None:
    callback = "https://app.example.com/cb?tenant=a%20b"
    await sign_in(client)
    request_id = await start(client, await register(client, callback), redirect_uri=callback)

    response = await client.post(f"/api/oauth/requests/{request_id}/deny")

    assert response.status_code == 200
    assert (await client.get(f"/api/oauth/requests/{request_id}")).json()["code"] == "not_found"
    redirect_url = response.json()["redirect_url"]
    assert redirect_url.startswith("https://app.example.com/cb?tenant=a+b&error=access_denied&")
    assert callback_params(redirect_url, "https://app.example.com/cb")["tenant"] == "a b"


async def test_missing_pkce_goes_back_to_the_client_with_an_error(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await sign_in(client)
    client_id = await register(client)

    for overrides in (
        {"code_challenge": None},
        {"code_challenge": None, "code_challenge_method": None},
        {"code_challenge_method": None},
        {"code_challenge_method": "plain"},
        {"code_challenge": "too-short"},
    ):
        response = await client.get("/authorize", params=authorize_params(client_id, **overrides))

        assert response.status_code == 302, overrides
        params = callback_params(response.headers["location"])
        assert params["error"] == "invalid_request", overrides
        assert "code_challenge" in params["error_description"]
        assert params["state"] == STATE
        assert params["iss"] == ISSUER
        assert "code" not in params
    assert await count(db_session, OAuthAuthorizationRequest) == 0


async def test_other_invalid_requests_go_back_to_the_client(client: AsyncClient) -> None:
    await sign_in(client)
    client_id = await register(client)

    for overrides, error in (
        ({"response_type": None}, "invalid_request"),
        ({"response_type": "token"}, "unsupported_response_type"),
        ({"scope": "mcp admin"}, "invalid_scope"),
        ({"resource": "https://other.example.com/mcp"}, "invalid_target"),
    ):
        response = await client.get("/authorize", params=authorize_params(client_id, **overrides))

        assert response.status_code == 302, overrides
        params = callback_params(response.headers["location"])
        assert params["error"] == error
        assert params["state"] == STATE

    # A state that cannot be used is not echoed.
    query = urlencode(authorize_params(client_id)) + "&state=second"
    response = await client.get(f"/authorize?{query}")
    params = callback_params(response.headers["location"])
    assert params["error"] == "invalid_request"
    assert "state" not in params


async def test_mismatched_redirect_uri_shows_an_error_and_does_not_redirect(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await sign_in(client)
    client_id = await register(client)

    for redirect_uri in (
        "http://localhost:33418/other",
        "http://localhost:33418/callback/",
        "http://localhost:33418/callback?x=1",
        "http://localhost:9999/callback",
        "https://evil.example.com/callback",
        None,
    ):
        response = await client.get(
            "/authorize", params=authorize_params(client_id, redirect_uri=redirect_uri)
        )

        assert response.status_code == 400, redirect_uri
        assert "location" not in response.headers
        assert response.headers["content-type"].startswith("text/html")
        assert "Authorization failed" in response.text
        assert "redirect" in response.text
    assert await count(db_session, OAuthAuthorizationRequest) == 0


async def test_unknown_client_shows_an_error_and_does_not_redirect(client: AsyncClient) -> None:
    # Also without a session: nobody is sent to the login page for a request that cannot work.
    for client_id in (str(uuid.uuid4()), None):
        response = await client.get("/authorize", params=authorize_params(client_id))

        assert response.status_code == 400
        assert "location" not in response.headers
        assert "Authorization failed" in response.text


async def test_unauthenticated_request_goes_to_the_login_page_and_back(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    client_id = await register(client)
    params = authorize_params(client_id)

    response = await client.get("/authorize", params=params)

    assert response.status_code == 302
    location = urlsplit(response.headers["location"])
    assert (location.netloc, location.path) == ("", "/login")
    next_path = parse_qs(location.query)["next"][0]
    # The login page accepts it as a place to return to, and it is the same request.
    assert safe_next_path(next_path) == next_path
    assert urlsplit(next_path).path == "/authorize"
    assert dict(parse_qsl(urlsplit(next_path).query)) == params
    assert await count(db_session, OAuthAuthorizationRequest) == 0

    # After signing in, following `next` continues on the consent page.
    await sign_in(client)
    response = await client.get(next_path)
    assert response.status_code == 302
    assert response.headers["location"].startswith("/oauth/consent?request=")


async def test_deny(client: AsyncClient, db_session: AsyncSession) -> None:
    await sign_in(client)
    request_id = await start(client, await register(client))

    response = await client.post(f"/api/oauth/requests/{request_id}/deny")

    assert response.status_code == 200, response.text
    params = callback_params(response.json()["redirect_url"])
    assert params["error"] == "access_denied"
    assert params["state"] == STATE
    assert params["iss"] == ISSUER
    assert "code" not in params
    assert await count(db_session, OAuthAuthorizationCode) == 0
    assert await count(db_session, OAuthAuthorizationRequest) == 0
    assert (await client.post(f"/api/oauth/requests/{request_id}/deny")).status_code == 404


async def test_forbidden_agent(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    me = await sign_in(client)
    other = await sign_in(other_client, "grace@example.com", "Grace")
    other_org_id = other["organizations"][0]["id"]
    foreign_agent = await create_agent(other_client, other_org_id, "Foreign")
    request_id = await start(client, await register(client))
    approve_url = f"/api/oauth/requests/{request_id}/approve"

    # An agent of an organization the user is not in.
    response = await client.post(approve_url, json={"agent_id": foreign_agent["id"]})
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "forbidden"

    # Still 403 as a plain member of that organization.
    await add_member(db_session, other_org_id, me["user"]["id"], MembershipRole.MEMBER)
    response = await client.post(approve_url, json={"agent_id": foreign_agent["id"]})
    assert response.status_code == 403
    listed = (await client.get(f"/api/oauth/requests/{request_id}")).json()["agents"]
    assert listed == []

    # An agent id that does not exist gets the same answer.
    response = await client.post(approve_url, json={"agent_id": str(uuid.uuid4())})
    assert response.status_code == 403
    assert await count(db_session, OAuthAuthorizationCode) == 0

    # The request is still pending: the user can pick an agent they do administer.
    own_agent = await create_agent(client, me["organizations"][0]["id"], "Own")
    response = await client.post(approve_url, json={"agent_id": own_agent["id"]})
    assert response.status_code == 200, response.text


async def test_agents_come_from_every_organization_the_user_administers(
    client: AsyncClient,
    other_client: AsyncClient,
    third_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    me = await sign_in(client)
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    linus = await sign_in(third_client, "linus@example.com", "Linus")
    own_org, admin_org, member_org = (body["organizations"][0]["id"] for body in (me, grace, linus))
    own = await create_agent(client, own_org, "Own")
    administered = await create_agent(other_client, admin_org, "Administered")
    await create_agent(third_client, member_org, "Hidden")
    await add_member(db_session, admin_org, me["user"]["id"], MembershipRole.ADMIN)
    await add_member(db_session, member_org, me["user"]["id"], MembershipRole.MEMBER)
    request_id = await start(client, await register(client))

    body = (await client.get(f"/api/oauth/requests/{request_id}")).json()

    assert [(agent["id"], agent["organization"]["id"]) for agent in body["agents"]] == [
        (own["id"], own_org),
        (administered["id"], admin_org),
    ]
    response = await client.post(
        f"/api/oauth/requests/{request_id}/approve", json={"agent_id": administered["id"]}
    )
    assert response.status_code == 200


async def test_a_request_belongs_to_the_user_who_started_it(
    client: AsyncClient, other_client: AsyncClient, third_client: AsyncClient
) -> None:
    await sign_in(client)
    other = await sign_in(other_client, "grace@example.com", "Grace")
    agent = await create_agent(other_client, other["organizations"][0]["id"])
    request_id = await start(client, await register(client))
    url = f"/api/oauth/requests/{request_id}"

    for response in (
        await other_client.get(url),
        await other_client.post(f"{url}/approve", json={"agent_id": agent["id"]}),
        await other_client.post(f"{url}/deny"),
    ):
        assert response.status_code == 404
        assert response.json()["detail"] == "Authorization request not found"
    # Not signed in.
    assert (await third_client.get(url)).status_code == 401
    assert (await third_client.post(f"{url}/deny")).status_code == 401
    assert (await client.get(url)).status_code == 200


async def test_an_expired_request_is_gone(client: AsyncClient, db_session: AsyncSession) -> None:
    me = await sign_in(client)
    agent = await create_agent(client, me["organizations"][0]["id"])
    client_id = await register(client)
    request_id = await start(client, client_id)
    await db_session.execute(
        update(OAuthAuthorizationRequest).values(
            expires_at=datetime.now(UTC) - timedelta(seconds=1)
        )
    )
    url = f"/api/oauth/requests/{request_id}"

    assert (await client.get(url)).status_code == 404
    assert (await client.post(f"{url}/approve", json={"agent_id": agent["id"]})).status_code == 404
    assert (await client.post(f"{url}/deny")).status_code == 404
    assert await count(db_session, OAuthAuthorizationCode) == 0

    # The next authorization request clears it away.
    new_request_id = await start(client, client_id)
    remaining = (await db_session.execute(select(OAuthAuthorizationRequest.id))).scalars().all()
    assert [str(id) for id in remaining] == [new_request_id]
