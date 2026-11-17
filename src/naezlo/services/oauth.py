"""The OAuth 2.1 authorization server for MCP clients: metadata, client registration, the
authorization request and the user's answer to it on the consent screen.

The endpoints are hand-written (see DECISIONS.md); the `mcp` SDK supplies the wire models of
the two metadata documents, so what is served here is what the SDK's client parses.
"""

import hashlib
import re
import secrets
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from mcp.shared.auth import OAuthMetadata, ProtectedResourceMetadata
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from naezlo.config import Settings
from naezlo.errors import ForbiddenError, NotFoundError, OAuthError
from naezlo.models import (
    Agent,
    OAuthAuthorizationCode,
    OAuthAuthorizationRequest,
    OAuthClient,
    Organization,
    User,
)
from naezlo.permissions import authorizable_agents, can_authorize_agent
from naezlo.principals import Principal

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

# How long the consent screen may stay open, and how long the client has to exchange the code.
AUTHORIZATION_REQUEST_LIFETIME = timedelta(minutes=10)
AUTHORIZATION_CODE_LIFETIME = timedelta(minutes=10)
MAX_STATE_LENGTH = 2000
# RFC 7636: 43 to 128 unreserved characters (an S256 challenge is exactly 43).
_CODE_CHALLENGE = re.compile(r"[A-Za-z0-9\-._~]{43,128}")
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def new_token() -> str:
    """A fresh authorization code or token: 256 random bits, URL-safe."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """What is stored instead of a code or token. They are random, so a plain SHA-256 is enough."""
    return hashlib.sha256(token.encode()).hexdigest()


async def find_client(session: AsyncSession, client_id: str) -> OAuthClient | None:
    """The registered client with this id. The id comes straight from a request."""
    # PostgreSQL refuses a NUL byte in a text parameter; no client id has one.
    if "\x00" in client_id:
        return None
    return await session.get(OAuthClient, client_id)


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
            # RFC 9207: every authorization response carries `iss`.
            "authorization_response_iss_parameter_supported": True,
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


class AuthorizationPageError(Exception):
    """An authorization request whose client or redirect URI cannot be trusted. The browser
    must not be sent anywhere: the person sees this message instead (RFC 6749 4.1.2.1)."""

    def __init__(self, description: str) -> None:
        super().__init__(description)
        self.description = description


class AuthorizationRedirectError(Exception):
    """An invalid authorization request from a known client with a registered redirect URI:
    the error goes back to the client through `redirect_url`."""

    def __init__(self, redirect_url: str) -> None:
        super().__init__("Invalid authorization request")
        self.redirect_url = redirect_url


@dataclass(frozen=True)
class ValidatedAuthorization:
    """The parameters of an /authorize request that passed every check."""

    client: OAuthClient
    redirect_uri: str
    code_challenge: str
    state: str | None
    scope: str
    resource: str | None


def authorization_response_url(
    settings: Settings, redirect_uri: str, state: str | None, **parameters: str
) -> str:
    """`redirect_uri` with the authorization response added to its query: `parameters` (the
    code, or the error), the client's `state` when it sent one, and `iss` (RFC 9207)."""
    response = dict(parameters)
    if state is not None:
        response["state"] = state
    response["iss"] = settings.oauth_issuer
    parts = urlsplit(redirect_uri)
    query = parse_qsl(parts.query, keep_blank_values=True) + list(response.items())
    return urlunsplit(parts._replace(query=urlencode(query)))


async def validate_authorization_request(
    session: AsyncSession, settings: Settings, parameters: Sequence[tuple[str, str]]
) -> ValidatedAuthorization:
    """Check the query parameters of GET /authorize (OAuth 2.1 with PKCE, RFC 8707 resource).

    Raises `AuthorizationPageError` while the client and the redirect URI are not established,
    and `AuthorizationRedirectError` for every problem after that.
    """
    values: dict[str, list[str]] = {}
    for name, value in parameters:
        values.setdefault(name, []).append(value)

    def single(name: str) -> str | None:
        """The parameter's value; None when it is absent or empty."""
        found = values.get(name, [])
        return found[0] if len(found) == 1 and found[0] else None

    def repeated(name: str) -> bool:
        return len(values.get(name, [])) > 1

    client_id = single("client_id")
    if client_id is None:
        raise AuthorizationPageError("The request has no client_id, or more than one.")
    client = await find_client(session, client_id)
    if client is None:
        raise AuthorizationPageError("This application is not registered here.")
    redirect_uri = single("redirect_uri")
    if redirect_uri is None:
        raise AuthorizationPageError("The request has no redirect_uri, or more than one.")
    # Exact string comparison with what the client registered: no normalization, no prefixes.
    if redirect_uri not in client.redirect_uris:
        raise AuthorizationPageError(
            "The redirect URI of the request is not one this application registered."
        )

    state = single("state")
    state_is_usable = not repeated("state") and (state is None or len(state) <= MAX_STATE_LENGTH)

    def error(code: str, description: str) -> AuthorizationRedirectError:
        return AuthorizationRedirectError(
            authorization_response_url(
                settings,
                redirect_uri,
                state if state_is_usable else None,
                error=code,
                error_description=description,
            )
        )

    if not state_is_usable:
        raise error("invalid_request", f"state must be one value of at most {MAX_STATE_LENGTH}")
    for name in ("response_type", "code_challenge", "code_challenge_method", "scope", "resource"):
        if repeated(name):
            raise error("invalid_request", f"{name} is given more than once")

    response_type = single("response_type")
    if response_type is None:
        raise error("invalid_request", "response_type is required")
    if response_type != "code":
        raise error("unsupported_response_type", "response_type must be code")

    code_challenge = single("code_challenge")
    if code_challenge is None:
        raise error("invalid_request", "code_challenge is required (PKCE)")
    # Without a method the challenge would be `plain`, which is not accepted.
    if single("code_challenge_method") != "S256":
        raise error("invalid_request", "code_challenge_method must be S256")
    if _CODE_CHALLENGE.fullmatch(code_challenge) is None:
        raise error("invalid_request", "code_challenge is not a valid S256 challenge")

    scope = single("scope")
    if scope is not None and set(scope.split()) != {MCP_SCOPE}:
        raise error("invalid_scope", f"scope can only be {MCP_SCOPE}")

    resource = single("resource")
    if resource is not None and resource.rstrip("/") != settings.mcp_resource_url:
        raise error("invalid_target", f"resource must be {settings.mcp_resource_url}")

    return ValidatedAuthorization(
        client=client,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        state=state,
        scope=MCP_SCOPE,
        resource=None if resource is None else settings.mcp_resource_url,
    )


