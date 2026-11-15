"""add item assignee and list assignment_required

Revision ID: c284038e8b7f
Revises: aa786329f14d
Create Date: 2026-11-15 12:10:07.263961
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c284038e8b7f"
down_revision: str | Sequence[str] | None = "aa786329f14d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # principal_kind exists already (project_grants made it).
    op.add_column(
        "items",
        sa.Column(
            "assignee_kind",
            postgresql.ENUM("user", "agent", name="principal_kind", create_type=False),
            nullable=True,
        ),
    )
    op.add_column("items", sa.Column("assignee_id", sa.Uuid(), nullable=True))
    op.create_check_constraint(
        op.f("ck_items_assignee_kind_with_id"),
        "items",
        "(assignee_kind IS NULL) = (assignee_id IS NULL)",
    )
    op.add_column(
        "todo_lists",
        sa.Column(
            "assignment_required", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("todo_lists", "assignment_required")
    op.drop_constraint(op.f("ck_items_assignee_kind_with_id"), "items", type_="check")
    op.drop_column("items", "assignee_id")
    op.drop_column("items", "assignee_kind")
