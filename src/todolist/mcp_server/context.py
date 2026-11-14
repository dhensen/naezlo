"""Who is calling and a database session, for MCP tool handlers.

    async with agent_context() as ctx:   # `agent_context` is what `register_tools` receives
        ctx.principal  # the agent the bearer token acts as
        ctx.session    # one transaction for this tool call

The bearer token is checked on every HTTP request by `AgentTokenVerifier`, before the SDK
runs a tool; the tool reads the result from the SDK's request context.
"""

from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy.ext.asyncio import AsyncSession

from todolist.db import SessionScope
from todolist.errors import AppError
from todolist.principals import Principal
from todolist.services.oauth import MCP_SCOPE
from todolist.services.oauth_tokens import resolve_access_token


class AgentAccessToken(AccessToken):
    """The SDK's access token plus the agent it resolved to."""

    principal: Principal


class AgentTokenVerifier:
    """The SDK's `TokenVerifier`: a bearer token is valid when it resolves to an agent."""

    def __init__(self, session_scope: SessionScope) -> None:
        self._session_scope = session_scope

    async def verify_token(self, token: str) -> AccessToken | None:
        async with self._session_scope() as session:
            principal = await resolve_access_token(session, token)
        if principal is None:
            return None
        return AgentAccessToken(
            token=token,
            # The SDK only uses these two to name the caller; the agent is who is calling.
            client_id=str(principal.id),
            subject=str(principal.id),
            scopes=[MCP_SCOPE],
            principal=principal,
        )


@dataclass(frozen=True)
class AgentContext:
    principal: Principal
    session: AsyncSession


def current_principal() -> Principal:
    """The agent of the current MCP request."""
    token = get_access_token()
    if not isinstance(token, AgentAccessToken):
        # Not reachable over HTTP: the endpoint answers 401 before a tool runs.
        raise RuntimeError("MCP tool called without an authenticated agent")
    return token.principal


# What a tool module gets to open its context: `async with agent_context() as ctx`.
AgentContextFactory = Callable[[], AbstractAsyncContextManager[AgentContext]]


def agent_context_factory(session_scope: SessionScope) -> AgentContextFactory:
    @asynccontextmanager
    async def agent_context() -> AsyncGenerator[AgentContext]:
        """The calling agent and a session whose transaction is committed when the block
        ends and rolled back when it raises. An `AppError` raised inside the block becomes
        the SDK's `ToolError` with the same message."""
        principal = current_principal()
        try:
            async with session_scope() as session:
                yield AgentContext(principal=principal, session=session)
        except AppError as error:
            # An error the services and the permission service raise on purpose (not found,
            # not allowed, conflict): the agent gets its message as the tool's error. The
            # transaction is rolled back by now. Anything else is a crash, which the SDK
            # logs and reports without details.
            raise ToolError(error.detail) from error

    return agent_context
