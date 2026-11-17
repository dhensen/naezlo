"""ORM models.

Import every model module here: Alembic's autogenerate (`migrations/env.py`) imports this
package to fill `Base.metadata`.
"""

from naezlo.models.agent import Agent
from naezlo.models.audit_event import AuditAction, AuditEvent
from naezlo.models.invitation import Invitation, InvitationRole
from naezlo.models.item import Item, ItemStatus
from naezlo.models.list_grant import ListGrant, ListRole
from naezlo.models.oauth import (
    OAuthAccessToken,
    OAuthAuthorizationCode,
    OAuthAuthorizationRequest,
    OAuthClient,
    OAuthRefreshToken,
)
from naezlo.models.organization import Membership, MembershipRole, Organization
from naezlo.models.project import Project
from naezlo.models.project_grant import PrincipalKind, ProjectGrant, ProjectRole
from naezlo.models.todo_list import ListMode, TodoList
from naezlo.models.user import User, normalize_email

__all__ = [
    "Agent",
    "AuditAction",
    "AuditEvent",
    "Invitation",
    "InvitationRole",
    "Item",
    "ItemStatus",
    "ListGrant",
    "ListMode",
    "ListRole",
    "Membership",
    "MembershipRole",
    "OAuthAccessToken",
    "OAuthAuthorizationCode",
    "OAuthAuthorizationRequest",
    "OAuthClient",
    "OAuthRefreshToken",
    "Organization",
    "PrincipalKind",
    "Project",
    "ProjectGrant",
    "ProjectRole",
    "TodoList",
    "User",
    "normalize_email",
]
