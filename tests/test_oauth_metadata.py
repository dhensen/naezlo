"""OAuth discovery for MCP clients: the RFC 8414 and RFC 9728 metadata documents."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from mcp.client.auth.utils import (
    build_oauth_authorization_server_metadata_discovery_urls,
    build_protected_resource_metadata_discovery_urls,
    validate_metadata_issuer,
)
from mcp.shared.auth import OAuthMetadata, ProtectedResourceMetadata

from naezlo.app import create_app
from naezlo.config import Settings

AS_METADATA_URL = "/.well-known/oauth-authorization-server"
PRM_URLS = ["/.well-known/oauth-protected-resource/mcp", "/.well-known/oauth-protected-resource"]


async def test_authorization_server_metadata(client: AsyncClient) -> None:
    response = await client.get(AS_METADATA_URL)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "issuer": "http://localhost:8000",
        "authorization_endpoint": "http://localhost:8000/authorize",
        "token_endpoint": "http://localhost:8000/token",
        "registration_endpoint": "http://localhost:8000/register",
        "revocation_endpoint": "http://localhost:8000/revoke",
        "scopes_supported": ["mcp"],
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none"],
        "revocation_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"],
        "authorization_response_iss_parameter_supported": True,
    }


async def test_metadata_needs_no_session_and_may_be_cached(client: AsyncClient) -> None:
    for url in [AS_METADATA_URL, *PRM_URLS]:
        response = await client.get(url)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "public, max-age=3600"


@pytest.mark.parametrize("url", PRM_URLS)
async def test_protected_resource_metadata(client: AsyncClient, url: str) -> None:
    response = await client.get(url)

    assert response.status_code == 200
    assert response.json() == {
        "resource": "http://localhost:8000/mcp",
        "authorization_servers": ["http://localhost:8000"],
        "scopes_supported": ["mcp"],
        "bearer_methods_supported": ["header"],
        "resource_name": "Naezlo",
    }


async def test_the_sdk_client_discovers_the_authorization_server(client: AsyncClient) -> None:
    """Walk the discovery steps of the mcp SDK's client, with its own URL builders and models."""
    mcp_url = "http://localhost:8000/mcp"
    prm_urls = build_protected_resource_metadata_discovery_urls(None, mcp_url)
    assert [url.removeprefix("http://localhost:8000") for url in prm_urls] == PRM_URLS

    prm = ProtectedResourceMetadata.model_validate_json((await client.get(prm_urls[0])).content)
    assert str(prm.resource) == mcp_url
    issuer = str(prm.authorization_servers[0])

    as_urls = build_oauth_authorization_server_metadata_discovery_urls(issuer, mcp_url)
    assert as_urls[0] == "http://localhost:8000" + AS_METADATA_URL
    metadata = OAuthMetadata.model_validate_json((await client.get(as_urls[0])).content)
    # RFC 8414 3.3: the issuer in the document is the one the URL was built from, as a string.
    validate_metadata_issuer(metadata, issuer)
    assert metadata.code_challenge_methods_supported == ["S256"]
    assert str(metadata.registration_endpoint) == "http://localhost:8000/register"


async def test_urls_come_from_public_base_url(settings: Settings) -> None:
    custom = settings.model_copy(update={"public_base_url": "https://todo.example.com/"})
    app = create_app(custom)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://internal") as client:
        metadata = (await client.get(AS_METADATA_URL)).json()
        resource = (await client.get(PRM_URLS[0])).json()
    await _dispose(app)

    assert metadata["issuer"] == "https://todo.example.com"
    assert metadata["authorization_endpoint"] == "https://todo.example.com/authorize"
    assert metadata["token_endpoint"] == "https://todo.example.com/token"
    assert metadata["registration_endpoint"] == "https://todo.example.com/register"
    assert metadata["revocation_endpoint"] == "https://todo.example.com/revoke"
    assert resource["resource"] == "https://todo.example.com/mcp"
    assert resource["authorization_servers"] == ["https://todo.example.com"]


async def _dispose(app: FastAPI) -> None:
    await app.state.engine.dispose()
