"""The MCP endpoint (/mcp): bearer authentication and the `whoami` tool.

The SDK's client talks to the ASGI app in process; nothing goes over the network.
"""

import json
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, Literal

import httpx2
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from mcp import Client, MCPError
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_oauth_authorize import ISSUER
from tests.test_oauth_token import Authorized, access_row, authorize, exchange, revoke
from todolist.models import ListGrant, ListRole, PrincipalKind

MCP_URL = f"{ISSUER}/mcp"
METADATA_URL = f"{ISSUER}/.well-known/oauth-protected-resource/mcp"
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    },
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


@asynccontextmanager
async def running(app: FastAPI) -> AsyncGenerator[None]:
    """Run the app's lifespan, which starts the MCP session manager. Enter it in the test
    itself, not in a fixture: it must start and stop in the same task."""
    async with app.router.lifespan_context(app):
        yield


def mcp_http(app: FastAPI, token: str | None = None) -> httpx2.AsyncClient:
    """The HTTP client an MCP client uses, on the app's public address."""
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    return httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url=ISSUER, headers=headers
    )


@asynccontextmanager
async def mcp_client(
    app: FastAPI, token: str | None, mode: Literal["auto", "legacy"] = "auto"
) -> AsyncGenerator[Client]:
    """The SDK's client, connected to the running app with `token` as its bearer token."""
    async with (
        running(app),
        mcp_http(app, token) as http,
        Client(streamable_http_client(MCP_URL, http_client=http), mode=mode) as mcp,
    ):
        yield mcp


async def agent_token(client: AsyncClient) -> tuple[Authorized, str]:
    """Ada's organization with an agent and an access token that acts as it."""
    authorized = await authorize(client)
    return authorized, (await exchange(client, authorized))["access_token"]


async def whoami(mcp: Client) -> dict[str, Any]:
    result = await mcp.call_tool("whoami")
    assert not result.is_error, result.content
    assert result.structured_content is not None
    return result.structured_content


async def make_list(client: AsyncClient, org_id: str, name: str, mode: str) -> str:
    project = await client.post(f"/api/orgs/{org_id}/projects", json={"name": f"{name} project"})
    assert project.status_code == 201, project.text
    created = await client.post(
        f"/api/projects/{project.json()['id']}/lists", json={"name": name, "mode": mode}
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def grant_agent(session: AsyncSession, list_id: str, agent_id: str, role: ListRole) -> None:
    session.add(
        ListGrant(
            list_id=uuid.UUID(list_id),
            principal_kind=PrincipalKind.AGENT,
            agent_id=uuid.UUID(agent_id),
            role=role,
        )
    )
    await session.flush()


def assert_challenge(response: httpx2.Response) -> None:
    """401 with the challenge that tells an MCP client where to find the authorization server."""
    assert response.status_code == 401, response.text
    challenge = response.headers["www-authenticate"]
    assert challenge.startswith("Bearer ")
    assert f'resource_metadata="{METADATA_URL}"' in challenge
    assert 'error="invalid_token"' in challenge


async def test_without_a_token_the_endpoint_answers_401_with_the_metadata_url(
    app: FastAPI, client: AsyncClient
) -> None:
    async with running(app), mcp_http(app) as http:
        for response in (
            await http.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS),
            await http.get("/mcp", headers=MCP_HEADERS),
            await http.delete("/mcp"),
        ):
            assert_challenge(response)

    # The URL in the challenge is served by this app and names it as authorization server.
    metadata = await client.get(METADATA_URL.removeprefix(ISSUER))
    assert metadata.status_code == 200
    assert metadata.json()["resource"] == MCP_URL
    assert metadata.json()["authorization_servers"] == [ISSUER]


@pytest.mark.parametrize(
    "authorization",
    ["Bearer not-a-token", "Bearer ", "Basic dXNlcjpwYXNz", "not-a-token", "Bearer a\x00b"],
)
async def test_a_wrong_authorization_header_is_401(app: FastAPI, authorization: str) -> None:
    async with running(app), mcp_http(app) as http:
        response = await http.post(
            "/mcp", json=INITIALIZE, headers={**MCP_HEADERS, "Authorization": authorization}
        )

    assert_challenge(response)


async def test_the_sdk_client_is_rejected_without_a_token(app: FastAPI) -> None:
    statuses: list[int] = []

    async def record(response: httpx2.Response) -> None:
        statuses.append(response.status_code)

    async def connect() -> None:
        async with running(app), mcp_http(app) as http:
            http.event_hooks["response"].append(record)
            async with Client(streamable_http_client(MCP_URL, http_client=http)) as mcp:
                await mcp.call_tool("whoami")

    with pytest.raises(ExceptionGroup) as raised:
        await connect()

    assert isinstance(_leaf(raised.value), MCPError)
    assert statuses
    assert set(statuses) == {401}


