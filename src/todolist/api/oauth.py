"""OAuth authorization server endpoints for MCP clients.

`root_router` holds the routes whose paths the OAuth and MCP specifications fix; they live at
the root of the app, not under `/api`. Their errors are `OAuthError`s (RFC 6749 shape).
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from todolist.config import SettingsDep
from todolist.db import SessionDep
from todolist.services import oauth

root_router = APIRouter(tags=["oauth"])

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
