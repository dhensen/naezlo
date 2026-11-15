"""Agents: register, list, change and delete the AI agents of an organization.

The callers check that the acting user may manage the organization (owner or admin).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from todolist.errors import ConflictError, NotFoundError
from todolist.models import Agent
from todolist.permissions import accessible_lists
from todolist.principals import Principal


def _clean_description(description: str | None) -> str | None:
    """Trimmed; an empty description is stored as no description."""
    if description is None:
        return None
    return description.strip() or None


def _name_taken(name: str) -> ConflictError:
    return ConflictError("agent_name_taken", f'This organization already has an agent "{name}"')


async def list_agents(session: AsyncSession, organization_id: uuid.UUID) -> list[Agent]:
    """The agents of an organization, oldest first."""
    agents = await session.scalars(
        select(Agent).where(Agent.organization_id == organization_id).order_by(Agent.id)
    )
    return list(agents)


@dataclass(frozen=True)
class AgentReach:
    """How much an agent can access: the lists it sees and the projects those are in."""

    project_count: int = 0
    list_count: int = 0


async def agent_reach(session: AsyncSession, agents: list[Agent]) -> dict[uuid.UUID, AgentReach]:
    """The reach of each of these agents, by agent id.

    Counted with `accessible_lists`, so it is what the agent gets from the MCP tools
    `list_lists` and `list_projects`: a human-only list does not count, and a project counts
    when the agent sees at least one list in it.
    """
    reach: dict[uuid.UUID, AgentReach] = {}
    for agent in agents:
        lists = accessible_lists(Principal.for_agent(agent)).subquery()
        row = (
            await session.execute(
                select(func.count(lists.c.project_id.distinct()), func.count()).select_from(lists)
            )
        ).one()
        reach[agent.id] = AgentReach(project_count=row[0], list_count=row[1])
    return reach


async def get_agent(
    session: AsyncSession, organization_id: uuid.UUID, agent_id: uuid.UUID
) -> Agent:
    """The agent with this id in this organization; 404 when there is none."""
    agent = await session.scalar(
        select(Agent).where(Agent.id == agent_id, Agent.organization_id == organization_id)
    )
    if agent is None:
        raise NotFoundError("Agent not found")
    return agent


async def create_agent(
    session: AsyncSession,
    organization_id: uuid.UUID,
    created_by: uuid.UUID,
    name: str,
    description: str | None,
) -> Agent:
    agent = Agent(
        organization_id=organization_id,
        name=name.strip(),
        description=_clean_description(description),
        created_by=created_by,
    )
    # The unique constraint decides, so two requests at the same moment can't both get the
    # name. The savepoint keeps the request's transaction usable after a conflict; the add is
    # inside it because `begin_nested()` first flushes whatever is pending.
    try:
        async with session.begin_nested():
            session.add(agent)
            await session.flush()
    except IntegrityError:
        raise _name_taken(agent.name) from None
    return agent


async def update_agent(
    session: AsyncSession,
    agent: Agent,
    *,
    name: str | None = None,
    description: str | None = None,
    set_description: bool = False,
) -> Agent:
    """Change the name (when given) and the description (when `set_description`; None clears it)."""
    new_name = agent.name if name is None else name.strip()
    try:
        # The changes are made inside the savepoint, see `create_agent`.
        async with session.begin_nested():
            agent.name = new_name
            if set_description:
                agent.description = _clean_description(description)
            await session.flush()
    except IntegrityError:
        raise _name_taken(new_name) from None
    # updated_at is set by the database.
    await session.refresh(agent)
    return agent


async def delete_agent(session: AsyncSession, agent: Agent) -> None:
    await session.delete(agent)
    await session.flush()
