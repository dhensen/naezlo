"""Project grants: the role a user or an agent has on one project."""

import enum
import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from naezlo.db import Base, TimestampMixin, UUIDPrimaryKeyMixin, value_enum


class PrincipalKind(enum.StrEnum):
    """The two kinds of actor. `naezlo.principals.Principal` carries one."""

    USER = "user"
    AGENT = "agent"


class ProjectRole(enum.StrEnum):
    """Roles on a project, lowest first. Compare them with `naezlo.permissions.role_at_least`."""

    VIEWER = "viewer"
    EDITOR = "editor"
    ADMIN = "admin"


class ProjectGrant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "project_grants"
    __table_args__ = (
        # One grant per project and principal. NULLs are distinct in a unique constraint, so the
        # user constraint ignores agent grants and the other way around.
        UniqueConstraint("project_id", "user_id"),
        UniqueConstraint("project_id", "agent_id"),
        CheckConstraint(
            "(principal_kind = 'user' AND user_id IS NOT NULL AND agent_id IS NULL)"
            " OR (principal_kind = 'agent' AND agent_id IS NOT NULL AND user_id IS NULL)",
            name="principal_matches_kind",
        ),
        Index("ix_project_grants_user_id", "user_id"),
        Index("ix_project_grants_agent_id", "agent_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    principal_kind: Mapped[PrincipalKind] = mapped_column(
        value_enum(PrincipalKind, "principal_kind")
    )
    # Exactly one of these is set, the one that `principal_kind` names.
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    role: Mapped[ProjectRole] = mapped_column(value_enum(ProjectRole, "project_role"))
