"""add todo lists

Revision ID: 2f48a44bfe9a
Revises: a319017c893b
Create Date: 2026-11-14 22:27:43.119839
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2f48a44bfe9a"
down_revision: str | Sequence[str] | None = "a319017c893b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "todo_lists",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "mode", sa.Enum("human_only", "ai_only", "mixed", name="list_mode"), nullable=False
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_todo_lists_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_todo_lists_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_todo_lists")),
    )
    op.create_index("ix_todo_lists_project_id", "todo_lists", ["project_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_todo_lists_project_id", table_name="todo_lists")
    op.drop_table("todo_lists")
    # Dropping the table leaves the enum type behind; a second upgrade would fail on it.
    sa.Enum(name="list_mode").drop(op.get_bind())
