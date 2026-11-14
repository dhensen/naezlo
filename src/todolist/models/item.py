"""Items: the things to do on a list."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from todolist.db import Base, TimestampMixin, UUIDPrimaryKeyMixin, value_enum
from todolist.models.project_grant import PrincipalKind


class ItemStatus(enum.StrEnum):
    OPEN = "open"
    DONE = "done"


class Item(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "items"
    __table_args__ = (
        # A done item says who completed it and when; an open one says neither.
        CheckConstraint(
            "(status = 'done' AND completed_by_kind IS NOT NULL"
            " AND completed_by_id IS NOT NULL AND completed_at IS NOT NULL)"
            " OR (status = 'open' AND completed_by_kind IS NULL"
            " AND completed_by_id IS NULL AND completed_at IS NULL)",
            name="completion_matches_status",
        ),
        Index("ix_items_list_id_position", "list_id", "position"),
    )

    list_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("todo_lists.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ItemStatus] = mapped_column(
        value_enum(ItemStatus, "item_status"), default=ItemStatus.OPEN
    )
    # Order of the items within their list, lowest first.
    position: Mapped[int] = mapped_column(Integer)
    # The actor is a user or an agent, so the id has no foreign key: it is a record of who
    # did it and stays when that user or agent is deleted.
    created_by_kind: Mapped[PrincipalKind] = mapped_column(
        value_enum(PrincipalKind, "principal_kind")
    )
    created_by_id: Mapped[uuid.UUID]
    completed_by_kind: Mapped[PrincipalKind | None] = mapped_column(
        value_enum(PrincipalKind, "principal_kind")
    )
    completed_by_id: Mapped[uuid.UUID | None]
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
