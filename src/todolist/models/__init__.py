"""ORM models.

Import every model module here: Alembic's autogenerate (`migrations/env.py`) imports this
package to fill `Base.metadata`.
"""

from todolist.models.agent import Agent
from todolist.models.invitation import Invitation, InvitationRole
from todolist.models.list_grant import ListGrant, ListRole
from todolist.models.organization import Membership, MembershipRole, Organization
from todolist.models.project import Project
from todolist.models.project_grant import PrincipalKind, ProjectGrant, ProjectRole
from todolist.models.todo_list import ListMode, TodoList
from todolist.models.user import User, normalize_email

__all__ = [
    "Agent",
    "Invitation",
    "InvitationRole",
    "ListGrant",
    "ListMode",
    "ListRole",
    "Membership",
    "MembershipRole",
    "Organization",
    "PrincipalKind",
    "Project",
    "ProjectGrant",
    "ProjectRole",
    "TodoList",
    "User",
    "normalize_email",
]
