"""The complete agent onboarding, end to end: an MCP client that knows only the /mcp URL
discovers the authorization server, registers, sends the user to the browser, and works as
the agent the user picked, through a refresh, until its tokens are revoked.

The client side is the mcp SDK's own (`OAuthClientProvider` and `Client`); the test only plays
the parts a person and their browser play. Everything runs on the ASGI app in process.
"""

import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, parse_qsl, urlsplit

import httpx2
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from mcp import Client
from mcp.client.auth import OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import (
    AuthorizationCodeResult,
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthToken,
)
from pydantic import AnyUrl
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers import sign_in
from tests.test_mcp import (
    INITIALIZE,
    MCP_HEADERS,
    MCP_URL,
    assert_challenge,
    make_list,
    mcp_http,
    running,
)
from tests.test_mcp_read_tools import call
from tests.test_oauth_authorize import ISSUER, create_agent
from tests.test_oauth_token import access_row

REDIRECT_URI = "http://127.0.0.1:33418/callback"
EMAIL = "ada@example.com"


class MemoryStorage:
    """Where the MCP client keeps its registration and tokens (the SDK's `TokenStorage`)."""

    def __init__(self) -> None:
        self.tokens: OAuthToken | None = None
        self.client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self.client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client_info = client_info


class AccessDeniedError(Exception):
    """What the MCP client makes of an authorization response without a code."""


@dataclass
class Browser:
    """The person at the keyboard: the MCP client opens the authorization URL in their browser
    (`open`), and reads the answer from the redirect to its loopback address (`callback`)."""

    client: AsyncClient
    agent_id: str
    approve: bool = True
    opened: list[dict[str, str]] = field(default_factory=list[dict[str, str]])
    consent: dict[str, Any] = field(default_factory=dict[str, Any])
    answer: dict[str, str] = field(default_factory=dict[str, str])

    async def open(self, authorization_url: str) -> None:
        url = urlsplit(authorization_url)
        assert f"{url.scheme}://{url.netloc}" == ISSUER
        assert url.path == "/authorize"
        self.opened.append(dict(parse_qsl(url.query)))

        response = await self.client.get(f"{url.path}?{url.query}")
        assert response.status_code == 302, response.text
        location = urlsplit(response.headers["location"])
        if location.path == "/login":
            # Nobody is signed in: the login page signs in and returns to the same request.
            await sign_in(self.client, EMAIL)
            response = await self.client.get(parse_qs(location.query)["next"][0])
            assert response.status_code == 302, response.text
            location = urlsplit(response.headers["location"])
        assert location.path == "/oauth/consent"
        request_id = parse_qs(location.query)["request"][0]

        # The consent page: what is asked, and the agents to choose from.
        shown = await self.client.get(f"/api/oauth/requests/{request_id}")
        assert shown.status_code == 200, shown.text
        self.consent = shown.json()
        if self.approve:
            answered = await self.client.post(
                f"/api/oauth/requests/{request_id}/approve", json={"agent_id": self.agent_id}
            )
        else:
            answered = await self.client.post(f"/api/oauth/requests/{request_id}/deny")
        assert answered.status_code == 200, answered.text
        redirect_url = answered.json()["redirect_url"]
        assert redirect_url.startswith(f"{REDIRECT_URI}?")
        self.answer = dict(parse_qsl(urlsplit(redirect_url).query))

    async def callback(self) -> AuthorizationCodeResult:
        if "code" not in self.answer:
            raise AccessDeniedError(self.answer.get("error"))
        return AuthorizationCodeResult(
            code=self.answer["code"], state=self.answer.get("state"), iss=self.answer.get("iss")
        )


def _leaves(error: BaseException) -> list[BaseException]:
    """The exceptions inside (nested) task group errors."""
    if isinstance(error, BaseExceptionGroup):
        return [leaf for inner in error.exceptions for leaf in _leaves(inner)]
    return [error]


