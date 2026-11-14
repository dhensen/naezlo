"""add audit events

Revision ID: b82bcf0756e0
Revises: 7e182c993f2e
Create Date: 2026-11-14 22:53:29.275667
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b82bcf0756e0"
down_revision: str | Sequence[str] | None = "7e182c993f2e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("list_id", sa.Uuid(), nullable=True),
        # The type exists already (project_grants).
        sa.Column(
            "actor_kind",
            postgresql.ENUM("user", "agent", name="principal_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("actor_name", sa.String(length=200), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_kind", sa.String(length=50), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_audit_events_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(
        "ix_audit_events_list_id_created_at",
        "audit_events",
        ["list_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_project_id_created_at",
        "audit_events",
        ["project_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_project_id_created_at", table_name="audit_events")
    op.drop_index("ix_audit_events_list_id_created_at", table_name="audit_events")
    op.drop_table("audit_events")
    # principal_kind stays: project_grants owns it.