def _leaf(error: BaseException) -> BaseException:
    """The one exception inside nested task group errors."""
    while isinstance(error, BaseExceptionGroup):
        [error] = error.exceptions
    return error


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_whoami_returns_the_agent_of_the_token(
    app: FastAPI, client: AsyncClient, mode: Literal["auto", "legacy"]
) -> None:
    authorized, token = await agent_token(client)
    organization = (await client.get("/api/me")).json()["organizations"][0]

    async with mcp_client(app, token, mode) as mcp:
        tools = await mcp.list_tools()
        result = await mcp.call_tool("whoami")

    assert [tool.name for tool in tools.tools] == ["whoami"]
    assert not result.is_error, result.content
    expected = {
        "agent_id": authorized.agent["id"],
        "name": authorized.agent["name"],
        "organization": {
            "id": organization["id"],
            "name": organization["name"],
            "slug": organization["slug"],
        },
        "accessible_list_count": 0,
    }
    assert result.structured_content == expected
    # Clients that only read the text content get the same answer.
    [content] = result.content
    assert content.type == "text"
    assert json.loads(content.text) == expected


async def test_whoami_counts_the_lists_the_agent_can_access(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    authorized, token = await agent_token(client)
    agent_id = authorized.agent["id"]
    # Counted: a list grant, and a role on the project of a list.
    await grant_agent(
        db_session,
        await make_list(client, authorized.org_id, "Mixed", "mixed"),
        agent_id,
        ListRole.VIEWER,
    )
    by_project = await make_list(client, authorized.org_id, "AI", "ai_only")
    project_id = (await client.get(f"/api/lists/{by_project}")).json()["project_id"]
    shared = await client.put(
        f"/api/projects/{project_id}/grants",
        json={"principal_kind": "agent", "principal_id": agent_id, "role": "editor"},
    )
    assert shared.status_code in (200, 201), shared.text
    # Not counted: human-only whatever the grant, a `none` grant, and no grant at all.
    await grant_agent(
        db_session,
        await make_list(client, authorized.org_id, "People", "human_only"),
        agent_id,
        ListRole.ADMIN,
    )
    closed = await client.post(
        f"/api/projects/{project_id}/lists", json={"name": "Closed", "mode": "mixed"}
    )
    await grant_agent(db_session, closed.json()["id"], agent_id, ListRole.NONE)
    await make_list(client, authorized.org_id, "Unshared", "mixed")

    async with mcp_client(app, token) as mcp:
        assert (await whoami(mcp))["accessible_list_count"] == 2


async def test_a_revoked_token_stops_working(app: FastAPI, client: AsyncClient) -> None:
    authorized, token = await agent_token(client)

    async with running(app), mcp_http(app, token) as http:
        before = await http.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)
        assert (await revoke(client, authorized.client_id, token)).status_code == 200
        after = await http.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)

    assert before.status_code == 200, before.text
    assert_challenge(after)


async def test_an_expired_token_is_401(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    _, token = await agent_token(client)
    row = await access_row(db_session, token)
    row.expires_at = row.created_at
    await db_session.flush()

    async with running(app), mcp_http(app, token) as http:
        response = await http.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)

    assert_challenge(response)


async def test_the_session_cookie_of_a_user_is_not_a_login(
    app: FastAPI, client: AsyncClient
) -> None:
    await agent_token(client)  # signs Ada in on `client`

    async with running(app):
        response = await client.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)

    assert response.status_code == 401


async def test_only_requests_for_the_public_host_are_answered(
    app: FastAPI, client: AsyncClient
) -> None:
    _, token = await agent_token(client)

    async with running(app), mcp_http(app, token) as http:
        response = await http.post(
            "/mcp", json=INITIALIZE, headers={**MCP_HEADERS, "Host": "evil.example"}
        )

    assert response.status_code == 421


async def test_the_lifespan_starts_and_stops_the_mcp_server(
    app: FastAPI, client: AsyncClient
) -> None:
    _, token = await agent_token(client)

    async with mcp_http(app, token) as http:
        async with running(app):
            started = await http.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)
        # Not running: the SDK refuses to handle the request.
        with pytest.raises(RuntimeError, match="Task group is not initialized"):
            await http.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)

    assert started.status_code == 200, started.text
    assert started.json()["result"]["serverInfo"]["name"] == app.state.settings.app_name
