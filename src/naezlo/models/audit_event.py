"""Audit events: who changed what, kept after the thing they changed is gone."""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from naezlo.db import Base, UUIDPrimaryKeyMixin, value_enum
from naezlo.models.project_grant import PrincipalKind


class AuditAction(enum.StrEnum):
    """The actions that are recorded. The column is a plain string, so adding one needs no
    migration."""

    PROJECT_CREATED = "project.created"
    PROJECT_UPDATED = "project.updated"
    PROJECT_DELETED = "project.deleted"
    LIST_CREATED = "list.created"
    LIST_UPDATED = "list.updated"
    LIST_DELETED = "list.deleted"
    ITEM_CREATED = "item.created"
    ITEM_UPDATED = "item.updated"
    ITEM_COMPLETED = "item.completed"
    ITEM_REOPENED = "item.reopened"
    ITEM_MOVED = "item.moved"
    ITEM_DELETED = "item.deleted"
    ITEM_ASSIGNED = "item.assigned"
    ITEM_UNASSIGNED = "item.unassigned"
    PROJECT_GRANT_SET = "project_grant.set"
    PROJECT_GRANT_REVOKED = "project_grant.revoked"
    LIST_GRANT_SET = "list_grant.set"
    LIST_GRANT_REVOKED = "list_grant.revoked"


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    """One recorded change. Events are only ever inserted (`naezlo.services.audit`)."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_project_id_created_at", "project_id", "created_at"),
        Index("ix_audit_events_list_id_created_at", "list_id", "created_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    # No foreign keys on the project, the list, the actor and the target: the event is a
    # record and stays when they are deleted.
    project_id: Mapped[uuid.UUID | None]
    list_id: Mapped[uuid.UUID | None]
    actor_kind: Mapped[PrincipalKind] = mapped_column(value_enum(PrincipalKind, "principal_kind"))
    actor_id: Mapped[uuid.UUID]
    # The actor's name when it happened.
    actor_name: Mapped[str] = mapped_column(String(200))
    # An `AuditAction` value, such as "item.completed".
    action: Mapped[str] = mapped_column(String(100))
    # "project", "list", "item", "project_grant" or "list_grant".
    target_kind: Mapped[str] = mapped_column(String(50))
    target_id: Mapped[uuid.UUID]
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
