"""The token side of the OAuth server: the token endpoint (authorization code and refresh
token grants), revocation (RFC 7009) and the lookup of an access token for the MCP endpoint.

Clients are public: they identify themselves with `client_id` in the form body and prove the
authorization code is theirs with PKCE. Every error is an `OAuthError` (RFC 6749 5.2).
"""

import base64
import hashlib
import hmac
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from todolist.config import Settings
from todolist.errors import OAuthError
from todolist.models import (
    Agent,
    OAuthAccessToken,
    OAuthAuthorizationCode,
    OAuthClient,
    OAuthRefreshToken,
    User,
)
from todolist.permissions import can_authorize_agent
from todolist.principals import Principal
from todolist.services.oauth import GRANT_TYPES, MCP_SCOPE, find_client, hash_token, new_token

ACCESS_TOKEN_LIFETIME = timedelta(hours=1)
# Every rotation starts a new period, so a client that keeps working stays connected.
REFRESH_TOKEN_LIFETIME = timedelta(days=30)

MAX_FORM_BODY_BYTES = 16 * 1024
FORM_MEDIA_TYPE = "application/x-www-form-urlencoded"
# RFC 7636: 43 to 128 unreserved characters.
_CODE_VERIFIER = re.compile(r"[A-Za-z0-9\-._~]{43,128}")


class ReplayedGrantError(OAuthError):
    """An authorization code or refresh token that was already used came in again, and the
    tokens that descend from it were revoked.

    The route must answer with this error without raising it: raising rolls the request's
    transaction back, and the revocation with it.
    """

    def __init__(self, description: str) -> None:
        super().__init__("invalid_grant", description)


@dataclass(frozen=True)
class IssuedTokens:
    """What a successful token request hands out. The plain values exist only here."""

    access_token: str
    refresh_token: str | None
    expires_in: int
    scope: str

    def response_body(self) -> dict[str, Any]:
        """The RFC 6749 5.1 token response."""
        body: dict[str, Any] = {
            "access_token": self.access_token,
            "token_type": "Bearer",
            "expires_in": self.expires_in,
            "scope": self.scope,
        }
        if self.refresh_token is not None:
            body["refresh_token"] = self.refresh_token
        return body


def _invalid_request(description: str) -> OAuthError:
    return OAuthError("invalid_request", description)


def _invalid_grant(description: str) -> OAuthError:
    return OAuthError("invalid_grant", description)


def parse_form(content_type: str | None, body: bytes) -> dict[str, str]:
    """The parameters of a form-encoded request to /token or /revoke.

    A parameter without a value counts as absent and a repeated one is an error (RFC 6749 3.2).
    """
    if len(body) > MAX_FORM_BODY_BYTES:
        raise _invalid_request("The request is too large")
    media_type = (content_type or "").split(";")[0].strip().lower()
    if media_type != FORM_MEDIA_TYPE:
        raise _invalid_request(f"The request body must be {FORM_MEDIA_TYPE}")
    try:
        pairs = parse_qsl(body.decode(), keep_blank_values=True)
    except UnicodeDecodeError:
        raise _invalid_request("The request body is not valid UTF-8") from None
    form: dict[str, str] = {}
    for name, value in pairs:
        if name in form:
            raise _invalid_request(f"{name} is given more than once")
        form[name] = value
    return {name: value for name, value in form.items() if value}


async def _authenticate_client(session: AsyncSession, form: dict[str, str]) -> OAuthClient:
    """The client that makes the request. A public client only names itself; one with a
    secret (none are registered dynamically) must also send it as `client_secret`."""
    failure = OAuthError("invalid_client", "Unknown client, or client_id is missing", 401)
    client_id = form.get("client_id")
    client = await find_client(session, client_id) if client_id is not None else None
    if client is None:
        raise failure
    if client.client_secret_hash is not None:
        secret = form.get("client_secret")
        if secret is None or not hmac.compare_digest(hash_token(secret), client.client_secret_hash):
            raise failure
    return client


def _requested_resource(settings: Settings, form: dict[str, str]) -> str | None:
    """The RFC 8707 resource of the request: absent, or the MCP endpoint."""
    resource = form.get("resource")
    if resource is None:
        return None
    if resource.rstrip("/") != settings.mcp_resource_url:
        raise OAuthError("invalid_target", f"resource must be {settings.mcp_resource_url}")
    return settings.mcp_resource_url


