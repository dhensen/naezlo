"""Dynamic client registration (RFC 7591) and the OAuth tables."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata
from pydantic import AnyUrl
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers import add_in_savepoint, sign_in
from todolist.models import (
    Agent,
    OAuthAccessToken,
    OAuthAuthorizationCode,
    OAuthClient,
    OAuthRefreshToken,
)
from todolist.services.oauth import hash_token, new_token

CALLBACK = "http://localhost:33418/callback"


async def register(client: AsyncClient, **metadata: Any) -> Any:
    return await client.post("/register", json={"redirect_uris": [CALLBACK], **metadata})


async def client_count(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(OAuthClient))).scalar_one()


async def test_register_a_public_client(client: AsyncClient, db_session: AsyncSession) -> None:
    response = await register(
        client,
        redirect_uris=[CALLBACK, "https://app.example.com/oauth/callback"],
        client_name="  Claude Code  ",
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
    )

    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert uuid.UUID(body["client_id"])
    assert isinstance(body.pop("client_id_issued_at"), int)
    assert body == {
        "client_id": body["client_id"],
        "client_name": "Claude Code",
        "redirect_uris": [CALLBACK, "https://app.example.com/oauth/callback"],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": "mcp",
    }
    assert "client_secret" not in body

    stored = await db_session.get(OAuthClient, body["client_id"])
    assert stored is not None
    assert stored.client_secret_hash is None
    assert stored.client_name == "Claude Code"
    assert stored.redirect_uris == [CALLBACK, "https://app.example.com/oauth/callback"]
    assert stored.grant_types == ["authorization_code", "refresh_token"]
    assert stored.scope == "mcp"


async def test_registration_needs_no_session_and_has_defaults(client: AsyncClient) -> None:
    response = await client.post("/register", json={"redirect_uris": [CALLBACK]})

    assert response.status_code == 201
    body = response.json()
    assert "client_name" not in body
    assert body["grant_types"] == ["authorization_code", "refresh_token"]
    assert body["token_endpoint_auth_method"] == "none"
    assert body["scope"] == "mcp"


async def test_every_registration_gets_its_own_client_id(client: AsyncClient) -> None:
    first = (await register(client)).json()
    second = (await register(client)).json()

    assert first["client_id"] != second["client_id"]


async def test_the_sdk_client_can_register(client: AsyncClient) -> None:
    """The request the mcp SDK's client sends, and its parser on the answer."""
    metadata = OAuthClientMetadata(
        redirect_uris=[AnyUrl("http://127.0.0.1:3030/callback")],
        client_name="SDK client",
        scope="mcp",
    )

    response = await client.post(
        "/register", json=metadata.model_dump(by_alias=True, mode="json", exclude_none=True)
    )

    assert response.status_code == 201, response.text
    information = OAuthClientInformationFull.model_validate(response.json())
    assert information.client_secret is None
    assert information.token_endpoint_auth_method == "none"
    assert information.redirect_uris == [AnyUrl("http://127.0.0.1:3030/callback")]


async def test_a_client_that_asks_for_a_secret_is_registered_as_public(client: AsyncClient) -> None:
    response = await register(client, token_endpoint_auth_method="client_secret_post")

    assert response.status_code == 201
    assert response.json()["token_endpoint_auth_method"] == "none"
    assert "client_secret" not in response.json()


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "http://localhost/callback",
        "http://localhost:8080/callback",
        "http://127.0.0.1:51234/cb",
        "http://[::1]:9000/cb",
        "https://example.com/callback?source=mcp",
        "https://example.com",
    ],
)
async def test_https_and_loopback_http_redirect_uris(
    client: AsyncClient, redirect_uri: str
) -> None:
    response = await register(client, redirect_uris=[redirect_uri])

    assert response.status_code == 201, response.text
    assert response.json()["redirect_uris"] == [redirect_uri]


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "http://example.com/callback",
        "http://localhost.example.com/callback",
        "http://127.0.0.1.example.com/callback",
        "http://192.168.1.10/callback",
        "http://user@localhost/callback",
        "https://user:secret@example.com/callback",
        "https://example.com/callback#fragment",
        "https://example.com/call back",
        "https://example.com:port/callback",
        "https:///callback",
        "https:example.com",
        "//example.com/callback",
        "/callback",
        "myapp://callback",
        "javascript:alert(1)",
        "",
        "https://example.com/" + "a" * 2000,
    ],
)
async def test_invalid_redirect_uri(
    client: AsyncClient, db_session: AsyncSession, redirect_uri: str
) -> None:
    response = await register(client, redirect_uris=[CALLBACK, redirect_uri])

    assert response.status_code == 400
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["error"] == "invalid_redirect_uri"
    assert body["error_description"]
    assert set(body) == {"error", "error_description"}
    assert await client_count(db_session) == 0


