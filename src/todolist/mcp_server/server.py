"""Builds the SDK's `MCPServer` and its ASGI app for one FastAPI app."""

from urllib.parse import urlsplit

from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp

from todolist.config import Settings
from todolist.db import SessionScope
from todolist.mcp_server.context import AgentTokenVerifier, agent_context_factory
from todolist.mcp_server.tools import register_tools
from todolist.services.oauth import MCP_SCOPE

MCP_PATH = "/mcp"

_LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]")


def create_mcp_server(settings: Settings, session_scope: SessionScope) -> MCPServer:
    """A new server per app: its session manager can be started only once.

    `session_scope` opens a database session with its transaction; the token check and
    every tool call use one each.
    """
    server = MCPServer(
        settings.app_name,
        instructions=(
            "Todo lists shared by people and AI agents. You act as one agent and see only "
            "the lists that agent was given access to. Before you start working on an item, "
            "call claim_item so that people and other agents see it is taken; leave items "
            "alone that are assigned to someone else."
        ),
        token_verifier=AgentTokenVerifier(session_scope),
        # This app is a resource server here; its own OAuth endpoints (api/oauth.py) are the
        # authorization server. The 401 challenge points to the metadata built from this URL.
        auth=AuthSettings.model_validate(
            {
                "issuer_url": settings.oauth_issuer,
                "resource_server_url": settings.mcp_resource_url,
                "required_scopes": [MCP_SCOPE],
                # The token store only holds tokens issued for this endpoint, so there is
                # no other audience to refuse (and `resource` may be null on a token).
                "validate_token_resource": False,
            }
        ),
    )
    register_tools(server, agent_context_factory(session_scope))
    return server


def transport_security(settings: Settings) -> TransportSecuritySettings:
    """Only answer requests addressed to the public host (DNS rebinding protection).

    Outside production the loopback names are allowed too, for a server run on a laptop.
    """
    public = urlsplit(settings.public_base_url)
    hosts = [public.netloc]
    origins = [f"{public.scheme}://{public.netloc}"]
    if settings.environment != "production":
        hosts += [f"{host}:*" for host in _LOCAL_HOSTS]
        origins += [f"http://{host}:*" for host in _LOCAL_HOSTS]
    return TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=origins)


def mcp_asgi_app(server: MCPServer, settings: Settings) -> ASGIApp:
    """The ASGI app that serves `MCP_PATH`. The caller runs `server.session_manager.run()`
    in its lifespan; a sub-application's own lifespan never runs.

    Stateless with JSON responses: every request stands alone and carries the bearer token,
    so nothing is kept in memory between requests and any worker can answer.
    """
    return server.streamable_http_app(
        streamable_http_path=MCP_PATH,
        stateless_http=True,
        json_response=True,
        transport_security=transport_security(settings),
    )
