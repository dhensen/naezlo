"""add list grants

Revision ID: a0f9fa30f0c9
Revises: 2f48a44bfe9a
Create Date: 2026-11-14 22:33:08.494472
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a0f9fa30f0c9"
down_revision: str | Sequence[str] | None = "2f48a44bfe9a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "list_grants",
        sa.Column("list_id", sa.Uuid(), nullable=False),
        # The type exists already (project_grants).
        sa.Column(
            "principal_kind",
            postgresql.ENUM("user", "agent", name="principal_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column(
            "role", sa.Enum("none", "viewer", "editor", "admin", name="list_role"), nullable=False
        ),
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
            "(principal_kind = 'user' AND user_id IS NOT NULL AND agent_id IS NULL)"
            " OR (principal_kind = 'agent' AND agent_id IS NOT NULL AND user_id IS NULL)",
            name=op.f("ck_list_grants_principal_matches_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_list_grants_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["list_id"],
            ["todo_lists.id"],
            name=op.f("fk_list_grants_list_id_todo_lists"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_list_grants_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_list_grants")),
        sa.UniqueConstraint("list_id", "agent_id", name=op.f("uq_list_grants_list_id_agent_id")),
        sa.UniqueConstraint("list_id", "user_id", name=op.f("uq_list_grants_list_id_user_id")),
    )
    op.create_index("ix_list_grants_agent_id", "list_grants", ["agent_id"], unique=False)
    op.create_index("ix_list_grants_user_id", "list_grants", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_list_grants_user_id", table_name="list_grants")
    op.drop_index("ix_list_grants_agent_id", table_name="list_grants")
    op.drop_table("list_grants")
    # Dropping the table leaves the enum type behind; a second upgrade would fail on it.
    # principal_kind stays: project_grants uses it.
    sa.Enum(name="list_role").drop(op.get_bind())