def _verifier_matches(verifier: str, challenge: str) -> bool:
    """PKCE with S256: the challenge is base64url(sha256(verifier)) without padding."""
    if _CODE_VERIFIER.fullmatch(verifier) is None:
        return False
    digest = hashlib.sha256(verifier.encode()).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return hmac.compare_digest(expected, challenge)


async def _authorized_agent(
    session: AsyncSession, user_id: uuid.UUID, agent_id: uuid.UUID
) -> Agent | None:
    """The agent a code or token stands for, while the approval behind it still holds: the
    agent exists and the user who approved the client may still authorize that agent."""
    agent = await session.get(Agent, agent_id)
    user = await session.get(User, user_id)
    if agent is None or user is None:
        return None
    approver = Principal.for_user(user, agent.organization_id)
    if not await can_authorize_agent(session, approver, agent):
        return None
    return agent


async def _revoke_family(session: AsyncSession, code_id: uuid.UUID, now: datetime) -> None:
    """Revoke every access and refresh token that descends from one authorization code."""
    for model in (OAuthAccessToken, OAuthRefreshToken):
        await session.execute(
            update(model)
            .where(model.authorization_code_id == code_id, model.revoked_at.is_(None))
            .values(revoked_at=now)
            .execution_options(synchronize_session="fetch")
        )


async def _issue_tokens(
    session: AsyncSession,
    client: OAuthClient,
    *,
    code_id: uuid.UUID | None,
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    scope: str,
    resource: str | None,
    now: datetime,
) -> IssuedTokens:
    access_token = new_token()
    session.add(
        OAuthAccessToken(
            token_hash=hash_token(access_token),
            client_id=client.client_id,
            user_id=user_id,
            agent_id=agent_id,
            scope=scope,
            resource=resource,
            expires_at=now + ACCESS_TOKEN_LIFETIME,
            authorization_code_id=code_id,
        )
    )
    refresh_token: str | None = None
    # Only a client that registered the refresh_token grant could use one.
    if "refresh_token" in client.grant_types:
        refresh_token = new_token()
        session.add(
            OAuthRefreshToken(
                token_hash=hash_token(refresh_token),
                client_id=client.client_id,
                user_id=user_id,
                agent_id=agent_id,
                scope=scope,
                resource=resource,
                expires_at=now + REFRESH_TOKEN_LIFETIME,
                authorization_code_id=code_id,
            )
        )
    await session.flush()
    return IssuedTokens(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=int(ACCESS_TOKEN_LIFETIME.total_seconds()),
        scope=scope,
    )


async def _exchange_authorization_code(
    session: AsyncSession, settings: Settings, client: OAuthClient, form: dict[str, str]
) -> IssuedTokens:
    code_value = form.get("code")
    redirect_uri = form.get("redirect_uri")
    code_verifier = form.get("code_verifier")
    if code_value is None:
        raise _invalid_request("code is required")
    if redirect_uri is None:
        raise _invalid_request("redirect_uri is required")
    if code_verifier is None:
        raise _invalid_request("code_verifier is required (PKCE)")
    resource = _requested_resource(settings, form)

    # Locked, so that two requests with the same code cannot both find it unused.
    code = await session.scalar(
        select(OAuthAuthorizationCode)
        .where(OAuthAuthorizationCode.code_hash == hash_token(code_value))
        .with_for_update()
    )
    if code is None or code.client_id != client.client_id:
        raise _invalid_grant("The authorization code is not valid")
    now = datetime.now(UTC)
    if code.used_at is not None:
        # Someone else may have the code: nothing that came from it can be trusted.
        await _revoke_family(session, code.id, now)
        raise ReplayedGrantError("The authorization code was already used")
    if code.expires_at <= now:
        raise _invalid_grant("The authorization code has expired")
    if redirect_uri != code.redirect_uri:
        raise _invalid_grant("redirect_uri is not the one of the authorization request")
    if not _verifier_matches(code_verifier, code.code_challenge):
        raise _invalid_grant("code_verifier does not match the code challenge")
    if await _authorized_agent(session, code.user_id, code.agent_id) is None:
        raise _invalid_grant("The authorization is no longer valid")

    code.used_at = now
    return await _issue_tokens(
        session,
        client,
        code_id=code.id,
        user_id=code.user_id,
        agent_id=code.agent_id,
        scope=code.scope,
        resource=code.resource or resource,
        now=now,
    )


