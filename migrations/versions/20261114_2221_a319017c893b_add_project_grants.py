"""add project grants

Revision ID: a319017c893b
Revises: 25fe7b5f0643
Create Date: 2026-11-14 22:21:04.251725
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a319017c893b"
down_revision: str | Sequence[str] | None = "25fe7b5f0643"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_grants",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column(
            "principal_kind", sa.Enum("user", "agent", name="principal_kind"), nullable=False
        ),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column(
            "role", sa.Enum("viewer", "editor", "admin", name="project_role"), nullable=False
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
            name=op.f("ck_project_grants_principal_matches_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_project_grants_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_project_grants_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_project_grants_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_grants")),
        sa.UniqueConstraint(
            "project_id", "agent_id", name=op.f("uq_project_grants_project_id_agent_id")
        ),
        sa.UniqueConstraint(
            "project_id", "user_id", name=op.f("uq_project_grants_project_id_user_id")
        ),
    )
    op.create_index("ix_project_grants_agent_id", "project_grants", ["agent_id"], unique=False)
    op.create_index("ix_project_grants_user_id", "project_grants", ["user_id"], unique=False)
    # Projects that exist already: their creator becomes admin, as for a new project.
    op.execute(
        "INSERT INTO project_grants (id, project_id, principal_kind, user_id, role)"
        " SELECT uuidv7(), id, 'user', created_by, 'admin'"
        " FROM projects WHERE created_by IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_project_grants_user_id", table_name="project_grants")
    op.drop_index("ix_project_grants_agent_id", table_name="project_grants")
    op.drop_table("project_grants")
    # Dropping the table leaves the enum types behind; a second upgrade would fail on them.
    sa.Enum(name="project_role").drop(op.get_bind())
    sa.Enum(name="principal_kind").drop(op.get_bind())
