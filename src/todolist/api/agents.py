"""Agents: the AI agents of an organization. Any member lists them; owners and admins manage."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, StringConstraints, field_validator

from todolist.api.deps import OrgAdminContextDep, OrgContextDep
from todolist.db import SessionDep
from todolist.models import Agent
from todolist.services.agents import (
    AgentReach,
    agent_reach,
    create_agent,
    delete_agent,
    get_agent,
    list_agents,
    update_agent,
)

router = APIRouter(prefix="/orgs/{org_id}/agents", tags=["agents"])

# agents.name holds 200 characters.
AgentName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
AgentDescription = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class AgentIn(BaseModel):
    name: AgentName
    description: AgentDescription | None = None


class AgentPatch(BaseModel):
    """Only the fields that are sent change. `description: null` removes the description."""

    name: AgentName | None = None
    description: AgentDescription | None = None

    @field_validator("name")
    @classmethod
    def _name_is_not_null(cls, value: str | None) -> str | None:
        # Runs only when `name` is sent: leaving it out is fine, null is not a name.
        if value is None:
            raise ValueError("name cannot be null")
        return value


class AgentOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    created_by: uuid.UUID | None
    # The lists the agent can see, and the projects those lists are in.
    project_count: int
    list_count: int
    created_at: datetime
    updated_at: datetime


def _agent_out(agent: Agent, reach: AgentReach) -> AgentOut:
    return AgentOut(
        id=agent.id,
        name=agent.name,
        description=agent.description,
        created_by=agent.created_by,
        project_count=reach.project_count,
        list_count=reach.list_count,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


@router.get("")
async def list_agents_route(org: OrgContextDep, session: SessionDep) -> list[AgentOut]:
    agents = await list_agents(session, org.organization.id)
    reach = await agent_reach(session, agents)
    return [_agent_out(agent, reach[agent.id]) for agent in agents]


@router.post("", status_code=201)
async def create_agent_route(
    body: AgentIn, org: OrgAdminContextDep, session: SessionDep
) -> AgentOut:
    agent = await create_agent(
        session, org.organization.id, org.user.id, body.name, body.description
    )
    # A new agent has no grants yet.
    return _agent_out(agent, AgentReach())


@router.patch("/{agent_id}")
async def update_agent_route(
    agent_id: uuid.UUID, body: AgentPatch, org: OrgAdminContextDep, session: SessionDep
) -> AgentOut:
    agent = await get_agent(session, org.organization.id, agent_id)
    await update_agent(
        session,
        agent,
        name=body.name,
        description=body.description,
        set_description="description" in body.model_fields_set,
    )
    return _agent_out(agent, (await agent_reach(session, [agent]))[agent.id])


@router.delete("/{agent_id}", status_code=204)
async def delete_agent_route(
    agent_id: uuid.UUID, org: OrgAdminContextDep, session: SessionDep
) -> None:
    agent = await get_agent(session, org.organization.id, agent_id)
    await delete_agent(session, agent)