async def create_authorization_request(
    session: AsyncSession, validated: ValidatedAuthorization, user: User
) -> OAuthAuthorizationRequest:
    """Store a validated request until `user` answers it on the consent screen."""
    now = datetime.now(UTC)
    # Housekeeping: requests nobody answered in time.
    await session.execute(
        delete(OAuthAuthorizationRequest).where(OAuthAuthorizationRequest.expires_at <= now)
    )
    pending = OAuthAuthorizationRequest(
        client_id=validated.client.client_id,
        user_id=user.id,
        redirect_uri=validated.redirect_uri,
        code_challenge=validated.code_challenge,
        state=validated.state,
        scope=validated.scope,
        resource=validated.resource,
        expires_at=now + AUTHORIZATION_REQUEST_LIFETIME,
    )
    session.add(pending)
    await session.flush()
    return pending


async def get_authorization_request(
    session: AsyncSession, request_id: uuid.UUID, user: User, *, for_update: bool = False
) -> tuple[OAuthAuthorizationRequest, OAuthClient]:
    """The pending request `user` started, with its client; 404 when there is none (also for
    someone else's request, an answered one and an expired one).

    `for_update` locks the request, so that it can be answered only once.
    """
    query = (
        select(OAuthAuthorizationRequest, OAuthClient)
        .join(OAuthClient, OAuthClient.client_id == OAuthAuthorizationRequest.client_id)
        .where(
            OAuthAuthorizationRequest.id == request_id,
            OAuthAuthorizationRequest.user_id == user.id,
            OAuthAuthorizationRequest.expires_at > datetime.now(UTC),
        )
    )
    if for_update:
        query = query.with_for_update(of=OAuthAuthorizationRequest)
    row = (await session.execute(query)).one_or_none()
    if row is None:
        raise NotFoundError("Authorization request not found")
    return row[0], row[1]


async def list_authorizable_agents(
    session: AsyncSession, user: User
) -> list[tuple[Agent, Organization]]:
    """The agents `user` may pick on the consent screen, with their organization."""
    rows = await session.execute(authorizable_agents(user.id))
    return [(agent, organization) for agent, organization in rows]


async def approve_authorization_request(
    session: AsyncSession,
    settings: Settings,
    request_id: uuid.UUID,
    user: User,
    agent_id: uuid.UUID,
) -> str:
    """Let the client act as the agent: issue a single-use authorization code and return the
    URL that brings the browser back to the client with it.

    The request is used up. Raises 404 for a request that is not pending and 403 for an agent
    the user may not authorize (one answer, whether or not that agent exists).
    """
    pending, _client = await get_authorization_request(session, request_id, user, for_update=True)
    agent = await session.get(Agent, agent_id)
    if agent is None or not await can_authorize_agent(
        session, Principal.for_user(user, agent.organization_id), agent
    ):
        raise ForbiddenError("You cannot authorize an application to act as this agent")

    code = new_token()
    session.add(
        OAuthAuthorizationCode(
            code_hash=hash_token(code),
            client_id=pending.client_id,
            user_id=user.id,
            agent_id=agent.id,
            redirect_uri=pending.redirect_uri,
            code_challenge=pending.code_challenge,
            scope=pending.scope,
            resource=pending.resource,
            expires_at=datetime.now(UTC) + AUTHORIZATION_CODE_LIFETIME,
        )
    )
    redirect_url = authorization_response_url(
        settings, pending.redirect_uri, pending.state, code=code
    )
    await session.delete(pending)
    await session.flush()
    return redirect_url


async def deny_authorization_request(
    session: AsyncSession, settings: Settings, request_id: uuid.UUID, user: User
) -> str:
    """Refuse the client: the request is used up and the returned URL tells the client so."""
    pending, _client = await get_authorization_request(session, request_id, user, for_update=True)
    redirect_url = authorization_response_url(
        settings,
        pending.redirect_uri,
        pending.state,
        error="access_denied",
        error_description="The user denied the request",
    )
    await session.delete(pending)
    await session.flush()
    return redirect_url
