"""List grants: the role a user or an agent has on one list, overriding their project role."""

import enum
import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from naezlo.db import Base, TimestampMixin, UUIDPrimaryKeyMixin, value_enum
from naezlo.models.project_grant import PrincipalKind, ProjectRole


class ListRole(enum.StrEnum):
    """What a list grant can say: one of the project roles, or `none` to hide the list."""

    NONE = "none"
    VIEWER = "viewer"
    EDITOR = "editor"
    ADMIN = "admin"

    @property
    def project_role(self) -> ProjectRole | None:
        """The role this gives on the list; None for `none` (no access)."""
        return None if self is ListRole.NONE else ProjectRole(self.value)


class ListGrant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "list_grants"
    __table_args__ = (
        # One grant per list and principal. NULLs are distinct in a unique constraint, so the
        # user constraint ignores agent grants and the other way around.
        UniqueConstraint("list_id", "user_id"),
        UniqueConstraint("list_id", "agent_id"),
        CheckConstraint(
            "(principal_kind = 'user' AND user_id IS NOT NULL AND agent_id IS NULL)"
            " OR (principal_kind = 'agent' AND agent_id IS NOT NULL AND user_id IS NULL)",
            name="principal_matches_kind",
        ),
        Index("ix_list_grants_user_id", "user_id"),
        Index("ix_list_grants_agent_id", "agent_id"),
    )

    list_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("todo_lists.id", ondelete="CASCADE"))
    principal_kind: Mapped[PrincipalKind] = mapped_column(
        value_enum(PrincipalKind, "principal_kind")
    )
    # Exactly one of these is set, the one that `principal_kind` names.
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    role: Mapped[ListRole] = mapped_column(value_enum(ListRole, "list_role"))
