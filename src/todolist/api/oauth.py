"""OAuth authorization server endpoints for MCP clients.

`root_router` holds the routes whose paths the OAuth and MCP specifications fix; they live at
the root of the app, not under `/api`. Their errors are `OAuthError`s (RFC 6749 shape).
`router` holds what the consent page of the SPA calls, under `/api/oauth`, with the usual
`AppError`s.
"""

import html
import uuid
from datetime import datetime
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from todolist.auth import CurrentUser, OptionalCurrentUser
from todolist.config import SettingsDep
from todolist.db import SessionDep
from todolist.errors import oauth_error_response
from todolist.services import oauth, oauth_tokens

root_router = APIRouter(tags=["oauth"])
router = APIRouter(prefix="/oauth", tags=["oauth"])

# Where the SPA asks the user to approve a client and pick an agent, and where it signs in.
CONSENT_PAGE_PATH = "/oauth/consent"
LOGIN_PAGE_PATH = "/login"
_NO_STORE = {"Cache-Control": "no-store"}

# Clients may cache the metadata documents; they only change with a deployment.
_METADATA_HEADERS = {"Cache-Control": "public, max-age=3600"}


def _metadata_response(metadata: BaseModel) -> JSONResponse:
    return JSONResponse(
        metadata.model_dump(mode="json", exclude_none=True), headers=_METADATA_HEADERS
    )


@root_router.get("/.well-known/oauth-authorization-server")
async def authorization_server_metadata(settings: SettingsDep) -> JSONResponse:
    """RFC 8414 authorization server metadata."""
    return _metadata_response(oauth.authorization_server_metadata(settings))


# MCP clients try the variant with the resource's path (/mcp) first and the root one second.
@root_router.get("/.well-known/oauth-protected-resource/mcp")
@root_router.get("/.well-known/oauth-protected-resource")
async def protected_resource_metadata(settings: SettingsDep) -> JSONResponse:
    """RFC 9728 protected resource metadata of the MCP endpoint."""
    return _metadata_response(oauth.protected_resource_metadata(settings))


@root_router.post(oauth.REGISTRATION_PATH, status_code=201)
async def register_client(request: Request, session: SessionDep) -> JSONResponse:
    """RFC 7591 dynamic client registration. Open to anyone; it registers public clients only."""
    client = await oauth.register_client(session, await request.body())
    return JSONResponse(
        oauth.client_information(client),
        status_code=201,
        headers={"Cache-Control": "no-store"},
    )


def _authorization_error_page(app_name: str, description: str) -> HTMLResponse:
    """What the person sees when the client or its redirect URI cannot be trusted: the
    browser stays here, because sending it on would make this server an open redirector."""
    title = html.escape(f"{app_name}: authorization failed")
    page = (
        "<!doctype html>"
        '<html lang="en"><head><meta charset="utf-8">'
        f"<title>{title}</title></head>"
        f"<body><h1>Authorization failed</h1><p>{html.escape(description)}</p>"
        "<p>Close this window and try to connect again from the application.</p></body></html>"
    )
    return HTMLResponse(page, status_code=400, headers=_NO_STORE)


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=302, headers=_NO_STORE)


@root_router.get(oauth.AUTHORIZATION_PATH, status_code=302, response_class=RedirectResponse)
async def authorize(
    request: Request, session: SessionDep, settings: SettingsDep, user: OptionalCurrentUser
) -> Response:
    """The OAuth authorization endpoint, opened in the user's browser by an MCP client.

    A valid request ends on the consent page of the SPA (through the login page when nobody
    is signed in), which answers it through `/api/oauth/requests/{id}`.
    """
    try:
        validated = await oauth.validate_authorization_request(
            session, settings, request.query_params.multi_items()
        )
    except oauth.AuthorizationPageError as error:
        return _authorization_error_page(settings.app_name, error.description)
    except oauth.AuthorizationRedirectError as error:
        return _redirect(error.redirect_url)

    if user is None:
        # Come back to this same request after signing in; it is validated again then.
        next_path = f"{oauth.AUTHORIZATION_PATH}?{request.url.query}"
        return _redirect(f"{LOGIN_PAGE_PATH}?{urlencode({'next': next_path})}")

    pending = await oauth.create_authorization_request(session, validated, user)
    return _redirect(f"{CONSENT_PAGE_PATH}?{urlencode({'request': str(pending.id)})}")


@root_router.post(oauth.TOKEN_PATH)
async def token(request: Request, session: SessionDep, settings: SettingsDep) -> JSONResponse:
    """The OAuth token endpoint: exchanges an authorization code (with its PKCE verifier) for
    tokens, and rotates a refresh token. The body is form-encoded."""
    try:
        issued = await oauth_tokens.token_request(
            session, settings, request.headers.get("content-type"), await request.body()
        )
    except oauth_tokens.ReplayedGrantError as error:
        # Returned, not raised: the revocation that came with it must be committed.
        return oauth_error_response(error)
    return JSONResponse(issued.response_body(), headers={**_NO_STORE, "Pragma": "no-cache"})


@root_router.post(oauth.REVOCATION_PATH)
async def revoke(request: Request, session: SessionDep) -> Response:
    """RFC 7009 token revocation. Answers 200 also when the token was not valid."""
    await oauth_tokens.revoke_token(
        session, request.headers.get("content-type"), await request.body()
    )
    return Response(status_code=200, headers=_NO_STORE)


class ConsentOrganizationOut(BaseModel):
    id: uuid.UUID
    name: str


class ConsentAgentOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    organization: ConsentOrganizationOut


class AuthorizationRequestOut(BaseModel):
    id: uuid.UUID
    # What the client called itself when it registered; anyone can register any name.
    client_name: str | None
    # Where the browser goes after the answer: the part of the redirect URI to show the user.
    redirect_host: str
    scope: str
    expires_at: datetime
    # The agents the user may let the client act as.
    agents: list[ConsentAgentOut]


class ApproveIn(BaseModel):
    agent_id: uuid.UUID


class AuthorizationAnswerOut(BaseModel):
    # Where the SPA sends the browser: back to the client, with the code or the error.
    redirect_url: str


@router.get("/requests/{request_id}")
async def get_authorization_request(
    request_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> AuthorizationRequestOut:
    pending, client = await oauth.get_authorization_request(session, request_id, user)
    agents = await oauth.list_authorizable_agents(session, user)
    return AuthorizationRequestOut(
        id=pending.id,
        client_name=client.client_name,
        redirect_host=urlsplit(pending.redirect_uri).netloc,
        scope=pending.scope,
        expires_at=pending.expires_at,
        agents=[
            ConsentAgentOut(
                id=agent.id,
                name=agent.name,
                description=agent.description,
                organization=ConsentOrganizationOut(id=organization.id, name=organization.name),
            )
            for agent, organization in agents
        ],
    )


@router.post("/requests/{request_id}/approve")
async def approve_authorization_request(
    request_id: uuid.UUID,
    body: ApproveIn,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> AuthorizationAnswerOut:
    """Let the client act as the chosen agent. The request can be answered once."""
    redirect_url = await oauth.approve_authorization_request(
        session, settings, request_id, user, body.agent_id
    )
    return AuthorizationAnswerOut(redirect_url=redirect_url)


@router.post("/requests/{request_id}/deny")
async def deny_authorization_request(
    request_id: uuid.UUID, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> AuthorizationAnswerOut:
    redirect_url = await oauth.deny_authorization_request(session, settings, request_id, user)
    return AuthorizationAnswerOut(redirect_url=redirect_url)