async def test_an_agent_is_onboarded_works_refreshes_and_is_revoked(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    # Ada has an organization with an agent, and a list that the agent may edit.
    me = await sign_in(client, EMAIL)
    org_id = me["organizations"][0]["id"]
    agent = await create_agent(client, org_id, "Claude")
    list_id = await make_list(client, org_id, "Chores", "mixed")
    shared = await client.put(
        f"/api/lists/{list_id}/grants",
        json={"principal_kind": "agent", "principal_id": agent["id"], "role": "editor"},
    )
    assert shared.status_code in (200, 201), shared.text
    # She is signed out when the MCP client sends her to the browser.
    assert (await client.post("/api/auth/logout")).status_code == 204
    assert (await client.get("/api/me")).status_code == 401

    # The MCP client: it is given the server URL and nothing else.
    browser = Browser(client, agent["id"])
    storage = MemoryStorage()
    provider = OAuthClientProvider(
        server_url=MCP_URL,
        client_metadata=OAuthClientMetadata(
            client_name="Claude Code",
            redirect_uris=[AnyUrl(REDIRECT_URI)],
            token_endpoint_auth_method="none",
        ),
        storage=storage,
        redirect_handler=browser.open,
        callback_handler=browser.callback,
    )
    requests: list[tuple[str, str, int]] = []

    async def record(response: httpx2.Response) -> None:
        requests.append((response.request.method, response.request.url.path, response.status_code))

    def token_requests() -> int:
        return requests.count(("POST", "/token", 200))

    # `http` is the MCP client's connection, with the SDK's OAuth flow on it; `plain` sends
    # single requests with the token the test chooses.
    async with running(app), mcp_http(app) as http, mcp_http(app) as plain:
        http.auth = provider
        http.event_hooks["response"].append(record)

        async with Client(streamable_http_client(MCP_URL, http_client=http)) as mcp:
            # Connecting ran the whole flow: the 401 challenge, both metadata documents,
            # registration, the browser, and the code exchange.
            assert requests[:6] == [
                ("POST", "/mcp", 401),
                ("GET", "/.well-known/oauth-protected-resource/mcp", 200),
                ("GET", "/.well-known/oauth-authorization-server", 200),
                ("POST", "/register", 201),
                ("POST", "/token", 200),
                ("POST", "/mcp", 200),
            ]
            assert storage.client_info is not None
            client_id = storage.client_info.client_id
            assert client_id
            assert storage.client_info.client_secret is None
            [asked] = browser.opened
            assert asked["client_id"] == client_id
            assert asked["redirect_uri"] == REDIRECT_URI
            assert asked["code_challenge_method"] == "S256"
            assert len(asked["code_challenge"]) == 43
            assert asked["resource"] == MCP_URL
            assert asked["scope"] == "mcp"
            assert browser.consent["client_name"] == "Claude Code"
            assert browser.consent["redirect_host"] == "127.0.0.1:33418"
            assert [choice["id"] for choice in browser.consent["agents"]] == [agent["id"]]
            assert browser.answer["iss"] == ISSUER
            first = storage.tokens
            assert first is not None
            assert first.token_type == "Bearer"
            assert first.scope == "mcp"
            assert first.refresh_token
            assert first.expires_in

            # The client is the agent Ada picked, and works on her list.
            who = await call(mcp, "whoami")
            assert who["agent_id"] == agent["id"]
            assert who["organization"]["id"] == org_id
            assert who["accessible_list_count"] == 1
            item = await call(mcp, "add_item", list_id=list_id, title="Water the plants")
            completed = await call(mcp, "complete_item", item_id=item["id"])
            assert completed["status"] == "done"
            assert token_requests() == 1

            # An hour later the access token has expired, for the server and for the client,
            # which refreshes it before its next call.
            expired = await access_row(db_session, first.access_token)
            expired.expires_at = expired.created_at
            await db_session.flush()
            provider.context.token_expiry_time = time.time() - 1
            listed = await call(mcp, "get_list", list_id=list_id, include_done=True)

            assert [entry["id"] for entry in listed["items"]] == [item["id"]]
            assert listed["items"][0]["status"] == "done"
            assert token_requests() == 2
            assert len(browser.opened) == 1  # without asking Ada again
            second = storage.tokens
            assert second is not None
            assert second.access_token != first.access_token
            assert second.refresh_token
            assert second.refresh_token != first.refresh_token
            old = await plain.post(
                "/mcp",
                json=INITIALIZE,
                headers={**MCP_HEADERS, "Authorization": f"Bearer {first.access_token}"},
            )
            assert_challenge(old)

            # The client signs out: revoking the refresh token ends the whole authorization.
            metadata = provider.context.oauth_metadata
            assert metadata is not None
            assert metadata.revocation_endpoint is not None
            revoked = await plain.post(
                str(metadata.revocation_endpoint),
                data={"token": second.refresh_token, "client_id": client_id},
            )
            assert revoked.status_code == 200, revoked.text
            rejected = await plain.post(
                "/mcp",
                json=INITIALIZE,
                headers={**MCP_HEADERS, "Authorization": f"Bearer {second.access_token}"},
            )
            assert_challenge(rejected)
            again = await plain.post(
                "/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": second.refresh_token,
                    "client_id": client_id,
                    "resource": MCP_URL,
                },
            )
            assert again.status_code == 400, again.text
            assert again.json()["error"] == "invalid_grant"

        # The client still holds the revoked tokens. Its next call is refused, so the SDK
        # starts over in the browser; this time Ada says no and the client stays out.
        browser.approve = False
        del requests[:]

        async def call_again() -> None:
            async with Client(streamable_http_client(MCP_URL, http_client=http)) as mcp:
                await mcp.call_tool("add_item", {"list_id": list_id, "title": "Not allowed"})

        with pytest.raises(ExceptionGroup) as raised:
            await call_again()
        assert any(isinstance(leaf, AccessDeniedError) for leaf in _leaves(raised.value))
        assert requests[0] == ("POST", "/mcp", 401)
        assert ("POST", "/mcp", 200) not in requests
        assert ("POST", "/token", 200) not in requests
        assert len(browser.opened) == 2
        assert browser.answer["error"] == "access_denied"

    # What Ada sees afterwards: the item, added and completed by her agent...
    items = await client.get(f"/api/lists/{list_id}/items")
    assert items.status_code == 200, items.text
    by_agent = {"kind": "agent", "id": agent["id"]}
    [seen] = items.json()
    assert seen["id"] == item["id"]
    assert seen["title"] == "Water the plants"
    assert seen["status"] == "done"
    assert seen["position"] == 1
    assert seen["created_by"] == by_agent
    assert seen["completed_by"] == by_agent
    assert seen["completed_at"] is not None

    # ... and the audit log, which names the agent for its changes and her for her own.
    log = await client.get(f"/api/lists/{list_id}/audit")
    assert log.status_code == 200, log.text
    events = log.json()["events"][::-1]  # oldest first
    assert [(event["action"], event["actor"]["kind"]) for event in events] == [
        ("list.created", "user"),
        ("list_grant.set", "user"),
        ("item.created", "agent"),
        ("item.completed", "agent"),
    ]
    for event in events[2:]:
        assert event["actor"] == {**by_agent, "name": "Claude"}
        assert event["target_kind"] == "item"
        assert event["target_id"] == item["id"]
        assert event["list_id"] == list_id
        assert event["details"]["title"] == "Water the plants"
    for event in events[:2]:
        assert event["actor"]["id"] == me["user"]["id"]
