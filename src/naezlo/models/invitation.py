"""Invitations: an email address that joins an organization on its next sign-in."""

import enum
import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, validates

from naezlo.db import Base, TimestampMixin, UUIDPrimaryKeyMixin, value_enum
from naezlo.models.user import normalize_email


class InvitationRole(enum.StrEnum):
    """The roles an invitation can give. Ownership is never handed out by invitation."""

    ADMIN = "admin"
    MEMBER = "member"


class Invitation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "invitations"
    __table_args__ = (
        UniqueConstraint("organization_id", "email"),
        # Same guard as users.email: the model lowercases, the database checks.
        CheckConstraint("email = lower(email)", name="email_lowercase"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    email: Mapped[str] = mapped_column(String(320), index=True)
    role: Mapped[InvitationRole] = mapped_column(value_enum(InvitationRole, "invitation_role"))
    # The user who sent the invitation; empty when that user no longer exists.
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    @validates("email")
    def _normalize_email(self, _key: str, value: str) -> str:
        return normalize_email(value)
