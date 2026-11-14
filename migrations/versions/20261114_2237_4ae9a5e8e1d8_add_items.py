"""add items

Revision ID: 4ae9a5e8e1d8
Revises: a0f9fa30f0c9
Create Date: 2026-11-14 22:37:50.779835
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "4ae9a5e8e1d8"
down_revision: str | Sequence[str] | None = "a0f9fa30f0c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "items",
        sa.Column("list_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.Enum("open", "done", name="item_status"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        # The type exists already (project_grants).
        sa.Column(
            "created_by_kind",
            postgresql.ENUM("user", "agent", name="principal_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column(
            "completed_by_kind",
            postgresql.ENUM("user", "agent", name="principal_kind", create_type=False),
            nullable=True,
        ),
        sa.Column("completed_by_id", sa.Uuid(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'done' AND completed_by_kind IS NOT NULL"
            " AND completed_by_id IS NOT NULL AND completed_at IS NOT NULL)"
            " OR (status = 'open' AND completed_by_kind IS NULL"
            " AND completed_by_id IS NULL AND completed_at IS NULL)",
            name=op.f("ck_items_completion_matches_status"),
        ),
        sa.ForeignKeyConstraint(
            ["list_id"],
            ["todo_lists.id"],
            name=op.f("fk_items_list_id_todo_lists"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_items")),
    )
    op.create_index("ix_items_list_id_position", "items", ["list_id", "position"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_items_list_id_position", table_name="items")
    op.drop_table("items")
    # Dropping the table leaves the enum type behind; a second upgrade would fail on it.
    # principal_kind stays: project_grants owns it.
    sa.Enum(name="item_status").drop(op.get_bind())
