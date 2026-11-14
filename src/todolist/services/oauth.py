"""The OAuth 2.1 authorization server for MCP clients: metadata and client registration.

The endpoints are hand-written (see DECISIONS.md); the `mcp` SDK supplies the wire models of
the two metadata documents, so what is served here is what the SDK's client parses.
"""

import hashlib
import secrets
import uuid
from typing import Any
from urllib.parse import urlsplit

from mcp.shared.auth import OAuthMetadata, ProtectedResourceMetadata
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from todolist.config import Settings
from todolist.errors import OAuthError
from todolist.models import OAuthClient

AUTHORIZATION_PATH = "/authorize"
TOKEN_PATH = "/token"
REGISTRATION_PATH = "/register"
REVOCATION_PATH = "/revoke"

# The one scope: use the lists as the agent that was picked on the consent screen.
MCP_SCOPE = "mcp"
GRANT_TYPES = ("authorization_code", "refresh_token")
# Registered clients are public: they have no secret and prove themselves with PKCE.
PUBLIC_CLIENT_AUTH_METHOD = "none"

MAX_REGISTRATION_BODY_BYTES = 16 * 1024
MAX_REDIRECT_URIS = 10
MAX_REDIRECT_URI_LENGTH = 2000
MAX_CLIENT_NAME_LENGTH = 200
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def new_token() -> str:
    """A fresh authorization code or token: 256 random bits, URL-safe."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """What is stored instead of a code or token. They are random, so a plain SHA-256 is enough."""
    return hashlib.sha256(token.encode()).hexdigest()


def authorization_server_metadata(settings: Settings) -> OAuthMetadata:
    """RFC 8414 metadata, served at /.well-known/oauth-authorization-server."""
    issuer = settings.oauth_issuer
    # Validated from strings on purpose: building an `AnyHttpUrl` first adds a trailing slash
    # to a URL without a path, and clients compare the issuer as a string.
    return OAuthMetadata.model_validate(
        {
            "issuer": issuer,
            "authorization_endpoint": issuer + AUTHORIZATION_PATH,
            "token_endpoint": issuer + TOKEN_PATH,
            "registration_endpoint": issuer + REGISTRATION_PATH,
            "revocation_endpoint": issuer + REVOCATION_PATH,
            "scopes_supported": [MCP_SCOPE],
            "response_types_supported": ["code"],
            "response_modes_supported": ["query"],
            "grant_types_supported": list(GRANT_TYPES),
            "token_endpoint_auth_methods_supported": [PUBLIC_CLIENT_AUTH_METHOD],
            "revocation_endpoint_auth_methods_supported": [PUBLIC_CLIENT_AUTH_METHOD],
            "code_challenge_methods_supported": ["S256"],
        }
    )


def protected_resource_metadata(settings: Settings) -> ProtectedResourceMetadata:
    """RFC 9728 metadata of the MCP endpoint: this app is its own authorization server."""
    return ProtectedResourceMetadata.model_validate(
        {
            "resource": settings.mcp_resource_url,
            "authorization_servers": [settings.oauth_issuer],
            "scopes_supported": [MCP_SCOPE],
            "resource_name": settings.app_name,
        }
    )


class _RegistrationRequest(BaseModel):
    """The RFC 7591 client metadata this server looks at; the rest is ignored."""

    model_config = ConfigDict(extra="ignore", strict=True)

    redirect_uris: list[str] = Field(min_length=1, max_length=MAX_REDIRECT_URIS)
    client_name: str | None = None
    grant_types: list[str] | None = None
    response_types: list[str] | None = None
    scope: str | None = None


def _redirect_uri_problem(uri: str) -> str | None:
    """Why `uri` cannot be a redirect URI, or None when it can: https, or http on loopback."""
    if len(uri) > MAX_REDIRECT_URI_LENGTH:
        return "is too long"
    if any(char.isspace() or not char.isprintable() for char in uri):
        return "contains whitespace or control characters"
    try:
        parts = urlsplit(uri)
        _ = parts.port  # raises for a port that is not a number
    except ValueError:
        return "is not a valid URI"
    if "#" in uri:
        return "must not have a fragment"
    if parts.username is not None or parts.password is not None:
        return "must not contain credentials"
    host = parts.hostname
    if not host:
        return "must be an absolute URI with a host"
    if parts.scheme == "https":
        return None
    if parts.scheme == "http" and host in _LOOPBACK_HOSTS:
        return None
    return "must use https, or http on localhost, 127.0.0.1 or [::1]"


def _invalid_metadata(description: str) -> OAuthError:
    return OAuthError("invalid_client_metadata", description)


def _parse_registration(body: bytes) -> _RegistrationRequest:
    if len(body) > MAX_REGISTRATION_BODY_BYTES:
        raise _invalid_metadata("The registration request is too large")
    try:
        return _RegistrationRequest.model_validate_json(body)
    except ValidationError as error:
        first = error.errors(include_url=False, include_context=False, include_input=False)[0]
        field = str(first["loc"][0]) if first["loc"] else None
        if field == "redirect_uris":
            raise OAuthError(
                "invalid_redirect_uri",
                f"redirect_uris must be a list of 1 to {MAX_REDIRECT_URIS} URIs",
            ) from None
        if field is None:
            raise _invalid_metadata("The body must be a JSON object with client metadata") from None
        raise _invalid_metadata(f"{field}: {first['msg']}") from None


async def register_client(session: AsyncSession, body: bytes) -> OAuthClient:
    """Dynamic client registration (RFC 7591) of a public client, from the raw request body.

    Raises `OAuthError` (`invalid_redirect_uri` or `invalid_client_metadata`).
    """
    request = _parse_registration(body)

    redirect_uris = list(dict.fromkeys(request.redirect_uris))
    for uri in redirect_uris:
        problem = _redirect_uri_problem(uri)
        if problem is not None:
            # Don't echo the URI: the description may end up in a log or on a screen.
            raise OAuthError("invalid_redirect_uri", f"A redirect URI {problem}")

    client_name = (request.client_name or "").strip() or None
    if client_name is not None and len(client_name) > MAX_CLIENT_NAME_LENGTH:
        raise _invalid_metadata(f"client_name is longer than {MAX_CLIENT_NAME_LENGTH} characters")

    grant_types = list(dict.fromkeys(request.grant_types or GRANT_TYPES))
    if "authorization_code" not in grant_types:
        raise _invalid_metadata("grant_types must include authorization_code")
    if not set(grant_types) <= set(GRANT_TYPES):
        raise _invalid_metadata("grant_types can only be authorization_code and refresh_token")

    if request.response_types is not None and request.response_types != ["code"]:
        raise _invalid_metadata("response_types can only be code")

    scopes = (request.scope or MCP_SCOPE).split()
    if set(scopes) != {MCP_SCOPE}:
        raise _invalid_metadata(f"scope can only be {MCP_SCOPE}")

    client = OAuthClient(
        client_id=str(uuid.uuid4()),
        client_secret_hash=None,
        redirect_uris=redirect_uris,
        client_name=client_name,
        grant_types=grant_types,
        scope=MCP_SCOPE,
    )
    session.add(client)
    await session.flush()
    return client


def client_information(client: OAuthClient) -> dict[str, Any]:
    """The RFC 7591 client information response for a registered client."""
    information: dict[str, Any] = {
        "client_id": client.client_id,
        "client_id_issued_at": int(client.created_at.timestamp()),
        "redirect_uris": client.redirect_uris,
        "grant_types": client.grant_types,
        "response_types": ["code"],
        "token_endpoint_auth_method": PUBLIC_CLIENT_AUTH_METHOD,
        "scope": client.scope,
    }
    if client.client_name is not None:
        information["client_name"] = client.client_name
    return information
