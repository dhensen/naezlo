"""The MCP tools. They call the same service functions as the HTTP API, with the agent's
`Principal`; every permission check goes through `todolist.permissions`."""

import uuid

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from todolist.mcp_server.context import AgentContextFactory
from todolist.models import Organization
from todolist.permissions import accessible_lists


class OrganizationInfo(BaseModel):
    id: uuid.UUID
    name: str
    slug: str


class WhoAmI(BaseModel):
    agent_id: uuid.UUID
    name: str = Field(description="The agent you act as")
    organization: OrganizationInfo
    accessible_list_count: int = Field(description="How many lists you can read")


def register_tools(server: MCPServer, agent_context: AgentContextFactory) -> None:
    @server.tool()
    async def whoami() -> WhoAmI:  # pyright: ignore[reportUnusedFunction]
        """Who you are: the agent you act as, its organization and how many lists you can
        access."""
        async with agent_context() as ctx:
            principal = ctx.principal
            organization = (
                await ctx.session.execute(
                    select(Organization).where(Organization.id == principal.organization_id)
                )
            ).scalar_one()
            count = await ctx.session.scalar(
                select(func.count()).select_from(accessible_lists(principal).subquery())
            )
            return WhoAmI(
                agent_id=principal.id,
                name=principal.name,
                organization=OrganizationInfo(
                    id=organization.id, name=organization.name, slug=organization.slug
                ),
                accessible_list_count=count or 0,
            )
