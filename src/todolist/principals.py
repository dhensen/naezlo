"""The actor type: who is doing something, a user or an agent.

Code that checks permissions or records audit events takes a `Principal`, never a bare `User`
or `Agent`, so both kinds of actor go through the same rules.
"""

import enum
import uuid
from dataclasses import dataclass

from todolist.models import Agent, User


class PrincipalKind(enum.StrEnum):
    USER = "user"
    AGENT = "agent"


@dataclass(frozen=True)
class Principal:
    """A user or an agent, acting in one organization.

    `id` is the user's or the agent's id, depending on `kind`. `organization_id` is the
    organization the principal acts in: for an agent the one it belongs to, for a user the one
    the request is about (a user can be in several). `name` is the display name at this moment,
    kept for audit events, which outlive their actor.

    Building a principal does not check anything: the caller makes sure the user is a member of
    that organization (`OrgContext.principal` does).
    """

    kind: PrincipalKind
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str

    @classmethod
    def for_user(cls, user: User, organization_id: uuid.UUID) -> Principal:
        return cls(
            kind=PrincipalKind.USER, id=user.id, organization_id=organization_id, name=user.name
        )

    @classmethod
    def for_agent(cls, agent: Agent) -> Principal:
        return cls(
            kind=PrincipalKind.AGENT,
            id=agent.id,
            organization_id=agent.organization_id,
            name=agent.name,
        )

    @property
    def is_user(self) -> bool:
        return self.kind is PrincipalKind.USER

    @property
    def is_agent(self) -> bool:
        return self.kind is PrincipalKind.AGENT
