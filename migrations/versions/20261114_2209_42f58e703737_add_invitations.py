"""add invitations

Revision ID: 42f58e703737
Revises: 3f46e4359648
Create Date: 2026-11-14 22:09:49.999686
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "42f58e703737"
down_revision: str | Sequence[str] | None = "3f46e4359648"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "invitations",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.Enum("admin", "member", name="invitation_role"), nullable=False),
        sa.Column("invited_by", sa.Uuid(), nullable=True),
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
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_invitations_email_lowercase")),
        sa.ForeignKeyConstraint(
            ["invited_by"],
            ["users.id"],
            name=op.f("fk_invitations_invited_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_invitations_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invitations")),
        sa.UniqueConstraint(
            "organization_id", "email", name=op.f("uq_invitations_organization_id_email")
        ),
    )
    op.create_index(op.f("ix_invitations_email"), "invitations", ["email"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_invitations_email"), table_name="invitations")
    op.drop_table("invitations")
    # Dropping the table leaves the enum type behind; a second upgrade would fail on it.
    sa.Enum(name="invitation_role").drop(op.get_bind())
