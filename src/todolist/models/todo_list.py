"""Lists: a todo list belongs to one project and says who works on it (its mode)."""

import enum
import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from todolist.db import Base, TimestampMixin, UUIDPrimaryKeyMixin, value_enum


class ListMode(enum.StrEnum):
    """Who works on a list: only people, only AI agents, or both."""

    HUMAN_ONLY = "human_only"
    AI_ONLY = "ai_only"
    MIXED = "mixed"


class TodoList(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "todo_lists"
    __table_args__ = (Index("ix_todo_lists_project_id", "project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    mode: Mapped[ListMode] = mapped_column(value_enum(ListMode, "list_mode"))
    # Order of the lists within their project, lowest first. Not necessarily gap-free.
    position: Mapped[int] = mapped_column(Integer)
    # The user who created the list; empty when that user no longer exists.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