async def _refresh(
    session: AsyncSession, settings: Settings, client: OAuthClient, form: dict[str, str]
) -> IssuedTokens:
    token_value = form.get("refresh_token")
    if token_value is None:
        raise _invalid_request("refresh_token is required")
    scope = form.get("scope")
    if scope is not None and set(scope.split()) != {MCP_SCOPE}:
        raise OAuthError("invalid_scope", f"scope can only be {MCP_SCOPE}")
    resource = _requested_resource(settings, form)

    # Locked, so that two requests with the same token cannot both rotate it.
    old = await session.scalar(
        select(OAuthRefreshToken)
        .where(OAuthRefreshToken.token_hash == hash_token(token_value))
        .with_for_update()
    )
    if old is None or old.client_id != client.client_id:
        raise _invalid_grant("The refresh token is not valid")
    now = datetime.now(UTC)
    if old.revoked_at is not None:
        # A rotated token that comes back was copied somewhere: end the whole family, also
        # the tokens of whoever refreshed first.
        if old.authorization_code_id is not None:
            await _revoke_family(session, old.authorization_code_id, now)
        raise ReplayedGrantError("The refresh token was already used or revoked")
    if old.expires_at <= now:
        raise _invalid_grant("The refresh token has expired")
    if await _authorized_agent(session, old.user_id, old.agent_id) is None:
        raise _invalid_grant("The authorization is no longer valid")

    old.revoked_at = now
    return await _issue_tokens(
        session,
        client,
        code_id=old.authorization_code_id,
        user_id=old.user_id,
        agent_id=old.agent_id,
        scope=old.scope,
        resource=old.resource or resource,
        now=now,
    )


async def token_request(
    session: AsyncSession, settings: Settings, content_type: str | None, body: bytes
) -> IssuedTokens:
    """Answer a POST /token from its raw body: exchange an authorization code, or rotate a
    refresh token.

    Raises `OAuthError`; a `ReplayedGrantError` among them has revoked tokens (see there).
    """
    form = parse_form(content_type, body)
    grant_type = form.get("grant_type")
    if grant_type is None:
        raise _invalid_request("grant_type is required")
    if grant_type not in GRANT_TYPES:
        raise OAuthError(
            "unsupported_grant_type", "grant_type must be authorization_code or refresh_token"
        )
    client = await _authenticate_client(session, form)
    if grant_type not in client.grant_types:
        raise OAuthError("unauthorized_client", f"The client did not register {grant_type}")
    if grant_type == "authorization_code":
        return await _exchange_authorization_code(session, settings, client, form)
    return await _refresh(session, settings, client, form)


async def revoke_token(session: AsyncSession, content_type: str | None, body: bytes) -> None:
    """Answer a POST /revoke (RFC 7009) from its raw body.

    Revoking a refresh token also revokes the access tokens of the same authorization;
    revoking an access token revokes only that one. A token that is unknown, already revoked
    or another client's is not an error. `token_type_hint` is not needed: both kinds are
    looked up.
    """
    form = parse_form(content_type, body)
    client = await _authenticate_client(session, form)
    token_value = form.get("token")
    if token_value is None:
        raise _invalid_request("token is required")
    token_hash = hash_token(token_value)
    now = datetime.now(UTC)

    refresh_token = await session.scalar(
        select(OAuthRefreshToken)
        .where(
            OAuthRefreshToken.token_hash == token_hash,
            OAuthRefreshToken.client_id == client.client_id,
        )
        .with_for_update()
    )
    if refresh_token is not None:
        if refresh_token.authorization_code_id is not None:
            await _revoke_family(session, refresh_token.authorization_code_id, now)
        if refresh_token.revoked_at is None:
            refresh_token.revoked_at = now
        await session.flush()
        return

    access_token = await session.scalar(
        select(OAuthAccessToken)
        .where(
            OAuthAccessToken.token_hash == token_hash,
            OAuthAccessToken.client_id == client.client_id,
        )
        .with_for_update()
    )
    if access_token is not None and access_token.revoked_at is None:
        access_token.revoked_at = now
        await session.flush()


async def resolve_access_token(session: AsyncSession, token: str) -> Principal | None:
    """The agent a bearer token acts as, or None when the token gives no access: unknown,
    expired or revoked, the agent was deleted, or the user who approved the client may no
    longer authorize that agent (left the organization, or is no longer owner or admin)."""
    access_token = await session.scalar(
        select(OAuthAccessToken).where(
            OAuthAccessToken.token_hash == hash_token(token),
            OAuthAccessToken.revoked_at.is_(None),
            OAuthAccessToken.expires_at > datetime.now(UTC),
        )
    )
    if access_token is None:
        return None
    agent = await _authorized_agent(session, access_token.user_id, access_token.agent_id)
    return None if agent is None else Principal.for_agent(agent)