@pytest.mark.parametrize(
    "redirect_uris",
    [None, [], "http://localhost/callback", [1], [None], [f"https://e.com/{n}" for n in range(11)]],
)
async def test_redirect_uris_must_be_a_list_of_uris(
    client: AsyncClient, redirect_uris: Any
) -> None:
    response = await client.post("/register", json={"redirect_uris": redirect_uris})

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"


async def test_redirect_uris_are_required(client: AsyncClient) -> None:
    response = await client.post("/register", json={"client_name": "No callback"})

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"


@pytest.mark.parametrize(
    "metadata",
    [
        {"grant_types": ["refresh_token"]},
        {"grant_types": ["authorization_code", "client_credentials"]},
        {"grant_types": ["authorization_code", "urn:ietf:params:oauth:grant-type:jwt-bearer"]},
        {"grant_types": "authorization_code"},
        {"response_types": ["token"]},
        {"response_types": ["code", "token"]},
        {"scope": "admin"},
        {"scope": "mcp admin"},
        {"scope": 5},
        {"client_name": "x" * 201},
        {"client_name": ["Claude"]},
    ],
)
async def test_invalid_client_metadata(
    client: AsyncClient, db_session: AsyncSession, metadata: dict[str, Any]
) -> None:
    response = await register(client, **metadata)

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "invalid_client_metadata"
    assert body["error_description"]
    assert await client_count(db_session) == 0


@pytest.mark.parametrize("body", [b"", b"not json", b"[]", b'"text"', b"null"])
async def test_body_must_be_a_json_object(client: AsyncClient, body: bytes) -> None:
    response = await client.post(
        "/register", content=body, headers={"content-type": "application/json"}
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client_metadata"


async def test_oversized_body_is_refused(client: AsyncClient) -> None:
    body = json.dumps({"redirect_uris": [CALLBACK], "client_uri": "https://e.com/" + "a" * 20000})

    response = await client.post("/register", content=body)

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client_metadata"


async def test_null_placeholders_and_unknown_fields_are_ignored(client: AsyncClient) -> None:
    response = await register(
        client,
        client_name=None,
        grant_types=None,
        response_types=None,
        scope=None,
        logo_uri="https://example.com/logo.png",
        application_type="native",
        software_id="abc",
    )

    assert response.status_code == 201
    assert "logo_uri" not in response.json()


async def test_duplicate_redirect_uris_are_stored_once(client: AsyncClient) -> None:
    response = await register(client, redirect_uris=[CALLBACK, CALLBACK])

    assert response.json()["redirect_uris"] == [CALLBACK]


def test_tokens_are_random_and_hashed() -> None:
    token = new_token()

    assert token != new_token()
    assert len(token) >= 43
    digest = hash_token(token)
    assert len(digest) == 64
    assert digest == hash_token(token)
    assert token not in digest


async def test_codes_and_tokens_are_stored_hashed_for_an_agent(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    me = await sign_in(client)
    org_id = me["organizations"][0]["id"]
    agent_id = (await client.post(f"/api/orgs/{org_id}/agents", json={"name": "Claude"})).json()[
        "id"
    ]
    client_id = (await register(client)).json()["client_id"]
    grant: dict[str, Any] = {
        "client_id": client_id,
        "user_id": uuid.UUID(me["user"]["id"]),
        "agent_id": uuid.UUID(agent_id),
        "scope": "mcp",
        "resource": "http://localhost:8000/mcp",
        "expires_at": datetime.now(UTC) + timedelta(minutes=10),
    }
    code = OAuthAuthorizationCode(
        code_hash=hash_token("code"),
        redirect_uri=CALLBACK,
        code_challenge="E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        **grant,
    )
    db_session.add(code)
    await db_session.flush()
    access = OAuthAccessToken(
        token_hash=hash_token("access"), authorization_code_id=code.id, **grant
    )
    refresh = OAuthRefreshToken(
        token_hash=hash_token("refresh"), authorization_code_id=code.id, **grant
    )
    db_session.add_all([access, refresh])
    await db_session.flush()

    assert code.used_at is None
    assert access.revoked_at is None
    assert refresh.revoked_at is None

    # A token hash is unique.
    with pytest.raises(IntegrityError):
        await add_in_savepoint(
            db_session, OAuthAccessToken(token_hash=hash_token("access"), **grant)
        )

    # Deleting the agent takes its codes and tokens along.
    agent = await db_session.get(Agent, uuid.UUID(agent_id))
    await db_session.delete(agent)
    await db_session.flush()
    for model in (OAuthAuthorizationCode, OAuthAccessToken, OAuthRefreshToken):
        count = (await db_session.execute(select(func.count()).select_from(model))).scalar_one()
        assert count == 0
